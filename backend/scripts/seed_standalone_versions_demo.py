"""Seed 3 standalone paper versions (v1/v2/v3) sharing arxiv_id_base.

Validates the new standalone-paper-per-version model end-to-end:
  * 3 separate paper documents, each with its own UUID
  * v1 and v2 are frozen (is_latest_version=False), v3 is latest
  * Each version has its own ranking row with different stats
  * Each version has its own set of matches
  * arxiv_id_base shared across all three (non-unique index)

Safe to run multiple times — cleans up any prior demo state first.
Does NOT touch production papers.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.ranking import SCORE_BASE_CONST

BASE = "8888.77777"
V1_ID = "demo-multi-v1-abc"
V2_ID = "demo-multi-v2-abc"
V3_ID = "demo-multi-v3-abc"
CATEGORY = "cs.RO"


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        # Cleanup prior demo
        await db.papers.delete_many({"id": {"$in": [V1_ID, V2_ID, V3_ID]}})
        await db.papers.delete_many({"arxiv_id_base": BASE})
        await db.papers.delete_many({"id": {"$regex": "^demo-multi-opp-"}})
        await db.rankings.delete_many({"paper_id": {"$in": [V1_ID, V2_ID, V3_ID]}})
        await db.matches.delete_many({
            "$or": [
                {"paper1_id": {"$in": [V1_ID, V2_ID, V3_ID]}},
                {"paper2_id": {"$in": [V1_ID, V2_ID, V3_ID]}},
            ]
        })

        now = datetime.now(timezone.utc)
        iso = lambda dt: dt.isoformat()

        common = {
            "title": "Standalone Versions Demo — v1/v2/v3 Parallel Matmul Kernels for Edge Robotics",
            "authors": ["Alice Example", "Bob Example", "Carol Example"],
            "categories": [CATEGORY],
            "abstract": "We introduce an efficient matrix-multiplication kernel optimized for "
                        "low-power robotics inference, with three successive revisions reflecting "
                        "feedback, new experimental results, and a theoretical framing extension.",
        }

        # v1 — published 90 days ago, frozen 60 days ago
        v1 = {
            **common,
            "id": V1_ID,
            "arxiv_id": f"{BASE}v1",
            "arxiv_id_base": BASE,
            "current_version": 1,
            "is_latest_version": False,
            "frozen_at": iso(now - timedelta(days=60)),
            "superseded_by_paper_id": V2_ID,
            "published": iso(now - timedelta(days=90)),
            "added_at": iso(now - timedelta(days=90)),
            "link": f"https://arxiv.org/abs/{BASE}v1",
            "pdf_link": f"https://arxiv.org/pdf/{BASE}v1",
            "summaries": {
                "anthropic:claude-opus-4-6:thinking": (
                    "This v1 introduces an efficient matmul kernel. The analysis is promising "
                    "but some experiments are limited.\n\n{\"score\": 6.8}"
                )
            },
            "summary_dates": {"anthropic:claude-opus-4-6:thinking": iso(now - timedelta(days=89))},
            "ai_rating": 6.8,
        }

        # v2 — frozen 25 days ago
        v2 = {
            **common,
            "id": V2_ID,
            "arxiv_id": f"{BASE}v2",
            "arxiv_id_base": BASE,
            "current_version": 2,
            "is_latest_version": False,
            "frozen_at": iso(now - timedelta(days=25)),
            "superseded_by_paper_id": V3_ID,
            "previous_version_paper_id": V1_ID,
            "published": iso(now - timedelta(days=60)),
            "added_at": iso(now - timedelta(days=60)),
            "link": f"https://arxiv.org/abs/{BASE}v2",
            "pdf_link": f"https://arxiv.org/pdf/{BASE}v2",
            "summaries": {
                "anthropic:claude-opus-4-6:thinking": (
                    "This v2 adds expanded ablation studies and a new benchmark set. The "
                    "theoretical grounding is clearer.\n\n{\"score\": 7.4}"
                )
            },
            "summary_dates": {"anthropic:claude-opus-4-6:thinking": iso(now - timedelta(days=59))},
            "ai_rating": 7.4,
        }

        # v3 — current latest
        v3 = {
            **common,
            "id": V3_ID,
            "arxiv_id": f"{BASE}v3",
            "arxiv_id_base": BASE,
            "current_version": 3,
            "is_latest_version": True,
            "previous_version_paper_id": V2_ID,
            "published": iso(now - timedelta(days=25)),
            "added_at": iso(now - timedelta(days=25)),
            "link": f"https://arxiv.org/abs/{BASE}v3",
            "pdf_link": f"https://arxiv.org/pdf/{BASE}v3",
            "summaries": {
                "anthropic:claude-opus-4-6:thinking": (
                    "This v3 broadens the evaluation to real-world edge-robotics scenarios and "
                    "introduces a theoretical analysis connecting kernel tiling to cache "
                    "locality — the strongest presentation so far.\n\n{\"score\": 8.1}"
                )
            },
            "summary_dates": {"anthropic:claude-opus-4-6:thinking": iso(now - timedelta(days=2))},
            "ai_rating": 8.1,
        }

        await db.papers.insert_many([v1, v2, v3])

        # Seed opponent stubs (7)
        for i in range(7):
            oid = f"demo-multi-opp-{i}"
            await db.papers.insert_one({
                "id": oid,
                "title": f"Comparison Opponent {i} — Accelerated Kernels on FPGA",
                "arxiv_id": f"7777.66{i:03d}v1",
                "categories": [CATEGORY],
                "link": f"https://arxiv.org/abs/7777.66{i:03d}v1",
            })

        # Rankings per version — top-level denormalized fields match prod schema
        def _rank(pid, paper, rank_ts, wins, losses, comps, score, ts_mu, ts_sigma, win_rate, is_latest, frozen_at=None):
            r = {
                "paper_id": pid, "category": CATEGORY,
                "rank_ts": rank_ts, "rank": rank_ts,
                "wins": wins, "losses": losses, "comparisons": comps, "unique_opponents": comps,
                "score": score, "ts_score": score,
                "ts_mu": ts_mu, "ts_sigma": ts_sigma,
                "ci": 0.18, "wilson_margin": 18.0, "win_rate": win_rate,
                "is_latest_version": is_latest,
                "updated_at": frozen_at or iso(now),
                # Denormalized paper fields
                "title": paper["title"],
                "authors": paper["authors"],
                "arxiv_id": paper["arxiv_id"],
                "link": paper["link"],
                "published": paper["published"],
                "added_at": paper["added_at"],
                "categories": paper["categories"],
                "current_version": paper["current_version"],
                "ai_rating": paper["ai_rating"],
            }
            if frozen_at:
                r["frozen_at"] = frozen_at
            return r

        await db.rankings.insert_many([
            _rank(V1_ID, v1, 42, 12, 14, 26, 1180, 24.2, 2.8, 0.46, False, v1["frozen_at"]),
            _rank(V2_ID, v2, 18, 21, 12, 33, 1312, 27.1, 2.3, 0.63, False, v2["frozen_at"]),
            _rank(V3_ID, v3, 8, 4, 1, 5, 1389, 28.4, 4.1, 0.80, True),
        ])

        # Matches — each version gets its own distinct matches (no sharing)
        match_specs = [
            (V1_ID, 6, "v1 — comparison from pre-revision era"),
            (V2_ID, 4, "v2 — mid-revision comparison, frozen"),
            (V3_ID, 3, "v3 — live comparison"),
        ]
        for pid, n, reasoning_prefix in match_specs:
            for i in range(n):
                opp = f"demo-multi-opp-{i % 7}"
                won = (i % 2 == 0)
                await db.matches.insert_one({
                    "id": str(uuid.uuid4()),
                    "paper1_id": pid,
                    "paper2_id": opp,
                    "primary_category": CATEGORY,
                    "shared_categories": [CATEGORY],
                    "completed": True, "failed": False,
                    "winner_id": pid if won else opp,
                    "reasoning": f"{reasoning_prefix} (match #{i}).",
                    "model_used": {"model": "claude-opus-4-6"},
                    "content_mode": "abstract_plus_summary",
                    "created_at": iso(now - timedelta(days=30 - i)),
                })

        print("Standalone-paper-per-version demo ready:")
        print(f"  v1 URL: https://research-discovery-2.preview.emergentagent.com/paper/{V1_ID}")
        print(f"  v2 URL: https://research-discovery-2.preview.emergentagent.com/paper/{V2_ID}")
        print(f"  v3 URL: https://research-discovery-2.preview.emergentagent.com/paper/{V3_ID} (latest)")
        print(f"  arxiv_id_base = {BASE}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
