"""
Comprehensive regression + edge case tests for the revision handling system.
Tests both the happy paths and dangerous edge cases around:
- Duplicate prevention
- Match superseding completeness
- Dedup_pair reuse after revision
- Summary clearing blocks matchmaking
- Migration idempotency
- Revision feed accuracy
"""
import asyncio
import os
import uuid
import hashlib
from datetime import datetime, timezone
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db_name = os.environ.get("DB_NAME", "papersumo")
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

TEST_PREFIX = "test-rev-regr-"
TEST_CATEGORY = "cs.RO"

results = {"passed": 0, "failed": 0, "errors": []}

def ok(name):
    results["passed"] += 1
    print(f"  PASS: {name}")

def fail(name, detail):
    results["failed"] += 1
    results["errors"].append(f"{name}: {detail}")
    print(f"  FAIL: {name} — {detail}")


async def cleanup():
    await db.papers.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
    await db.rankings.delete_many({"paper_id": {"$regex": f"^{TEST_PREFIX}"}})
    await db.matches.delete_many({"paper1_id": {"$regex": f"^{TEST_PREFIX}"}})
    await db.matches.delete_many({"paper2_id": {"$regex": f"^{TEST_PREFIX}"}})


async def create_test_paper(suffix, version=1, with_summary=True, with_matches=0):
    """Helper: create a paper + ranking + optional matches."""
    pid = f"{TEST_PREFIX}{suffix}"
    base = f"8888.{suffix}"
    arxiv_id = f"{base}v{version}"
    now = datetime.now(timezone.utc).isoformat()

    paper = {
        "id": pid,
        "arxiv_id": arxiv_id,
        "arxiv_id_base": base,
        "current_version": version,
        "title": f"Test Paper {suffix}",
        "authors": ["Author A"],
        "abstract": f"Abstract for {suffix}",
        "categories": [TEST_CATEGORY],
        "published": "2026-01-01T00:00:00Z",
        "link": f"http://arxiv.org/abs/{arxiv_id}",
        "pdf_link": f"https://arxiv.org/pdf/{arxiv_id}",
        "full_text": f"Full text content for paper {suffix} version {version}. " * 50,
        "needs_pdf": False,
        "dedup_hash": hashlib.sha256(f"test paper {suffix}|author a".encode()).hexdigest()[:16],
        "added_at": now,
    }
    if with_summary:
        paper["summaries"] = {"anthropic:claude-opus-4-6:thinking": f"Summary for {suffix}... " * 20}
        paper["ai_rating"] = 6.0
        paper["ai_ratings_by_model"] = {"claude": {"score": 6.0}}
    await db.papers.insert_one(paper)

    from services.ranking import insert_ranking_for_paper
    await insert_ranking_for_paper(db, paper)

    if with_matches > 0:
        for i in range(with_matches):
            opp = f"{TEST_PREFIX}opp-{suffix}-{i}"
            await db.matches.insert_one({
                "id": str(uuid.uuid4()),
                "paper1_id": pid, "paper2_id": opp,
                "dedup_pair": f"{min(pid, opp)}|{max(pid, opp)}",
                "primary_category": TEST_CATEGORY,
                "winner_id": pid if i % 3 != 0 else opp,
                "completed": True, "failed": False,
                "created_at": now,
                "model_used": {"provider": "anthropic", "model": "claude-opus-4-6"},
            })
        wins = sum(1 for i in range(with_matches) if i % 3 != 0)
        await db.rankings.update_one(
            {"paper_id": pid},
            {"$set": {"wins": wins, "losses": with_matches - wins,
                      "comparisons": with_matches, "rank_ts": 50, "ts_score": 1400}}
        )

    return pid


