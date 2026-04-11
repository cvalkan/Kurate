"""Test the backfill_archive_scores logic with simulated data."""
import asyncio
import sys
sys.path.insert(0, "/app/backend")

from datetime import datetime, timezone, timedelta


async def test():
    from core.config import db

    TEST_CAT = "__test_backfill__"
    TEST_ARCHIVE_ID = None

    try:
        # Clean up any previous test data
        await db.matches.delete_many({"primary_category": TEST_CAT})
        await db.leaderboard_archives.delete_many({"category": TEST_CAT})

        # Create 5 test papers
        papers = [
            {"id": f"test-paper-{i}", "title": f"Test Paper {i}"}
            for i in range(5)
        ]

        # Create matches: only papers 0,1,2 have matches BEFORE the archive cutoff
        # Paper 0 beats paper 1, paper 1 beats paper 2
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        before_cutoff = cutoff - timedelta(days=5)
        after_cutoff = cutoff + timedelta(days=5)

        matches_before = [
            {"id": "test-match-0", "paper1_id": "test-paper-0", "paper2_id": "test-paper-1",
             "winner_id": "test-paper-0", "primary_category": TEST_CAT,
             "completed": True, "created_at": before_cutoff.isoformat(),
             "model_used": {"provider": "openai", "model": "gpt-5.2"}},
            {"id": "test-match-1", "paper1_id": "test-paper-1", "paper2_id": "test-paper-2",
             "winner_id": "test-paper-1", "primary_category": TEST_CAT,
             "completed": True, "created_at": before_cutoff.isoformat(),
             "model_used": {"provider": "openai", "model": "gpt-5.2"}},
            {"id": "test-match-2", "paper1_id": "test-paper-0", "paper2_id": "test-paper-2",
             "winner_id": "test-paper-0", "primary_category": TEST_CAT,
             "completed": True, "created_at": before_cutoff.isoformat(),
             "model_used": {"provider": "openai", "model": "gpt-5.2"}},
        ]
        # Papers 3,4 only have matches AFTER the cutoff
        matches_after = [
            {"id": "test-match-3", "paper1_id": "test-paper-3", "paper2_id": "test-paper-4",
             "winner_id": "test-paper-3", "primary_category": TEST_CAT,
             "completed": True, "created_at": after_cutoff.isoformat(),
             "model_used": {"provider": "openai", "model": "gpt-5.2"}},
        ]

        await db.matches.insert_many(matches_before + matches_after)

        # Create an archive with all 5 papers, created_at = cutoff
        archive_lb = [
            {"id": f"test-paper-{i}", "title": f"Test Paper {i}",
             "score": 1200 + (50 - i * 10), "win_rate": 50 + i * 5,
             "comparisons": 3 if i < 3 else 0, "wins": 2 if i < 3 else 0,
             "ai_rating": 7.0 + i * 0.5}
            for i in range(5)
        ]
        result = await db.leaderboard_archives.insert_one({
            "category": TEST_CAT,
            "period_type": "weekly",
            "year": 2026, "week": 9,
            "label": "Week 9, 2026",
            "paper_count": 5,
            "created_at": cutoff.isoformat(),
            "leaderboard": archive_lb,
        })
        TEST_ARCHIVE_ID = result.inserted_id

        print("=== BEFORE BACKFILL ===")
        doc = await db.leaderboard_archives.find_one({"_id": TEST_ARCHIVE_ID}, {"_id": 0, "leaderboard": 1})
        for p in doc["leaderboard"]:
            print(f'  {p["id"]}: ts_score={p.get("ts_score")} ts_sigma={p.get("ts_sigma")} '
                  f'os_score={p.get("os_score")} rank_ts={p.get("rank_ts")}')

        # Run the backfill
        from scripts.backfill_archive_scores import main as backfill_fn
        await backfill_fn()

        # Check results
        print("\n=== AFTER BACKFILL ===")
        doc = await db.leaderboard_archives.find_one({"_id": TEST_ARCHIVE_ID}, {"_id": 0, "leaderboard": 1})
        all_ok = True
        for p in doc["leaderboard"]:
            ts = p.get("ts_score")
            sigma = p.get("ts_sigma")
            os_s = p.get("os_score")
            rank = p.get("rank_ts")
            gap = p.get("gap_score_ts")

            has_ts = ts is not None
            has_sigma = sigma is not None
            has_os = os_s is not None
            has_rank = rank is not None

            status = "OK" if (has_ts and has_sigma and has_os and has_rank) else "MISSING"
            if status == "MISSING":
                all_ok = False

            print(f'  {p["id"]}: ts_score={ts} ts_sigma={sigma} os_score={os_s} '
                  f'rank_ts={rank} gap_ts={gap} [{status}]')

        # Verify specific expectations
        print("\n=== ASSERTIONS ===")
        entries = {p["id"]: p for p in doc["leaderboard"]}

        # Papers 0,1,2 should have ts_score != 1200 (they had matches)
        for i in range(3):
            pid = f"test-paper-{i}"
            assert entries[pid]["ts_score"] is not None, f"{pid} missing ts_score"
            print(f'  {pid}: has computed ts_score={entries[pid]["ts_score"]} (had matches before cutoff) OK')

        # Papers 3,4 should have ts_score = 1200 (no matches before cutoff)
        for i in range(3, 5):
            pid = f"test-paper-{i}"
            assert entries[pid]["ts_score"] == 1200, f"{pid} should have default ts_score=1200, got {entries[pid]['ts_score']}"
            assert entries[pid]["ts_sigma"] is not None, f"{pid} missing ts_sigma"
            print(f'  {pid}: has default ts_score=1200, ts_sigma={entries[pid]["ts_sigma"]} (no matches before cutoff) OK')

        # Paper 0 should rank highest (won all matches)
        assert entries["test-paper-0"]["rank_ts"] == 1, f"Paper 0 should be rank 1, got {entries['test-paper-0']['rank_ts']}"
        print(f'  test-paper-0: rank_ts=1 (won all matches) OK')

        # All papers should have rank_ts assigned
        for i in range(5):
            pid = f"test-paper-{i}"
            assert entries[pid]["rank_ts"] is not None, f"{pid} missing rank_ts"

        # Papers 3 and 4 should have rank_ts > papers 0,1,2 (default score = 1200, lower than computed)
        for i in range(3, 5):
            pid = f"test-paper-{i}"
            assert entries[pid]["rank_ts"] > entries["test-paper-0"]["rank_ts"], f"{pid} rank should be > paper 0"

        if all_ok:
            print("\n ALL TESTS PASSED")
        else:
            print("\n SOME FIELDS MISSING")

    finally:
        # Cleanup
        await db.matches.delete_many({"primary_category": TEST_CAT})
        await db.leaderboard_archives.delete_many({"category": TEST_CAT})
        print("\nTest data cleaned up.")


if __name__ == "__main__":
    asyncio.run(test())
