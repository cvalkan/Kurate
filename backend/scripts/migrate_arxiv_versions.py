"""
One-time migration: backfill arxiv_id_base and current_version for all papers.
Handles pre-existing duplicate versions (v1 + v2 both ingested separately)
by merging them — keeping the higher version and archiving the lower.
Idempotent — safe to run multiple times.
"""
import asyncio
import os
import re
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone


def strip_arxiv_version(arxiv_id: str):
    m = re.match(r'^(.+?)v(\d+)$', arxiv_id)
    if m:
        return m.group(1), int(m.group(2))
    return arxiv_id, 1


async def migrate():
    from dotenv import load_dotenv
    load_dotenv()
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "papersumo")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: Backfill arxiv_id_base and current_version
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

        await db.papers.update_one(
            {"_id": doc["_id"]},
            {"$set": {"arxiv_id_base": base, "current_version": version}}
        )
        updated += 1

    print(f"Step 1: Backfilled {updated} papers, skipped {skipped}")

    # Step 2: Find and merge duplicate arxiv_id_base entries
    pipeline = [
        {"$match": {"arxiv_id_base": {"$exists": True}}},
        {"$group": {"_id": "$arxiv_id_base", "count": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    merged = 0
    async for group in db.papers.aggregate(pipeline):
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
            # Snapshot old version
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

            # Push snapshot into keeper's version_history
            await db.papers.update_one(
                {"id": keeper["id"]},
                {"$push": {"version_history": snapshot}}
            )

            # Supersede old paper's matches
            await db.matches.update_many(
                {
                    "$or": [{"paper1_id": old_paper["id"]}, {"paper2_id": old_paper["id"]}],
                    "completed": True,
                },
                {"$set": {"revision_superseded": True, "superseded_at": now_iso}}
            )

            # Delete old ranking entry
            await db.rankings.delete_one({"paper_id": old_paper["id"]})

            # Delete old paper doc
            await db.papers.delete_one({"id": old_paper["id"]})
            merged += 1
            print(f"  Merged duplicate: {old_paper.get('arxiv_id')} → {keeper.get('arxiv_id')}")

    print(f"Step 2: Merged {merged} duplicate papers")

    # Step 3: Create sparse unique index
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

    # Step 4: Verify
    total = await db.papers.count_documents({"arxiv_id": {"$exists": True}})
    with_base = await db.papers.count_documents({"arxiv_id_base": {"$exists": True}})
    dupe_check = []
    async for doc in db.papers.aggregate([
        {"$match": {"arxiv_id_base": {"$exists": True}}},
        {"$group": {"_id": "$arxiv_id_base", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]):
        dupe_check.append(doc)
    print(f"Step 4: {with_base}/{total} arxiv papers have arxiv_id_base, {len(dupe_check)} remaining duplicates")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
