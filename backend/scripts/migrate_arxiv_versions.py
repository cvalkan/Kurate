"""
One-time migration: backfill arxiv_id_base and current_version for all papers.

Handles pre-existing duplicate versions (v1 + v2 both ingested separately) by
merging them — keeping the higher version and archiving the lower.

Safety guarantees (hardened for production):
  * Requires MONGO_URL env var (fails fast if unset — no silent localhost fallback).
  * Pauses the scheduler via `db.settings.key=global paused=true` BEFORE touching
    papers, restores the prior paused flag on completion. Prevents new
    inserts creating duplicates between Step 2 (merge) and Step 3 (unique index).
  * Step 2 loops until no duplicates remain (defensive against insert races).
  * --dry-run flag: logs what would change without writing.
  * Connection cleanup in finally.

Idempotent — safe to run multiple times.
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient


def strip_arxiv_version(arxiv_id: str):
    m = re.match(r'^(.+?)v(\d+)$', arxiv_id)
    if m:
        return m.group(1), int(m.group(2))
    return arxiv_id, 1


async def _find_duplicate_bases(db):
    """Return list of arxiv_id_base values that have > 1 paper."""
    dupes = []
    async for group in db.papers.aggregate([
        {"$match": {"arxiv_id_base": {"$exists": True}}},
        {"$group": {"_id": "$arxiv_id_base", "count": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]):
        dupes.append(group)
    return dupes


async def migrate(dry_run: bool = False):
    from dotenv import load_dotenv
    load_dotenv()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url:
        print("ERROR: MONGO_URL environment variable is not set. "
              "Refusing to run migration against an unknown database.", file=sys.stderr)
        sys.exit(2)
    if not db_name:
        print("ERROR: DB_NAME environment variable is not set.", file=sys.stderr)
        sys.exit(2)

    print(f"Target: {mongo_url[:60]}... / db={db_name}  dry_run={dry_run}")

    client = AsyncIOMotorClient(mongo_url)
    now_iso = datetime.now(timezone.utc).isoformat()
    pause_marker_key = "_migration_arxiv_versions_paused_on"

    try:
        db = client[db_name]

        # ── Step 0: pause scheduler (skip in dry-run) ──────────────────────
        prior_paused = None
        if not dry_run:
            settings_doc = await db.settings.find_one({"key": "global"}) or {}
            prior_paused = settings_doc.get("paused", False)
            await db.settings.update_one(
                {"key": "global"},
                {"$set": {"paused": True, pause_marker_key: now_iso}},
                upsert=True,
            )
            print(f"Step 0: scheduler paused (prior state: paused={prior_paused}). "
                  f"Waiting 5s for in-flight cycles to drain...")
            await asyncio.sleep(5)
        else:
            print("Step 0: DRY-RUN — skipping scheduler pause")

        # ── Step 1: Backfill arxiv_id_base and current_version ─────────────
        updated = 0
        skipped = 0
        async for doc in db.papers.find(
            {"arxiv_id": {"$exists": True, "$ne": None}},
            {"_id": 1, "arxiv_id": 1, "arxiv_id_base": 1, "current_version": 1}
        ):
            arxiv_id = doc["arxiv_id"]
            base, version = strip_arxiv_version(arxiv_id)

            if doc.get("arxiv_id_base") == base and doc.get("current_version") == version:
                skipped += 1
                continue

            if not dry_run:
                await db.papers.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"arxiv_id_base": base, "current_version": version}}
                )
            updated += 1

        print(f"Step 1: {'Would backfill' if dry_run else 'Backfilled'} "
              f"{updated} papers, skipped {skipped}")

        # ── Step 2: Merge duplicate arxiv_id_base entries (loop until clean) ─
        total_merged = 0
        iterations = 0
        while True:
            iterations += 1
            if iterations > 10:
                print("WARN: Step 2 aborting after 10 iterations — manual investigation needed")
                break
            groups = await _find_duplicate_bases(db)
            if not groups:
                break
            print(f"Step 2 iter {iterations}: found {len(groups)} duplicate bases")
            merged_this_iter = 0

            for group in groups:
                base = group["_id"]
                paper_ids = group["ids"]

                # Load all versions
                papers = []
                async for p in db.papers.find(
                    {"id": {"$in": paper_ids}},
                    {"_id": 0, "id": 1, "arxiv_id": 1, "current_version": 1, "summaries": 1,
                     "summary_dates": 1, "ai_ratings_by_model": 1, "ai_rating": 1, "added_at": 1,
                     "comparisons": 1}
                ):
                    papers.append(p)

                # Sort by version desc — keep highest
                papers.sort(key=lambda p: p.get("current_version", 1), reverse=True)
                keeper = papers[0]
                to_archive = papers[1:]

                for old_paper in to_archive:
                    old_ranking = await db.rankings.find_one(
                        {"paper_id": old_paper["id"]},
                        {"_id": 0, "rank_ts": 1, "ts_score": 1, "comparisons": 1, "win_rate": 1}
                    )
                    snapshot = {
                        "version": old_paper.get("current_version", 1),
                        "arxiv_id": old_paper.get("arxiv_id"),
                        "summaries": old_paper.get("summaries", {}),
                        "summary_dates": old_paper.get("summary_dates", {}),
                        "ai_ratings_by_model": old_paper.get("ai_ratings_by_model", {}),
                        "ai_rating": old_paper.get("ai_rating"),
                        "added_at": old_paper.get("added_at"),
                        "archived_at": now_iso,
                        "tournament_reset": True,
                        "merged_from_duplicate": True,
                    }
                    if old_ranking:
                        snapshot["last_rank"] = old_ranking.get("rank_ts")
                        snapshot["last_ts_score"] = old_ranking.get("ts_score")
                        snapshot["last_comparisons"] = old_ranking.get("comparisons", 0)
                        snapshot["last_win_rate"] = old_ranking.get("win_rate", 0)

                    if dry_run:
                        print(f"  [dry-run] would merge {old_paper.get('arxiv_id')} → "
                              f"{keeper.get('arxiv_id')} (base={base})")
                    else:
                        await db.papers.update_one(
                            {"id": keeper["id"]},
                            {"$push": {"version_history": snapshot}}
                        )
                        await db.matches.update_many(
                            {
                                "$or": [{"paper1_id": old_paper["id"]}, {"paper2_id": old_paper["id"]}],
                                "completed": True,
                            },
                            {"$set": {"revision_superseded": True, "superseded_at": now_iso}}
                        )
                        await db.rankings.delete_one({"paper_id": old_paper["id"]})
                        await db.papers.delete_one({"id": old_paper["id"]})
                        print(f"  Merged duplicate: {old_paper.get('arxiv_id')} → {keeper.get('arxiv_id')}")
                    merged_this_iter += 1

            total_merged += merged_this_iter
            if dry_run:
                # Dry-run can't actually clear duplicates — stop after one iter
                print(f"Step 2 dry-run: would merge {merged_this_iter} papers, stopping loop")
                break
            if merged_this_iter == 0:
                break

        print(f"Step 2: {'Would merge' if dry_run else 'Merged'} {total_merged} duplicate papers "
              f"(in {iterations} iteration(s))")

        # ── Step 3: Create sparse unique index ─────────────────────────────
        if not dry_run:
            existing_indexes = await db.papers.index_information()
            if "arxiv_id_base_1" not in existing_indexes:
                await db.papers.create_index(
                    "arxiv_id_base",
                    unique=True,
                    sparse=True,
                    name="arxiv_id_base_1"
                )
                print("Step 3: Created unique sparse index on arxiv_id_base")
            else:
                print("Step 3: Index arxiv_id_base_1 already exists")
        else:
            print("Step 3: DRY-RUN — skipping index creation")

        # ── Step 4: Verify ─────────────────────────────────────────────────
        total = await db.papers.count_documents({"arxiv_id": {"$exists": True}})
        with_base = await db.papers.count_documents({"arxiv_id_base": {"$exists": True}})
        remaining = await _find_duplicate_bases(db)
        print(f"Step 4: {with_base}/{total} arxiv papers have arxiv_id_base, "
              f"{len(remaining)} remaining duplicates")
        if remaining and not dry_run:
            print("WARN: duplicates remain — manual investigation required.", file=sys.stderr)

    finally:
        # ── Step 5: restore scheduler state ────────────────────────────────
        if not dry_run:
            try:
                prior_doc = await client[db_name].settings.find_one({"key": "global"}) or {}
                if pause_marker_key in prior_doc:
                    restore = {"paused": bool(prior_paused)} if prior_paused is not None else {"paused": False}
                    await client[db_name].settings.update_one(
                        {"key": "global"},
                        {"$set": restore, "$unset": {pause_marker_key: ""}}
                    )
                    print(f"Step 5: scheduler paused state restored to paused={restore['paused']}")
            except Exception as e:
                print(f"WARN: failed to restore scheduler pause state: {e}", file=sys.stderr)
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate arxiv_id → arxiv_id_base + current_version")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log changes without writing. Skips scheduler pause and index creation.")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
