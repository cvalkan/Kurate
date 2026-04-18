"""Create a demo paper with 3 archived versions so the revision UI can be visually reviewed.

Safe to run multiple times — cleans up any prior demo paper first.
Does NOT touch production papers.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from dotenv import load_dotenv
load_dotenv()

DEMO_ID = "demo-revision-paper-abc123"
DEMO_ARXIV_BASE = "9998.99999"


async def main():
    mongo = os.environ["MONGO_URL"]
    dbname = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo)
    db = client[dbname]
    try:
        # Cleanup prior demo
        await db.papers.delete_many({"id": DEMO_ID})
        await db.rankings.delete_many({"paper_id": DEMO_ID})
        await db.matches.delete_many({
            "$or": [{"paper1_id": DEMO_ID}, {"paper2_id": DEMO_ID}]
        })

        now = datetime.now(timezone.utc)
        iso = lambda dt: dt.isoformat()

        # 3 archived versions + current v4
        version_history = [
            {
                "version": 1,
                "arxiv_id": f"{DEMO_ARXIV_BASE}v1",
                "summaries": {"anthropic:claude-opus-4-6:thinking": "v1 summary (archived)." * 5},
                "summary_dates": {},
                "ai_ratings_by_model": {"claude": {"score": 6.2}},
                "ai_rating": 6.2,
                "added_at": iso(now - timedelta(days=90)),
                "archived_at": iso(now - timedelta(days=60)),
                "tournament_reset": True,
                "similarity": None,
                "similarity_basis": None,
                "last_rank": 42,
                "last_ts_score": 1180,
                "last_comparisons": 28,
                "last_win_rate": 0.46,
            },
            {
                "version": 2,
                "arxiv_id": f"{DEMO_ARXIV_BASE}v2",
                "summaries": {"anthropic:claude-opus-4-6:thinking": "v2 summary (archived)." * 5},
                "summary_dates": {},
                "ai_ratings_by_model": {"claude": {"score": 7.1}},
                "ai_rating": 7.1,
                "added_at": iso(now - timedelta(days=60)),
                "archived_at": iso(now - timedelta(days=25)),
                "tournament_reset": True,
                "similarity": 0.72,
                "similarity_basis": "full_text",
                "last_rank": 18,
                "last_ts_score": 1312,
                "last_comparisons": 41,
                "last_win_rate": 0.63,
            },
            {
                "version": 3,
                "arxiv_id": f"{DEMO_ARXIV_BASE}v3",
                "summaries": {"anthropic:claude-opus-4-6:thinking": "v3 summary (archived)." * 5},
                "summary_dates": {},
                "ai_ratings_by_model": {"claude": {"score": 7.4}},
                "ai_rating": 7.4,
                "added_at": iso(now - timedelta(days=25)),
                "archived_at": iso(now - timedelta(days=3)),
                "tournament_reset": False,  # cosmetic edit
                "similarity": 0.97,
                "similarity_basis": "full_text",
                "last_rank": 6,
                "last_ts_score": 1402,
                "last_comparisons": 35,
                "last_win_rate": 0.71,
            },
        ]

        # Current v4 paper document
        paper = {
            "id": DEMO_ID,
            "title": "Demo Paper — Multi-Revision Showcase (v4)",
            "authors": ["Alice Example", "Bob Example"],
            "abstract": "This demo paper exists purely to exercise the revision UI. "
                        "It has three archived versions spanning a 90-day window so the "
                        "version history, revision banner, archived matches tab, and "
                        "leaderboard badge can be reviewed end-to-end.",
            "full_text": "Full text body. " * 50,
            "categories": ["cs.RO"],
            "published": iso(now - timedelta(days=90)),
            "link": f"https://arxiv.org/abs/{DEMO_ARXIV_BASE}v4",
            "pdf_link": f"https://arxiv.org/pdf/{DEMO_ARXIV_BASE}v4",
            "arxiv_id": f"{DEMO_ARXIV_BASE}v4",
            "arxiv_id_base": DEMO_ARXIV_BASE,
            "current_version": 4,
            "revision_epoch": 3,  # 3 resets happened (v1→v2, v2→v3 reset; v3→v4 cosmetic)
            "added_at": iso(now - timedelta(days=90)),
            "revised_at": iso(now - timedelta(days=3)),
            "summaries": {
                "anthropic:claude-opus-4-6:thinking": (
                    "This paper presents a novel methodology that extends the prior "
                    "version with new experimental results and improved theoretical "
                    "grounding. It demonstrates strong performance across multiple "
                    "benchmarks and addresses several limitations noted in earlier "
                    "versions.\n\n{\"score\": 7.8}"
                )
            },
            "summary_dates": {
                "anthropic:claude-opus-4-6:thinking": iso(now - timedelta(days=2))
            },
            "ai_rating": 7.8,
            "ai_ratings_by_model": {"claude": {"score": 7.8}},
            "version_history": version_history,
            "needs_pdf": False,
        }
        # Use replace_one + upsert to avoid conflicts with arxiv_id unique index
        await db.papers.delete_one({"arxiv_id": f"{DEMO_ARXIV_BASE}v4"})
        await db.papers.insert_one(paper)

        # Current ranking with revision_badge
        ranking = {
            "paper_id": DEMO_ID,
            "category": "cs.RO",
            "rank": 15,
            "rank_ts": 12,
            "wins": 8,
            "losses": 4,
            "comparisons": 12,
            "unique_opponents": 11,
            "score": 1350,
            "ts_mu": 28.5,
            "ts_sigma": 4.2,
            "ts_score": 1350,
            "os_score": 1300,
            "os_sigma": 5.1,
            "win_rate": 0.67,
            "wilson_margin": 12.0,
            "ci": 0.12,
            "revision_badge": {
                "version": 4,
                "prev_rank": 6,
                "prev_ts_score": 1402,
                "prev_comparisons": 35,
                "prev_win_rate": 0.71,
                "revised_at": iso(now - timedelta(days=3)),
            },
            "paper_info": {
                "id": DEMO_ID, "title": paper["title"], "authors": paper["authors"],
                "arxiv_id": paper["arxiv_id"], "link": paper["link"],
                "published": paper["published"], "added_at": paper["added_at"],
                "categories": paper["categories"], "ai_rating": paper["ai_rating"],
            },
            "updated_at": iso(now),
        }
        await db.rankings.delete_one({"paper_id": DEMO_ID})
        await db.rankings.insert_one(ranking)

        # Create some ACTIVE (post-v4) matches
        for i in range(4):
            opp_id = f"demo-opp-{i}"
            await db.matches.insert_one({
                "id": str(uuid.uuid4()),
                "paper1_id": DEMO_ID,
                "paper2_id": opp_id,
                "primary_category": "cs.RO",
                "shared_categories": ["cs.RO"],
                "completed": True, "failed": False,
                "winner_id": DEMO_ID if i % 2 == 0 else opp_id,
                "reasoning": f"Active match #{i}: paper shows {'stronger' if i%2==0 else 'weaker'} contribution vs opponent.",
                "model_used": {"model": "claude-opus-4-6"},
                "content_mode": "abstract_plus_summary",
                "created_at": iso(now - timedelta(days=1, hours=i)),
            })

        # Create some SUPERSEDED matches (from old versions)
        for i in range(6):
            opp_id = f"demo-opp-old-{i}"
            await db.matches.insert_one({
                "id": str(uuid.uuid4()),
                "paper1_id": DEMO_ID,
                "paper2_id": opp_id,
                "primary_category": "cs.RO",
                "shared_categories": ["cs.RO"],
                "completed": True, "failed": False,
                "winner_id": DEMO_ID if i % 3 == 0 else opp_id,
                "reasoning": f"Archived v{(i%3)+1} match: stale comparison from pre-revision tournament.",
                "model_used": {"model": "claude-opus-4-6"},
                "content_mode": "abstract_plus_summary",
                "created_at": iso(now - timedelta(days=30 + i)),
                "revision_superseded": True,
                "superseded_at": iso(now - timedelta(days=3)),
            })

        # Stub opponent papers so titles resolve
        for i in range(4):
            opp_id = f"demo-opp-{i}"
            await db.papers.delete_one({"id": opp_id})
            await db.papers.insert_one({
                "id": opp_id,
                "title": f"Demo Opponent Paper {i} (active)",
                "arxiv_id": f"9998.88{i:03d}v1",
                "link": f"https://example.com/{opp_id}",
                "categories": ["cs.RO"],
            })
        for i in range(6):
            opp_id = f"demo-opp-old-{i}"
            await db.papers.delete_one({"id": opp_id})
            await db.papers.insert_one({
                "id": opp_id,
                "title": f"Demo Opponent (archived) {i}",
                "arxiv_id": f"9998.77{i:03d}v1",
                "link": f"https://example.com/{opp_id}",
                "categories": ["cs.RO"],
            })

        print(f"Demo paper created: id={DEMO_ID}")
        print(f"  4 active matches + 6 superseded matches created")
        print(f"  3 archived versions in version_history")
        print(f"  Preview URL: https://kurate-core.preview.emergentagent.com/paper/{DEMO_ID}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
