"""
Backfill TS and OS scores into leaderboard_archives.
Copies ts_score, os_score, rank_ts, rank_os, ts_sigma, os_sigma
from current rankings into matching archive entries.

Run: cd /app/backend && python3 scripts/backfill_archive_scores.py
"""
import asyncio
import sys
import time

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne


async def main():
    mongo_url = open("/app/backend/.env").read().split("MONGO_URL=")[1].split("\n")[0].strip().strip('"')
    db_name = open("/app/backend/.env").read().split("DB_NAME=")[1].split("\n")[0].strip().strip('"')
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    t0 = time.perf_counter()

    # Load current rankings: paper_id → {ts_score, os_score, ts_sigma, os_sigma, rank_ts, rank_os}
    scores = {}
    async for r in db.rankings.find(
        {},
        {"_id": 0, "paper_id": 1, "category": 1,
         "ts_score": 1, "os_score": 1, "ts_sigma": 1, "os_sigma": 1,
         "rank_ts": 1, "rank_os": 1},
    ):
        scores[r["paper_id"]] = {
            "ts_score": r.get("ts_score"),
            "os_score": r.get("os_score"),
            "ts_sigma": r.get("ts_sigma"),
            "os_sigma": r.get("os_sigma"),
            "rank_ts": r.get("rank_ts"),
            "rank_os": r.get("rank_os"),
        }

    print(f"Loaded {len(scores)} rankings with scores")

    # Update each archive
    total_archives = 0
    total_papers_updated = 0

    async for archive in db.leaderboard_archives.find(
        {"leaderboard": {"$exists": True}},
        {"_id": 1, "category": 1, "label": 1, "leaderboard": 1},
    ):
        lb = archive.get("leaderboard", [])
        if not lb:
            continue

        updated = False
        for entry in lb:
            pid = entry.get("id")
            if pid and pid in scores:
                s = scores[pid]
                for field in ["ts_score", "os_score", "ts_sigma", "os_sigma", "rank_ts", "rank_os"]:
                    if s.get(field) is not None:
                        entry[field] = s[field]
                        updated = True

        if updated:
            await db.leaderboard_archives.update_one(
                {"_id": archive["_id"]},
                {"$set": {"leaderboard": lb}},
            )
            total_archives += 1
            total_papers_updated += len(lb)

    elapsed = time.perf_counter() - t0
    print(f"Done: {total_archives} archives updated, {total_papers_updated} entries enriched in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
