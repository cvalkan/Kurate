"""
Test the revision handling system end-to-end on preview.
Creates a fake paper, simulates matches, then triggers a revision.
"""
import asyncio
import os
import uuid
import hashlib
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db_name = os.environ.get("DB_NAME", "papersumo")
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

TEST_PAPER_ID = "test-revision-" + str(uuid.uuid4())[:8]
TEST_ARXIV_BASE = "9999.99999"
TEST_CATEGORY = "cs.RO"


async def cleanup():
    """Remove test artifacts."""
    await db.papers.delete_many({"id": {"$regex": "^test-revision-"}})
    await db.rankings.delete_many({"paper_id": {"$regex": "^test-revision-"}})
    await db.matches.delete_many({"paper1_id": {"$regex": "^test-revision-"}})
    await db.matches.delete_many({"paper2_id": {"$regex": "^test-revision-"}})
    print("Cleaned up test data")


async def test_revision_flow():
    await cleanup()
    passed = 0
    failed = 0

    # --- Test 1: Create a v1 paper ---
    print("\n=== Test 1: Create v1 paper ===")
    title = "Test Paper for Revision Handling"
    first_author = "Test Author"
    content_hash = hashlib.sha256(f"{title.lower()}|{first_author.lower()}".encode()).hexdigest()[:16]

    paper_doc = {
        "id": TEST_PAPER_ID,
        "arxiv_id": f"{TEST_ARXIV_BASE}v1",
        "arxiv_id_base": TEST_ARXIV_BASE,
        "current_version": 1,
        "title": title,
        "authors": [first_author],
        "abstract": "This is the v1 abstract.",
        "categories": [TEST_CATEGORY],
        "published": "2026-01-01T00:00:00Z",
        "link": f"http://arxiv.org/abs/{TEST_ARXIV_BASE}v1",
        "pdf_link": f"https://arxiv.org/pdf/{TEST_ARXIV_BASE}v1",
        "full_text": "This is the original v1 full text content. " * 100,
        "needs_pdf": False,
        "dedup_hash": content_hash,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "summaries": {"anthropic:claude-opus-4-6:thinking": "V1 summary from Claude...  " * 20},
        "summary_dates": {"anthropic:claude-opus-4-6:thinking": datetime.now(timezone.utc).isoformat()},
        "ai_ratings_by_model": {"claude": {"score": 6.5, "significance": 7, "rigor": 6, "novelty": 7, "clarity": 8}},
        "ai_rating": 6.5,
    }
    await db.papers.insert_one(paper_doc)

    # Create ranking
    from services.ranking import insert_ranking_for_paper, SCORE_BASE_CONST
    await insert_ranking_for_paper(db, paper_doc)

    # Simulate 10 matches (7 wins, 3 losses)
    other_paper_ids = []
    for i in range(10):
        opp_id = f"test-revision-opp-{i}"
        other_paper_ids.append(opp_id)
        is_win = i < 7
        match_doc = {
            "id": str(uuid.uuid4()),
            "paper1_id": TEST_PAPER_ID,
            "paper2_id": opp_id,
            "dedup_pair": f"{min(TEST_PAPER_ID, opp_id)}|{max(TEST_PAPER_ID, opp_id)}",
            "primary_category": TEST_CATEGORY,
            "winner_id": TEST_PAPER_ID if is_win else opp_id,
            "completed": True,
            "failed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_used": {"provider": "anthropic", "model": "claude-opus-4-6"},
            "reasoning": f"Test match {i}",
            "mode": None,
        }
        # Remove mode=None (let it not exist)
        del match_doc["mode"]
        await db.matches.insert_one(match_doc)

    # Update ranking with fake stats
    await db.rankings.update_one(
        {"paper_id": TEST_PAPER_ID},
        {"$set": {"wins": 7, "losses": 3, "comparisons": 10, "win_rate": 70.0,
                  "rank_ts": 42, "ts_score": 1350}}
    )

    # Verify setup
    paper = await db.papers.find_one({"id": TEST_PAPER_ID}, {"_id": 0, "full_text": 0})
    ranking = await db.rankings.find_one({"paper_id": TEST_PAPER_ID}, {"_id": 0})
    match_count = await db.matches.count_documents({
        "$or": [{"paper1_id": TEST_PAPER_ID}, {"paper2_id": TEST_PAPER_ID}],
        "completed": True, "revision_superseded": {"$ne": True}
    })

    assert paper is not None, "Paper should exist"
    assert paper["current_version"] == 1
    assert paper["arxiv_id"] == f"{TEST_ARXIV_BASE}v1"
    assert "summaries" in paper
    assert ranking["comparisons"] == 10
    assert match_count == 10
    print(f"  v1 paper created: {paper['title']}")
    print(f"  Ranking: rank={ranking['rank_ts']}, ts={ranking['ts_score']}, matches={ranking['comparisons']}")
    passed += 1

    # --- Test 2: Simulate significant revision (v2 with different content) ---
    print("\n=== Test 2: Significant revision (v2, different content) ===")

    from services.scheduler import _handle_revision, _content_similarity

    # Test content similarity function first
    sim_same = _content_similarity("hello world foo bar", "hello world foo bar")
    sim_diff = _content_similarity("hello world foo bar", "completely different text entirely")
    assert sim_same == 1.0, f"Same text should be 1.0, got {sim_same}"
    assert sim_diff < 0.5, f"Different text should be <0.5, got {sim_diff}"
    print(f"  Content similarity: same={sim_same:.2f}, different={sim_diff:.2f}")

    # We can't download a real PDF for a fake arxiv ID. Instead, test _handle_revision
    # by monkeypatching download_and_extract_pdf.
    import services.scheduler as sched_mod
    original_download = sched_mod.download_and_extract_pdf

    async def fake_download(url, **kwargs):
        # Return completely different text for significant revision
        return "This is completely new and different v2 content with novel contributions. " * 100

    sched_mod.download_and_extract_pdf = fake_download

    new_arxiv_data = {
        "arxiv_id": f"{TEST_ARXIV_BASE}v2",
        "pdf_link": f"https://arxiv.org/pdf/{TEST_ARXIV_BASE}v2",
        "link": f"http://arxiv.org/abs/{TEST_ARXIV_BASE}v2",
        "abstract": "This is the v2 abstract with significant changes.",
    }
    settings = {"revision_diff_threshold": 0.95}

    result = await _handle_revision(TEST_PAPER_ID, new_arxiv_data, 2, settings)
    assert result == "revised", f"Expected 'revised', got '{result}'"
    print(f"  Revision result: {result}")

    # Verify paper was updated
    paper_v2 = await db.papers.find_one({"id": TEST_PAPER_ID}, {"_id": 0, "full_text": 0})
    assert paper_v2["current_version"] == 2, f"Version should be 2, got {paper_v2['current_version']}"
    assert paper_v2["arxiv_id"] == f"{TEST_ARXIV_BASE}v2"
    assert "summaries" not in paper_v2, "Summaries should be cleared"
    assert "ai_rating" not in paper_v2, "ai_rating should be cleared"
    assert len(paper_v2.get("version_history", [])) == 1, "Should have 1 archived version"

    vh = paper_v2["version_history"][0]
    assert vh["version"] == 1
    assert vh["arxiv_id"] == f"{TEST_ARXIV_BASE}v1"
    assert "summaries" in vh and vh["summaries"]
    assert vh.get("last_rank") == 42
    assert vh.get("last_ts_score") == 1350
    assert vh.get("last_comparisons") == 10
    assert vh.get("tournament_reset") is True
    print(f"  Version history: v{vh['version']} archived with rank={vh['last_rank']}, ts={vh['last_ts_score']}")
    passed += 1

    # --- Test 3: Matches should be superseded ---
    print("\n=== Test 3: Old matches superseded ===")
    active_matches = await db.matches.count_documents({
        "$or": [{"paper1_id": TEST_PAPER_ID}, {"paper2_id": TEST_PAPER_ID}],
        "completed": True, "revision_superseded": {"$ne": True}
    })
    superseded_matches = await db.matches.count_documents({
        "$or": [{"paper1_id": TEST_PAPER_ID}, {"paper2_id": TEST_PAPER_ID}],
        "revision_superseded": True
    })
    assert active_matches == 0, f"Expected 0 active matches, got {active_matches}"
    assert superseded_matches == 10, f"Expected 10 superseded matches, got {superseded_matches}"
    print(f"  Active: {active_matches}, Superseded: {superseded_matches}")
    passed += 1

    # --- Test 4: Ranking should be reset ---
    print("\n=== Test 4: Ranking reset ===")
    ranking_v2 = await db.rankings.find_one({"paper_id": TEST_PAPER_ID}, {"_id": 0})
    assert ranking_v2["wins"] == 0, f"Wins should be 0, got {ranking_v2['wins']}"
    assert ranking_v2["losses"] == 0
    assert ranking_v2["comparisons"] == 0
    assert ranking_v2["ts_score"] == SCORE_BASE_CONST
    assert "revision_badge" in ranking_v2
    badge = ranking_v2["revision_badge"]
    assert badge["version"] == 2
    assert badge["prev_rank"] == 42
    assert badge["prev_ts_score"] == 1350
    assert badge["prev_comparisons"] == 10
    print(f"  Ranking: wins={ranking_v2['wins']}, ts={ranking_v2['ts_score']}")
    print(f"  Revision badge: v{badge['version']}, prev_rank=#{badge['prev_rank']}, prev_ts={badge['prev_ts_score']}")
    passed += 1

    # --- Test 5: Cosmetic revision (v3, similar content → no tournament reset) ---
    print("\n=== Test 5: Cosmetic revision (v3, tournament kept) ===")

    # First add back some summaries and fake matches for v2
    await db.papers.update_one(
        {"id": TEST_PAPER_ID},
        {"$set": {
            "summaries": {"anthropic:claude-opus-4-6:thinking": "V2 summary... " * 20},
            "ai_rating": 7.0,
            "ai_ratings_by_model": {"claude": {"score": 7.0}},
        }}
    )
    # Add 3 new matches for v2
    for i in range(3):
        await db.matches.insert_one({
            "id": str(uuid.uuid4()),
            "paper1_id": TEST_PAPER_ID,
            "paper2_id": f"test-revision-opp-v2-{i}",
            "dedup_pair": f"{TEST_PAPER_ID}|test-revision-opp-v2-{i}",
            "primary_category": TEST_CATEGORY,
            "winner_id": TEST_PAPER_ID,
            "completed": True, "failed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await db.rankings.update_one(
        {"paper_id": TEST_PAPER_ID},
        {"$set": {"wins": 3, "losses": 0, "comparisons": 3, "win_rate": 100.0,
                  "rank_ts": 10, "ts_score": 1500}}
    )

    # Now simulate v3 with nearly identical text (cosmetic change)
    async def fake_download_cosmetic(url, **kwargs):
        # Return very similar text (just change a few words)
        return "This is completely new and different v2 content with novel contributions! " * 100  # just ! instead of .

    sched_mod.download_and_extract_pdf = fake_download_cosmetic

    new_arxiv_data_v3 = {
        "arxiv_id": f"{TEST_ARXIV_BASE}v3",
        "pdf_link": f"https://arxiv.org/pdf/{TEST_ARXIV_BASE}v3",
        "link": f"http://arxiv.org/abs/{TEST_ARXIV_BASE}v3",
        "abstract": "V3 abstract with minor fixes.",
    }
    result_v3 = await _handle_revision(TEST_PAPER_ID, new_arxiv_data_v3, 3, settings)
    assert result_v3 == "updated", f"Expected 'updated' (cosmetic), got '{result_v3}'"

    paper_v3 = await db.papers.find_one({"id": TEST_PAPER_ID}, {"_id": 0, "full_text": 0})
    assert paper_v3["current_version"] == 3
    assert paper_v3["arxiv_id"] == f"{TEST_ARXIV_BASE}v3"
    assert "summaries" not in paper_v3, "Summaries should be cleared (re-evaluate even cosmetic)"
    assert len(paper_v3.get("version_history", [])) == 2, "Should have 2 archived versions"

    # Tournament should NOT be reset for cosmetic
    ranking_v3 = await db.rankings.find_one({"paper_id": TEST_PAPER_ID}, {"_id": 0})
    assert ranking_v3["comparisons"] == 3, f"Tournament should be kept (3 matches), got {ranking_v3['comparisons']}"
    assert ranking_v3["wins"] == 3

    # v2 matches should still be active
    active_v2 = await db.matches.count_documents({
        "$or": [{"paper1_id": TEST_PAPER_ID}, {"paper2_id": TEST_PAPER_ID}],
        "completed": True, "revision_superseded": {"$ne": True}
    })
    assert active_v2 == 3, f"Expected 3 active v2 matches, got {active_v2}"

    vh3 = paper_v3["version_history"][1]
    assert vh3["version"] == 2
    assert vh3["tournament_reset"] is False
    print(f"  Result: {result_v3}")
    print(f"  Tournament kept: {ranking_v3['comparisons']} matches, rank_ts={ranking_v3['rank_ts']}")
    print(f"  Version history: {len(paper_v3['version_history'])} versions archived")
    passed += 1

    # --- Test 6: API endpoint returns version data ---
    print("\n=== Test 6: Paper detail API ===")
    import httpx
    api_url = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
    if not api_url.startswith("http"):
        api_url = f"https://{api_url}"

    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(f"{api_url}/api/papers/{TEST_PAPER_ID}")
        if resp.status_code == 200:
            data = resp.json()
            p = data["paper"]
            assert p.get("current_version") == 3, f"API should show v3, got {p.get('current_version')}"
            assert len(p.get("version_history", [])) == 2
            assert len(data.get("matches", [])) == 3, f"Active matches should be 3, got {len(data.get('matches', []))}"
            assert len(data.get("archived_matches", [])) == 10, f"Archived matches should be 10, got {len(data.get('archived_matches', []))}"
            if p.get("revision_badge"):
                print(f"  Revision badge: v{p['revision_badge']['version']}, prev_rank=#{p['revision_badge']['prev_rank']}")
            print(f"  API: v{p['current_version']}, {len(p['version_history'])} archived, "
                  f"{len(data['matches'])} active + {len(data.get('archived_matches', []))} archived matches")
            passed += 1
        else:
            print(f"  API ERROR: {resp.status_code}")
            failed += 1

    # --- Test 7: strip_arxiv_version utility ---
    print("\n=== Test 7: strip_arxiv_version ===")
    from services.arxiv import strip_arxiv_version
    assert strip_arxiv_version("2602.12345v2") == ("2602.12345", 2)
    assert strip_arxiv_version("2602.12345v1") == ("2602.12345", 1)
    assert strip_arxiv_version("2602.12345") == ("2602.12345", 1)
    assert strip_arxiv_version("math/0601001v3") == ("math/0601001", 3)
    print("  All assertions passed")
    passed += 1

    # Restore original
    sched_mod.download_and_extract_pdf = original_download

    # Cleanup
    await cleanup()

    print(f"\n{'='*50}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_revision_flow())
    exit(0 if success else 1)
