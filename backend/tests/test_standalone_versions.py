"""End-to-end preview audit for the standalone-paper-per-version revision model.

Validates:
  * Multiple papers can share arxiv_id_base (unique constraint removed)
  * /api/papers/{id} returns sibling_versions for every version
  * Frozen papers (is_latest_version=false) are excluded from the leaderboard
  * Frozen papers remain accessible via direct URL with their frozen stats
  * Pair selection excludes frozen versions
  * _handle_revision creates a new paper doc rather than mutating in place
  * Legacy in-place revised papers continue to work (backward compat)
  * Migration script backfills is_latest_version correctly (dry-run only)
  * Admin revision-feed surfaces both standalone families and legacy entries
  * Indexes are correct (non-unique on arxiv_id_base, compound on rankings)

Each test logs PASS/FAIL. Tests are idempotent where possible.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from motor.motor_asyncio import AsyncIOMotorClient

MONGO = os.environ["MONGO_URL"]
DBN = os.environ["DB_NAME"]
API = os.environ.get("PREVIEW_URL") or "https://validation-hub-42.preview.emergentagent.com"
ADMIN_PW = os.environ["ADMIN_PASSWORD"]

passed, failed = 0, 0
BASE = "8888.77777"
V1_ID = "demo-multi-v1-abc"
V2_ID = "demo-multi-v2-abc"
V3_ID = "demo-multi-v3-abc"


def report(name, ok, detail=""):
    global passed, failed
    mark = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  [{mark}] {name}{(' — ' + detail) if detail else ''}")


async def get_admin_token(client):
    r = await client.post(f"{API}/api/admin/login", json={"password": ADMIN_PW})
    r.raise_for_status()
    return r.json()["token"]


async def test_1_index_non_unique(db):
    print("\n─── Test 1: arxiv_id_base index is non-unique ───")
    idxs = await db.papers.index_information()
    base_idx = idxs.get("arxiv_id_base_1")
    report("arxiv_id_base_1 exists", base_idx is not None)
    if base_idx:
        report("arxiv_id_base_1 is NOT unique", not base_idx.get("unique", False))
        report("arxiv_id_base_1 is sparse", base_idx.get("sparse", False))


async def test_2_three_siblings_exist(db):
    print("\n─── Test 2: 3 paper docs share arxiv_id_base ───")
    siblings = await db.papers.count_documents({"arxiv_id_base": BASE})
    report(f"3 standalone docs with same base {BASE}", siblings == 3, f"got {siblings}")

    # Distribution of is_latest_version
    latest = await db.papers.count_documents({"arxiv_id_base": BASE, "is_latest_version": True})
    frozen = await db.papers.count_documents({"arxiv_id_base": BASE, "is_latest_version": False})
    report(f"1 latest + 2 frozen (got {latest}/{frozen})", latest == 1 and frozen == 2)


async def test_3_paper_detail_returns_siblings():
    print("\n─── Test 3: Paper detail returns sibling_versions ───")
    async with httpx.AsyncClient(timeout=30) as c:
        for pid, expected_version in [(V1_ID, 1), (V2_ID, 2), (V3_ID, 3)]:
            r = await c.get(f"{API}/api/papers/{pid}")
            report(f"GET /api/papers/{pid} → 200", r.status_code == 200)
            if r.status_code != 200:
                continue
            d = r.json()
            paper = d.get("paper", {})
            sibs = paper.get("sibling_versions", [])
            report(f"{pid}: has 3 siblings", len(sibs) == 3, f"got {len(sibs)}")
            # Ordered ascending by version
            versions_seen = [s["version"] for s in sibs]
            report(f"{pid}: siblings sorted [1,2,3]", versions_seen == [1, 2, 3], str(versions_seen))
            # current_version correct
            report(f"{pid}: current_version == {expected_version}",
                   paper.get("current_version") == expected_version,
                   f"got {paper.get('current_version')}")


async def test_4_leaderboard_hides_frozen_versions():
    print("\n─── Test 4: Leaderboard only shows the latest version ───")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/leaderboard?cat=cs.RO&period=all&limit=500")
        report(f"leaderboard cs.RO → 200", r.status_code == 200)
        rows = r.json().get("leaderboard", [])
        v1_present = any(x.get("id") == V1_ID for x in rows)
        v2_present = any(x.get("id") == V2_ID for x in rows)
        v3_present = any(x.get("id") == V3_ID for x in rows)
        report("v1 NOT in leaderboard (frozen)", not v1_present)
        report("v2 NOT in leaderboard (frozen)", not v2_present)
        report("v3 IS in leaderboard (latest)", v3_present)
        # The v3 arxiv_id ends in 'v3' — verify the frontend can derive the badge version
        v3_row = next((r for r in rows if r.get("id") == V3_ID), None)
        if v3_row:
            aid = v3_row.get("arxiv_id", "")
            report(f"v3 arxiv_id ends with v3 ({aid})", aid.endswith("v3"))


async def test_5_frozen_papers_still_accessible_by_url():
    print("\n─── Test 5: Frozen v1/v2 pages load with their frozen stats ───")
    async with httpx.AsyncClient(timeout=30) as c:
        # v1 frozen: rank=42, score=1180, 26 comparisons
        r = await c.get(f"{API}/api/papers/{V1_ID}")
        report("v1 page → 200", r.status_code == 200)
        if r.status_code == 200:
            d = r.json()
            stats = d.get("stats", {})
            report(f"v1 shows 26 comparisons (stats frozen)", stats.get("comparisons") == 26)
            report(f"v1 shows 12 wins", stats.get("wins") == 12)
            report(f"v1 paper.ts_score == 1180", d["paper"].get("ts_score") == 1180)
        # v3 latest: rank=8, score=1389, 5 comparisons
        r = await c.get(f"{API}/api/papers/{V3_ID}")
        if r.status_code == 200:
            d = r.json()
            stats = d.get("stats", {})
            report("v3 shows 5 comparisons (live)", stats.get("comparisons") == 5)
            report("v3 shows 4 wins", stats.get("wins") == 4)
            report("v3 paper.ts_score == 1389", d["paper"].get("ts_score") == 1389)


async def test_6_matches_isolated_per_version():
    print("\n─── Test 6: Each version has its own distinct match list ───")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/{V1_ID}")
        m1 = r.json().get("matches", []) if r.status_code == 200 else []
        r = await c.get(f"{API}/api/papers/{V2_ID}")
        m2 = r.json().get("matches", []) if r.status_code == 200 else []
        r = await c.get(f"{API}/api/papers/{V3_ID}")
        m3 = r.json().get("matches", []) if r.status_code == 200 else []
        report(f"v1 has 6 matches (got {len(m1)})", len(m1) == 6)
        report(f"v2 has 4 matches (got {len(m2)})", len(m2) == 4)
        report(f"v3 has 3 matches (got {len(m3)})", len(m3) == 3)
        # No overlap between version match id sets
        s1 = {m["id"] for m in m1}
        s2 = {m["id"] for m in m2}
        s3 = {m["id"] for m in m3}
        report("match id sets are pairwise disjoint", len(s1 & s2) == 0 and len(s2 & s3) == 0 and len(s1 & s3) == 0)


async def test_7_get_matchable_paper_ids_excludes_frozen(db):
    print("\n─── Test 7: Pair selection excludes frozen versions ───")
    from services.scheduler import get_matchable_paper_ids
    matchable = await get_matchable_paper_ids("cs.RO", "thinking")
    report(f"v1 NOT matchable (frozen)", V1_ID not in matchable)
    report(f"v2 NOT matchable (frozen)", V2_ID not in matchable)
    report(f"v3 IS matchable (latest, has summaries)", V3_ID in matchable)


async def test_8_handle_revision_creates_new_doc(db):
    print("\n─── Test 8: _handle_revision creates a new paper doc ───")
    # Create a fake v1 paper, invoke _handle_revision, verify new doc created
    from services import scheduler as sched
    test_base = "7777.66666"
    test_pid_v1 = "test-handle-rev-v1"
    try:
        await db.papers.delete_many({"arxiv_id_base": test_base})
        await db.papers.delete_many({"id": test_pid_v1})
        await db.rankings.delete_many({"paper_id": test_pid_v1})
        now = datetime.now(timezone.utc)
        await db.papers.insert_one({
            "id": test_pid_v1,
            "arxiv_id": f"{test_base}v1",
            "arxiv_id_base": test_base,
            "current_version": 1,
            "is_latest_version": True,
            "title": "Handle-revision test",
            "authors": ["Test"],
            "abstract": "test",
            "full_text": "test full text",
            "categories": ["cs.RO"],
            "published": now.isoformat(),
            "link": f"https://arxiv.org/abs/{test_base}v1",
            "pdf_link": f"https://arxiv.org/pdf/{test_base}v1",
            "added_at": now.isoformat(),
            "summaries": {"anthropic:claude-opus-4-6:thinking": "old"},
        })
        await db.rankings.insert_one({
            "paper_id": test_pid_v1, "category": "cs.RO",
            "rank_ts": 10, "ts_score": 1200,
            "wins": 2, "losses": 1, "comparisons": 3,
            "is_latest_version": True,
        })

        # Monkeypatch PDF download
        orig = sched.download_and_extract_pdf
        sched.download_and_extract_pdf = lambda *a, **kw: asyncio.sleep(0, result="new full text v2 content")
        try:
            result = await sched._handle_revision(
                test_pid_v1,
                {"arxiv_id": f"{test_base}v2", "pdf_link": f"https://arxiv.org/pdf/{test_base}v2",
                 "abstract": "new abstract", "title": "Handle-revision test v2"},
                2, {}
            )
        finally:
            sched.download_and_extract_pdf = orig

        report("_handle_revision returned 'revised'", result == "revised")

        # Old paper: frozen
        old = await db.papers.find_one({"id": test_pid_v1}, {"_id": 0})
        report("old paper is_latest_version=False", old.get("is_latest_version") is False)
        report("old paper has frozen_at", old.get("frozen_at") is not None)
        report("old paper has superseded_by_paper_id", old.get("superseded_by_paper_id") is not None)

        # Old paper's summaries still intact (NOT wiped)
        report("old paper still has its summaries (preserved)",
               bool(old.get("summaries")) and "anthropic:claude-opus-4-6:thinking" in (old.get("summaries") or {}))

        # Old ranking frozen
        old_rank = await db.rankings.find_one({"paper_id": test_pid_v1}, {"_id": 0})
        report("old ranking stats untouched (wins=2)", old_rank.get("wins") == 2)
        report("old ranking is_latest_version=False", old_rank.get("is_latest_version") is False)

        # New paper exists
        new_paper = await db.papers.find_one(
            {"arxiv_id_base": test_base, "is_latest_version": True}, {"_id": 0}
        )
        report("new paper doc exists with same base", new_paper is not None)
        if new_paper:
            report("new paper version == 2", new_paper.get("current_version") == 2)
            report("new paper id != old paper id", new_paper.get("id") != test_pid_v1)
            report("new paper previous_version_paper_id links back",
                   new_paper.get("previous_version_paper_id") == test_pid_v1)
            report("new paper has full_text from download", bool(new_paper.get("full_text")))
            # New ranking exists and is fresh
            new_rank = await db.rankings.find_one({"paper_id": new_paper["id"]}, {"_id": 0})
            report("new ranking exists with 0 comparisons", new_rank and new_rank.get("comparisons") == 0)
    finally:
        # Cleanup test data
        await db.papers.delete_many({"arxiv_id_base": test_base})
        await db.rankings.delete_many({"paper_id": {"$in": [test_pid_v1]}})
        newp = await db.papers.find({"arxiv_id_base": test_base}, {"_id": 0, "id": 1}).to_list(10)
        for p in newp:
            await db.rankings.delete_many({"paper_id": p["id"]})


async def test_9_duplicate_arxiv_id_rejected(db):
    print("\n─── Test 9: Unique arxiv_id still prevents duplicates ───")
    # arxiv_id has a unique sparse index (each version is unique)
    idxs = await db.papers.index_information()
    # Find the index on arxiv_id
    arxiv_idxs = [(name, info) for name, info in idxs.items()
                  if any(k[0] == "arxiv_id" for k in info.get("key", []))]
    unique_present = any(info.get("unique") for name, info in arxiv_idxs)
    report("arxiv_id has a unique index", unique_present)


async def test_10_admin_revision_feed():
    print("\n─── Test 10: Admin revision feed surfaces the demo family ───")
    async with httpx.AsyncClient(timeout=30) as c:
        token = await get_admin_token(c)
        r = await c.get(f"{API}/api/admin/revision-feed", headers={"X-Admin-Token": token})
        report("revision-feed → 200", r.status_code == 200)
        d = r.json()
        report("has total_standalone_families", "total_standalone_families" in d)
        report("has total_legacy_in_place", "total_legacy_in_place" in d)
        report("has total_frozen_papers", "total_frozen_papers" in d)
        fams = d.get("families", [])
        demo = next((f for f in fams if f.get("arxiv_id_base") == BASE), None)
        report("demo family present in feed", demo is not None)
        if demo:
            report("demo family has 3 versions", len(demo.get("versions", [])) == 3)
            report("demo family latest_version == 3", demo.get("latest_version") == 3)


async def test_11_scheduler_still_starts(db):
    print("\n─── Test 11: Backend health after refactor ───")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/status")
        report("/api/status → 200", r.status_code == 200)
        d = r.json()
        report("/api/status has total_papers", "total_papers" in d)


async def test_12_frontend_build_contains_toggle():
    print("\n─── Test 12: Frontend build includes VersionToggle ───")
    import glob
    files = glob.glob("/app/frontend/build/static/js/main.*.js")
    if not files:
        report("frontend build exists", False)
        return
    with open(files[0]) as f:
        content = f.read()
    report("build contains 'version-toggle'", "version-toggle" in content)
    report("build contains 'version-badge-'", "version-badge-" in content)
    # Old components should be gone
    report("old 'revision-banner' removed", "revision-banner" not in content)
    report("old 'archived-matches' removed", "archived-matches" not in content)


async def test_13_migration_dry_run():
    print("\n─── Test 13: Migration script --dry-run ───")
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = "/app/backend"
    res = subprocess.run(
        ["python", "/app/backend/scripts/migrate_arxiv_versions.py", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    ok = res.returncode == 0 and "Step 4:" in res.stdout
    report("dry-run completes cleanly", ok, f"rc={res.returncode} stderr={res.stderr[:120]}")


async def test_14_legacy_revised_papers_still_work(db):
    print("\n─── Test 14: Legacy in-place revised papers still serve ───")
    legacy = await db.papers.find_one({"version_history": {"$exists": True, "$ne": []}},
                                       {"_id": 0, "id": 1})
    if not legacy:
        report("legacy paper exists for regression test", False, "none found")
        return
    pid = legacy["id"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/{pid}")
        report(f"legacy paper {pid[:10]} → 200", r.status_code == 200)
        if r.status_code == 200:
            d = r.json()
            # Legacy papers have only one standalone doc — no siblings
            report("legacy paper has no sibling_versions (single standalone doc)",
                   "sibling_versions" not in d.get("paper", {}))


async def test_15_race_no_summaries_preserved_on_revision(db):
    print("\n─── Test 15: Revision does NOT wipe old paper's summaries/rating ───")
    # This is a behavior change from the prior in-place model.
    # Create a paper, invoke revision, verify old doc still has its data.
    from services import scheduler as sched
    test_base = "7777.88888"
    test_pid = "test-preserve-summaries-v1"
    try:
        await db.papers.delete_many({"arxiv_id_base": test_base})
        await db.rankings.delete_many({"paper_id": test_pid})
        now = datetime.now(timezone.utc)
        await db.papers.insert_one({
            "id": test_pid,
            "arxiv_id": f"{test_base}v1",
            "arxiv_id_base": test_base,
            "current_version": 1,
            "is_latest_version": True,
            "title": "Preserve-summaries test",
            "authors": ["Test"],
            "abstract": "old abstract",
            "full_text": "old full text",
            "categories": ["cs.RO"],
            "link": f"https://arxiv.org/abs/{test_base}v1",
            "pdf_link": f"https://arxiv.org/pdf/{test_base}v1",
            "added_at": now.isoformat(),
            "summaries": {"anthropic:claude-opus-4-6:thinking": "OLD v1 summary content"},
            "ai_rating": 7.5,
        })

        orig = sched.download_and_extract_pdf
        sched.download_and_extract_pdf = lambda *a, **kw: asyncio.sleep(0, result="new v2 text")
        try:
            await sched._handle_revision(
                test_pid,
                {"arxiv_id": f"{test_base}v2", "pdf_link": f"https://arxiv.org/pdf/{test_base}v2",
                 "abstract": "new"},
                2, {}
            )
        finally:
            sched.download_and_extract_pdf = orig

        old = await db.papers.find_one({"id": test_pid}, {"_id": 0})
        sums = old.get("summaries") or {}
        rating = old.get("ai_rating")
        report("old paper summaries field preserved",
               "anthropic:claude-opus-4-6:thinking" in sums
               and sums["anthropic:claude-opus-4-6:thinking"] == "OLD v1 summary content")
        report("old paper ai_rating preserved", rating == 7.5)
        report("old paper abstract preserved (old, not overwritten)",
               old.get("abstract") == "old abstract")
    finally:
        await db.papers.delete_many({"arxiv_id_base": test_base})
        newp = await db.papers.find({"arxiv_id_base": test_base}, {"_id": 0, "id": 1}).to_list(10)
        for p in newp:
            await db.rankings.delete_many({"paper_id": p["id"]})


async def main():
    client = AsyncIOMotorClient(MONGO)
    db = client[DBN]
    try:
        await test_1_index_non_unique(db)
        await test_2_three_siblings_exist(db)
        await test_3_paper_detail_returns_siblings()
        await test_4_leaderboard_hides_frozen_versions()
        await test_5_frozen_papers_still_accessible_by_url()
        await test_6_matches_isolated_per_version()
        await test_7_get_matchable_paper_ids_excludes_frozen(db)
        await test_8_handle_revision_creates_new_doc(db)
        await test_9_duplicate_arxiv_id_rejected(db)
        await test_10_admin_revision_feed()
        await test_11_scheduler_still_starts(db)
        await test_12_frontend_build_contains_toggle()
        await test_13_migration_dry_run()
        await test_14_legacy_revised_papers_still_work(db)
        await test_15_race_no_summaries_preserved_on_revision(db)
    finally:
        client.close()
    print(f"\n{'='*60}\nSTANDALONE-VERSIONS AUDIT: {passed} passed, {failed} failed\n{'='*60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
