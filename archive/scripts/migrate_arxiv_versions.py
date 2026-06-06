"""
One-time migration: backfill `arxiv_id_base`, `current_version`, and
`is_latest_version` fields on existing papers so the revision system
(standalone-paper-per-version model) can operate cleanly.

Backfill only — does NOT touch matches, rankings, or merge any duplicates.
If duplicate arxiv_id_base groups exist (from the legacy in-place model),
they are preserved: the highest version is flagged is_latest_version=True,
the rest is_latest_version=False. Their rankings are flagged accordingly too.

Safety guarantees (hardened for production):
  * Requires MONGO_URL + DB_NAME env vars (fails fast if unset).
  * Pauses the scheduler via `db.settings.key=global paused=true` BEFORE
    writing, restores the prior paused flag in `finally`.
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

        # ── Step 1: Backfill arxiv_id_base + current_version on papers ─────
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

        # ── Step 2: Flag is_latest_version on papers (and their rankings) ──
        # For each arxiv_id_base group, mark the highest version as latest and
        # everything else as frozen. Papers without arxiv_id_base are left alone
        # (they're non-arXiv or pre-arXiv; treated as latest by the app default).
        latest_set = 0
        frozen_set = 0
        async for group in db.papers.aggregate([
            {"$match": {"arxiv_id_base": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$arxiv_id_base",
                        "docs": {"$push": {"id": "$id", "version": "$current_version"}}}}
        ]):
            docs = group["docs"]
            if not docs:
                continue
            # Keep the highest version as latest
            docs.sort(key=lambda d: d.get("version", 1) or 1, reverse=True)
            latest_id = docs[0]["id"]
            if not dry_run:
                await db.papers.update_one(
                    {"id": latest_id},
                    {"$set": {"is_latest_version": True}, "$unset": {"frozen_at": "", "superseded_by_paper_id": ""}}
                )
                await db.rankings.update_one(
                    {"paper_id": latest_id},
                    {"$set": {"is_latest_version": True}}
                )
            latest_set += 1
            # Freeze everything else
            for stale in docs[1:]:
                if not dry_run:
                    await db.papers.update_one(
                        {"id": stale["id"]},
                        {"$set": {"is_latest_version": False, "frozen_at": now_iso,
                                  "superseded_by_paper_id": latest_id}}
                    )
                    await db.rankings.update_one(
                        {"paper_id": stale["id"]},
                        {"$set": {"is_latest_version": False, "frozen_at": now_iso}}
                    )
                frozen_set += 1

        print(f"Step 2: {'Would flag' if dry_run else 'Flagged'} "
              f"{latest_set} latest papers, {frozen_set} frozen papers")

        # ── Step 3: Ensure non-unique sparse index on arxiv_id_base ────────
        if not dry_run:
            existing = await db.papers.index_information()
            base_idx = existing.get("arxiv_id_base_1")
            if base_idx and base_idx.get("unique"):
                print("Step 3: Existing unique index detected — dropping and replacing with non-unique "
                      "(the standalone-paper-per-version model requires shared base across docs)")
                await db.papers.drop_index("arxiv_id_base_1")
                base_idx = None
            if not base_idx:
                await db.papers.create_index(
                    "arxiv_id_base", sparse=True, name="arxiv_id_base_1"
                )
                print("Step 3: Created non-unique sparse index on arxiv_id_base")
            else:
                print("Step 3: Non-unique sparse index already in place")
        else:
            print("Step 3: DRY-RUN — skipping index work")

        # ── Step 4: Verify ─────────────────────────────────────────────────
        total = await db.papers.count_documents({"arxiv_id": {"$exists": True}})
        with_base = await db.papers.count_documents({"arxiv_id_base": {"$exists": True}})
        latest = await db.papers.count_documents({"is_latest_version": True})
        frozen = await db.papers.count_documents({"is_latest_version": False})
        print(f"Step 4: {with_base}/{total} arxiv papers have arxiv_id_base; "
              f"latest_flag={latest}, frozen_flag={frozen}")

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
    parser = argparse.ArgumentParser(description="Backfill arxiv_id_base, current_version, is_latest_version")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log changes without writing. Skips scheduler pause and index changes.")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
