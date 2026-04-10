"""
One-time backfill: compute per-model incremental OpenSkill (ThurstoneMosteller)
for all existing papers by replaying match history per model per category.

Stores model_os.{model_key}.mu and model_os.{model_key}.sigma on each rankings doc.

Run: cd /app/backend && python3 scripts/backfill_model_openskill.py
"""
import asyncio
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from openskill.models import ThurstoneMostellerFull
from pymongo import UpdateOne


async def main():
    from core.config import db

    model = ThurstoneMostellerFull()
    DEFAULT_MU = 25.0
    DEFAULT_SIGMA = 25.0 / 3

    categories = []
    async for doc in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}}},
        {"$group": {"_id": "$primary_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]):
        categories.append((doc["_id"], doc["count"]))

    print(f"Categories to backfill: {len(categories)}")
    total_updated = 0
    t0 = time.perf_counter()

    for cat, match_count in categories:
        cat_t0 = time.perf_counter()

        matches = []
        async for m in db.matches.find(
            {"primary_category": cat, "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1, "model_used": 1, "created_at": 1},
        ).sort("created_at", 1):
            if m.get("winner_id") and m.get("model_used"):
                matches.append(m)

        model_ratings = defaultdict(dict)

        _OPUS_MERGE = {
            "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
            "anthropic/claude-opus-4-6": "anthropic/claude-opus",
        }

        for m in matches:
            p1, p2, winner = m["paper1_id"], m["paper2_id"], m["winner_id"]
            mu = m["model_used"]
            raw_key = f"{mu.get('provider', 'unknown')}/{mu.get('model', 'unknown')}"
            mk = _OPUS_MERGE.get(raw_key, raw_key).replace(".", "_")

            if p1 not in model_ratings[mk]:
                model_ratings[mk][p1] = (DEFAULT_MU, DEFAULT_SIGMA)
            if p2 not in model_ratings[mk]:
                model_ratings[mk][p2] = (DEFAULT_MU, DEFAULT_SIGMA)

            r1 = model.rating(mu=model_ratings[mk][p1][0], sigma=model_ratings[mk][p1][1])
            r2 = model.rating(mu=model_ratings[mk][p2][0], sigma=model_ratings[mk][p2][1])

            if winner == p1:
                [[new_w], [new_l]] = model.rate([[r1], [r2]], ranks=[1, 2])
                model_ratings[mk][p1] = (new_w.mu, new_w.sigma)
                model_ratings[mk][p2] = (new_l.mu, new_l.sigma)
            else:
                [[new_w], [new_l]] = model.rate([[r2], [r1]], ranks=[1, 2])
                model_ratings[mk][p2] = (new_w.mu, new_w.sigma)
                model_ratings[mk][p1] = (new_l.mu, new_l.sigma)

        paper_updates = defaultdict(dict)
        for mk, ratings in model_ratings.items():
            for paper_id, (mu, sigma) in ratings.items():
                paper_updates[paper_id][mk] = {"mu": mu, "sigma": sigma}

        ops = []
        for paper_id, model_data in paper_updates.items():
            set_fields = {}
            for mk, vals in model_data.items():
                set_fields[f"model_os.{mk}"] = vals
            ops.append(UpdateOne(
                {"paper_id": paper_id, "category": cat},
                {"$set": set_fields},
            ))

        if ops:
            result = await db.rankings.bulk_write(ops, ordered=False)
            total_updated += result.modified_count

        n_models = len(model_ratings)
        n_papers = len(paper_updates)
        cat_elapsed = time.perf_counter() - cat_t0
        print(f"  {cat}: {len(matches)} matches, {n_models} models, {n_papers} papers, {cat_elapsed:.1f}s")

    elapsed = time.perf_counter() - t0
    print(f"\nDone: {total_updated} rankings updated across {len(categories)} categories in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