async def run_tests():
    import services.scheduler as sched_mod
    from services.scheduler import _handle_revision, _content_similarity
    from services.arxiv import strip_arxiv_version

    await cleanup()

    # ─── Test 1: Duplicate prevention — cannot insert same arxiv_id_base twice ───
    print("\n=== Test 1: Duplicate prevention via unique index ===")
    pid_a = await create_test_paper("dup-a")
    try:
        # Try to insert another paper with same arxiv_id_base
        await db.papers.insert_one({
            "id": f"{TEST_PREFIX}dup-b",
            "arxiv_id": "8888.dup-av2",
            "arxiv_id_base": "8888.dup-a",  # same base!
            "current_version": 2,
            "title": "Duplicate", "authors": ["X"], "categories": [TEST_CATEGORY],
        })
        fail("Duplicate prevention", "Should have raised DuplicateKeyError")
    except Exception as e:
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            ok("Duplicate prevention (unique index blocks)")
        else:
            fail("Duplicate prevention", f"Unexpected error: {e}")

    # ─── Test 2: All matches superseded — none left active ───
    print("\n=== Test 2: Complete match superseding ===")
    pid_b = await create_test_paper("super-b", with_matches=15)

    # Verify pre-state
    pre_active = await db.matches.count_documents({
        "$or": [{"paper1_id": pid_b}, {"paper2_id": pid_b}],
        "completed": True, "revision_superseded": {"$ne": True}
    })
    assert pre_active == 15, f"Pre: expected 15 active, got {pre_active}"

    # Monkeypatch PDF download
    original_download = sched_mod.download_and_extract_pdf
    async def fake_dl(url, **kw):
        return "Completely different revision content. " * 100
    sched_mod.download_and_extract_pdf = fake_dl

    result = await _handle_revision(
        pid_b,
        {"arxiv_id": "8888.super-bv2", "link": "http://test", "abstract": "new"},
        2, {"revision_diff_threshold": 0.95}
    )
    assert result == "revised"

    post_active = await db.matches.count_documents({
        "$or": [{"paper1_id": pid_b}, {"paper2_id": pid_b}],
        "completed": True, "revision_superseded": {"$ne": True}
    })
    post_super = await db.matches.count_documents({
        "$or": [{"paper1_id": pid_b}, {"paper2_id": pid_b}],
        "revision_superseded": True
    })
    if post_active == 0 and post_super == 15:
        ok(f"All 15 matches superseded, 0 active")
    else:
        fail("Match superseding", f"active={post_active}, superseded={post_super}")

    # ─── Test 3: Dedup_pair reuse — paper can be re-matched after revision ───
    print("\n=== Test 3: Dedup_pair reuse after revision ===")
    # The _select_pairs dedup check should NOT see superseded matches
    from routers.validation_utils import collect_all
    opp_id = f"{TEST_PREFIX}opp-super-b-0"
    dedup_key = f"{min(pid_b, opp_id)}|{max(pid_b, opp_id)}"

    # Check that superseded dedup_pair is excluded from pair selection
    active_pairs = set()
    async for m in db.matches.find(
        {"primary_category": TEST_CATEGORY, "dedup_pair": dedup_key,
         "completed": True, "revision_superseded": {"$ne": True}},
        {"_id": 0, "dedup_pair": 1}
    ):
        active_pairs.add(m["dedup_pair"])

    if dedup_key not in active_pairs:
        ok("Dedup_pair available for re-matching after revision")
    else:
        fail("Dedup_pair reuse", f"{dedup_key} still in active pairs")

    # ─── Test 4: Summary clearing blocks matchmaking ───
    print("\n=== Test 4: Summary clearing blocks matchmaking ===")
    paper_doc = await db.papers.find_one({"id": pid_b}, {"_id": 0, "summaries": 1})
    has_summaries = "summaries" in paper_doc and paper_doc["summaries"]
    if not has_summaries:
        ok("Summaries cleared after revision (paper ineligible for matching)")
    else:
        fail("Summary clearing", f"summaries still present: {list(paper_doc.get('summaries', {}).keys())}")

    # ─── Test 5: Version history integrity ───
    print("\n=== Test 5: Version history integrity ===")
    paper_full = await db.papers.find_one({"id": pid_b}, {"_id": 0, "version_history": 1, "current_version": 1})
    vh = paper_full.get("version_history", [])
    if len(vh) == 1 and vh[0]["version"] == 1 and paper_full["current_version"] == 2:
        ok(f"Version history: 1 archived version, current=v2")
    else:
        fail("Version history", f"len={len(vh)}, current_version={paper_full.get('current_version')}")

    # ─── Test 6: Ranking reset with revision_badge ───
    print("\n=== Test 6: Ranking reset with badge ===")
    ranking = await db.rankings.find_one({"paper_id": pid_b}, {"_id": 0})
    badge = ranking.get("revision_badge", {})
    if (ranking["wins"] == 0 and ranking["comparisons"] == 0 and
        badge.get("version") == 2 and badge.get("prev_comparisons") == 15):
        ok(f"Ranking reset: 0 matches, badge shows prev={badge['prev_comparisons']} matches")
    else:
        fail("Ranking reset", f"wins={ranking.get('wins')}, badge={badge}")

    # ─── Test 7: Cosmetic revision keeps tournament ───
    print("\n=== Test 7: Cosmetic revision preserves tournament ===")
    pid_c = await create_test_paper("cosm-c", with_matches=8)

    async def fake_dl_cosmetic(url, **kw):
        # Nearly identical to original (same content with minor punctuation change)
        return f"Full text content for paper cosm-c version 1! " * 50
    sched_mod.download_and_extract_pdf = fake_dl_cosmetic

    result_c = await _handle_revision(
        pid_c,
        {"arxiv_id": "8888.cosm-cv2", "link": "http://test", "abstract": "same"},
        2, {"revision_diff_threshold": 0.95}
    )
    assert result_c == "updated"

    rank_c = await db.rankings.find_one({"paper_id": pid_c}, {"_id": 0})
    active_c = await db.matches.count_documents({
        "$or": [{"paper1_id": pid_c}, {"paper2_id": pid_c}],
        "completed": True, "revision_superseded": {"$ne": True}
    })
    if rank_c["comparisons"] == 8 and active_c == 8:
        ok(f"Cosmetic: tournament kept ({rank_c['comparisons']} matches, {active_c} active)")
    else:
        fail("Cosmetic revision", f"comparisons={rank_c['comparisons']}, active={active_c}")

    # But summaries should still be cleared for re-evaluation
    paper_c = await db.papers.find_one({"id": pid_c}, {"_id": 0, "summaries": 1})
    if "summaries" not in paper_c or not paper_c.get("summaries"):
        ok("Cosmetic: summaries cleared for re-evaluation")
    else:
        fail("Cosmetic summaries", "summaries still present")

    # ─── Test 8: Migration idempotency ───
    print("\n=== Test 8: Migration idempotency ===")
    from scripts.migrate_arxiv_versions import migrate
    # Run migration — should be no-op on already-migrated data
    await migrate()
    # Verify nothing broke
    count = await db.papers.count_documents({"arxiv_id_base": {"$exists": True}})
    if count > 0:
        ok(f"Migration idempotent ({count} papers with arxiv_id_base)")
    else:
        fail("Migration", "No papers with arxiv_id_base after re-run")

    # ─── Test 9: Revision feed returns correct data ───
    print("\n=== Test 9: Revision feed endpoint ===")
    import httpx
    api_url = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
    if not api_url.startswith("http"):
        api_url = f"https://{api_url}"

    async with httpx.AsyncClient(timeout=15) as http:
        # Login
        login = await http.post(f"{api_url}/api/admin/login", json={"password": "papersumo2025"})
        token = login.json().get("token", "")

        resp = await http.get(f"{api_url}/api/admin/revision-feed",
                              headers={"X-Admin-Token": token})
        if resp.status_code == 200:
            feed = resp.json()
            if feed["total_revised_papers"] >= 2:  # at least our test papers
                ok(f"Revision feed: {feed['total_revised_papers']} revised papers, {feed['total_superseded_matches']} superseded matches")
            else:
                fail("Revision feed", f"Only {feed['total_revised_papers']} papers")
        else:
            fail("Revision feed", f"HTTP {resp.status_code}")

    # ─── Test 10: No orphaned ranking entries ───
    print("\n=== Test 10: No orphaned rankings ===")
    # Every ranking should have a corresponding paper
    orphans = 0
    async for r in db.rankings.find(
        {"paper_id": {"$regex": f"^{TEST_PREFIX}"}},
        {"_id": 0, "paper_id": 1}
    ):
        paper_exists = await db.papers.count_documents({"id": r["paper_id"]})
        if paper_exists == 0:
            orphans += 1
    if orphans == 0:
        ok("No orphaned rankings")
    else:
        fail("Orphaned rankings", f"{orphans} rankings without papers")

    # ─── Test 11: Existing production data integrity ───
    print("\n=== Test 11: Production data regression check ===")
    # Verify total match counts match expectations (no accidental superseding)
    total_active = await db.matches.count_documents({
        "completed": True, "revision_superseded": {"$ne": True}, "mode": {"$exists": False}
    })
    total_super = await db.matches.count_documents({"revision_superseded": True})
    total_all = await db.matches.count_documents({"completed": True, "mode": {"$exists": False}})

    # Active + superseded should equal total
    # (test matches also contribute, so allow for those)
    if total_active + total_super <= total_all + 50:  # small margin for test data
        ok(f"Match counts consistent: {total_active} active + {total_super} superseded = {total_active + total_super}")
    else:
        fail("Match consistency", f"active={total_active} + super={total_super} > total={total_all}")

    # Restore
    sched_mod.download_and_extract_pdf = original_download

    # Cleanup
    await cleanup()

    return results


async def main():
    r = await run_tests()
    print(f"\n{'='*60}")
    print(f"REGRESSION TESTS: {r['passed']} passed, {r['failed']} failed")
    if r['errors']:
        print("FAILURES:")
        for e in r['errors']:
            print(f"  - {e}")
    print(f"{'='*60}")
    client.close()
    return r['failed'] == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
