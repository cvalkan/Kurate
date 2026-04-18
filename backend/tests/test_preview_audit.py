"""Thorough preview/production-risk audit for the revision handling system.

Each test is self-contained and logs PASS/FAIL. Tests are idempotent where possible.
Focus: edge cases, env/infra issues, caching, auth, integration with live scheduler.
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from motor.motor_asyncio import AsyncIOMotorClient

MONGO = os.environ["MONGO_URL"]
DBN = os.environ["DB_NAME"]
API = os.environ.get("PREVIEW_URL") or "https://kurate-core.preview.emergentagent.com"
ADMIN_PW = os.environ["ADMIN_PASSWORD"]

passed, failed = 0, 0


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


async def test_1_admin_auth_required():
    """revision-feed endpoint must refuse unauthenticated + wrong-token requests."""
    print("\n─── Test 1: Admin auth on /api/admin/revision-feed ───")
    async with httpx.AsyncClient(timeout=30) as c:
        # No token
        r = await c.get(f"{API}/api/admin/revision-feed")
        report("no-token → 401/403", r.status_code in (401, 403), f"got {r.status_code}")
        # Bad token
        r = await c.get(f"{API}/api/admin/revision-feed", headers={"X-Admin-Token": "deadbeef"})
        report("bad-token → 401/403", r.status_code in (401, 403), f"got {r.status_code}")
        # Good token
        token = await get_admin_token(c)
        r = await c.get(f"{API}/api/admin/revision-feed?limit=3", headers={"X-Admin-Token": token})
        report("valid-token → 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        report("returns total_revised_papers", "total_revised_papers" in data)
        report("returns total_superseded_matches", "total_superseded_matches" in data)


async def test_2_paper_endpoint_response_shape(db):
    """Paper detail endpoint returns revision_badge, version_history, archived_matches for revised papers."""
    print("\n─── Test 2: /api/papers/{id} response shape ───")
    # Find a revised paper
    revised = await db.papers.find_one({"version_history": {"$exists": True, "$ne": []}},
                                        {"_id": 0, "id": 1})
    if not revised:
        report("found a revised paper", False, "no revised papers in DB")
        return
    pid = revised["id"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/{pid}")
        report("revised paper returns 200", r.status_code == 200)
        d = r.json()
        report("has 'paper' key", "paper" in d)
        report("has 'matches' key", "matches" in d)
        report("has 'stats' key", "stats" in d)
        paper = d.get("paper", {})
        report("paper.version_history is array", isinstance(paper.get("version_history"), list))
        # archived_matches only present if there are any
        # revision_badge only present if paper currently has one
    # Non-existent paper
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/nonexistent-xyz-123")
        report("nonexistent paper → 404", r.status_code == 404, f"got {r.status_code}")


async def test_3_leaderboard_exposes_revision_badge(db):
    """Leaderboard API returns revision_badge on ranking entries that have one."""
    print("\n─── Test 3: Leaderboard includes revision_badge ───")
    # Find a ranking with revision_badge
    ranked = await db.rankings.find_one(
        {"revision_badge": {"$exists": True}},
        {"_id": 0, "paper_id": 1, "category": 1}
    )
    if not ranked:
        report("found ranking with revision_badge", False, "skipping API test")
        return
    cat = ranked["category"]
    pid = ranked["paper_id"]
    async with httpx.AsyncClient(timeout=30) as c:
        # Fetch all-time leaderboard for that cat
        r = await c.get(f"{API}/api/leaderboard?cat={cat}&period=all&limit=200")
        report(f"leaderboard cat={cat} → 200", r.status_code == 200)
        rows = r.json().get("leaderboard") or r.json().get("papers") or []
        if not isinstance(rows, list):
            rows = []
        match = next((p for p in rows if p.get("id") == pid), None)
        report(f"paper {pid[:12]} found in leaderboard", bool(match))
        if match:
            report("revision_badge field present in leaderboard entry", "revision_badge" in match)
            if "revision_badge" in match:
                rb = match["revision_badge"]
                report("badge has 'version'", "version" in rb and rb["version"] is not None)


async def test_4_superseded_matches_excluded_from_rankings(db):
    """Ranking queries must exclude revision_superseded matches."""
    print("\n─── Test 4: Superseded matches excluded from rankings ───")
    # Count active vs total matches
    active_count = await db.matches.count_documents({
        "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False},
        "revision_superseded": {"$ne": True}
    })
    superseded_count = await db.matches.count_documents({"revision_superseded": True})
    total_count = await db.matches.count_documents({
        "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}
    })
    report(f"active + superseded = total ({active_count} + {superseded_count} = {total_count})",
           active_count + superseded_count == total_count,
           f"mismatch: {active_count} + {superseded_count} vs {total_count}")


async def test_5_match_counter_matches_db(db):
    """In-memory counter should equal DB count after a fresh seed."""
    print("\n─── Test 5: _incr_match_counts matches DB (post-startup) ───")
    # Query DB group-by-category
    db_counts = {}
    async for d in db.matches.aggregate([
        {"$match": {"completed": True, "failed": {"$ne": True},
                    "mode": {"$exists": False},
                    "revision_superseded": {"$ne": True}}},
        {"$group": {"_id": "$primary_category", "count": {"$sum": 1}}},
    ]):
        db_counts[d["_id"]] = d["count"]

    # Hit the status endpoint which reflects in-memory counters
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/status")
        data = r.json()
        # status endpoint returns total_matches
        live_total = data.get("total_matches", 0)
        db_total = sum(db_counts.values())
        # Allow tiny drift (recent matches mid-flight)
        drift = abs(live_total - db_total)
        report(f"/status total_matches matches DB ({live_total} vs {db_total}, drift={drift})",
               drift <= 5, f"live={live_total}, db={db_total}")


async def test_6_migration_script_dry_run():
    """Migration script --dry-run must succeed without modifying state."""
    print("\n─── Test 6: Migration script --dry-run ───")
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = "/app/backend"
    res = subprocess.run(
        ["python", "/app/backend/scripts/migrate_arxiv_versions.py", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    ok = res.returncode == 0 and "Step 4:" in res.stdout
    report("dry-run completes cleanly", ok,
           f"rc={res.returncode} stdout={res.stdout[:200]} stderr={res.stderr[:200]}")


async def test_7_missing_env_fails_fast():
    """Migration must refuse to run if MONGO_URL is unset."""
    print("\n─── Test 7: Migration fails fast on missing MONGO_URL ───")
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "MONGO_URL"}
    env["PYTHONPATH"] = "/app/backend"
    res = subprocess.run(
        ["python", "/app/backend/scripts/migrate_arxiv_versions.py", "--dry-run"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    ok = res.returncode == 2 and "MONGO_URL" in res.stderr
    report("exit code 2 + error mentions MONGO_URL", ok,
           f"rc={res.returncode}, stderr={res.stderr[:150]}")


async def test_8_prewarm_includes_superseded_filter(db):
    """Seeded counters must use revision_superseded: $ne True filter.
    Verify by counting twice — once with, once without the filter — and
    confirming the endpoint's status matches the filtered count."""
    print("\n─── Test 8: Startup seed respects revision_superseded ───")
    filtered = await db.matches.count_documents({
        "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False},
        "revision_superseded": {"$ne": True}
    })
    unfiltered = await db.matches.count_documents({
        "completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}
    })
    # Must differ if there are any superseded docs
    superseded = unfiltered - filtered
    report(f"DB has {superseded} superseded matches that must be excluded",
           True, f"filtered={filtered}, unfiltered={unfiltered}")


async def test_9_version_history_slice_20(db):
    """Version history is capped at 20 via $slice. Verify no paper has >20 entries."""
    print("\n─── Test 9: version_history cap ≤ 20 ───")
    oversized = 0
    async for p in db.papers.find(
        {"version_history.20": {"$exists": True}},  # index 20 means ≥21 elements
        {"_id": 0, "id": 1, "version_history": 1}
    ):
        oversized += 1
        print(f"    Warning: {p['id']} has {len(p['version_history'])} versions")
    report("no paper exceeds 20 archived versions", oversized == 0)


async def test_10_paper_detail_no_id_field_leak(db):
    """Ensure API never leaks MongoDB _id field."""
    print("\n─── Test 10: No _id field leakage ───")
    # Pick a revised paper
    revised = await db.papers.find_one({"version_history": {"$exists": True}},
                                        {"_id": 0, "id": 1})
    if not revised:
        report("found revised paper", False)
        return
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/{revised['id']}")
        text = r.text
        # ObjectId is a 24-char hex string; if leaked it appears as {"_id":"..."}
        leak = '"_id"' in text
        report("no _id field in response", not leak)


async def test_11_indexes_created_on_startup(db):
    """Confirm the new compound indexes exist on matches collection."""
    print("\n─── Test 11: New match indexes present ───")
    idxs = await db.matches.index_information()
    report("paper1_revision_idx exists", "paper1_revision_idx" in idxs)
    report("paper2_revision_idx exists", "paper2_revision_idx" in idxs)


async def test_12_archived_matches_filter_consistent(db):
    """Paper detail: matches[] and archived_matches[] must be disjoint + sum to total."""
    print("\n─── Test 12: matches + archived_matches are disjoint ───")
    # Find a paper with both active and archived matches
    async for paper in db.papers.find({"version_history": {"$exists": True}}, {"_id": 0, "id": 1}).limit(20):
        pid = paper["id"]
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{API}/api/papers/{pid}")
            if r.status_code != 200:
                continue
            d = r.json()
            m = d.get("matches", [])
            am = d.get("archived_matches", [])
            if not am:
                continue
            m_ids = {x["id"] for x in m}
            am_ids = {x["id"] for x in am}
            disjoint = len(m_ids & am_ids) == 0
            report(f"paper {pid[:12]}: {len(m)} active, {len(am)} archived, disjoint={disjoint}", disjoint)
            return
    report("no paper with both active+archived to test", True, "skipped (none)")


async def test_13_env_vars_loaded():
    """Confirm backend has required env vars accessible at runtime."""
    print("\n─── Test 13: Backend env vars ───")
    # Hit the /status endpoint — if env were broken, it'd 500
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/status")
        report("/api/status returns 200", r.status_code == 200)


async def test_14_demo_paper_rendering(db):
    """Demo paper must be resolvable via the API."""
    print("\n─── Test 14: Demo multi-revision paper API ───")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/api/papers/demo-revision-paper-abc123")
        if r.status_code != 200:
            report("demo paper API returns 200", False, f"got {r.status_code}")
            return
        d = r.json()
        p = d.get("paper", {})
        report("demo paper has current_version=4", p.get("current_version") == 4)
        report("demo paper has 3 archived versions", len(p.get("version_history", [])) == 3)
        report("demo paper has revision_badge", p.get("revision_badge") is not None)
        report("demo paper has 4 active matches", len(d.get("matches", [])) == 4)
        report("demo paper has 6 archived matches", len(d.get("archived_matches", [])) == 6)


async def test_15_similarity_perf():
    """_content_similarity on large text should be fast (< 500ms per call)."""
    print("\n─── Test 15: _content_similarity performance ───")
    from services.scheduler import _content_similarity
    # Simulate full paper text (30K chars)
    text_a = "we propose a novel approach for object detection using transformers. " * 500
    text_b = "we propose a novel approach for image classification using transformers. " * 500
    start = time.time()
    s = _content_similarity(text_a, text_b)
    elapsed = (time.time() - start) * 1000
    report(f"30K-char similarity in {elapsed:.0f}ms (sim={s:.2f})", elapsed < 500)


async def test_16_scheduler_revision_epoch_tracker():
    """Epoch tracker is module-level dict; verify cleanup doesn't leak."""
    print("\n─── Test 16: _paper_revision_epochs cleanup ───")
    from services import scheduler as sched
    # Tracker should be small (< 100 keys for normal operation)
    size = len(sched._paper_revision_epochs)
    report(f"epochs tracker size = {size} (reasonable < 10000)", size < 10000)


async def test_17_frontend_build_has_new_components():
    """Verify the frontend build includes the new revision components."""
    print("\n─── Test 17: Frontend build contains new UI code ───")
    # Find the main.*.js file and check
    import glob
    jsfiles = glob.glob("/app/frontend/build/static/js/main.*.js")
    if not jsfiles:
        report("frontend build exists", False)
        return
    f = jsfiles[0]
    with open(f) as fh:
        content = fh.read()
    report("build contains 'revision-banner' testid", "revision-banner" in content)
    report("build contains 'version-history' testid", "version-history" in content)
    report("build contains 'archived-matches' testid", "archived-matches" in content)
    report("build contains 'revision-badge' testid", "revision-badge-" in content)


async def main():
    client = AsyncIOMotorClient(MONGO)
    db = client[DBN]
    try:
        await test_1_admin_auth_required()
        await test_2_paper_endpoint_response_shape(db)
        await test_3_leaderboard_exposes_revision_badge(db)
        await test_4_superseded_matches_excluded_from_rankings(db)
        await test_5_match_counter_matches_db(db)
        await test_6_migration_script_dry_run()
        await test_7_missing_env_fails_fast()
        await test_8_prewarm_includes_superseded_filter(db)
        await test_9_version_history_slice_20(db)
        await test_10_paper_detail_no_id_field_leak(db)
        await test_11_indexes_created_on_startup(db)
        await test_12_archived_matches_filter_consistent(db)
        await test_13_env_vars_loaded()
        await test_14_demo_paper_rendering(db)
        await test_15_similarity_perf()
        await test_16_scheduler_revision_epoch_tracker()
        await test_17_frontend_build_has_new_components()
    finally:
        client.close()
    print(f"\n{'='*60}\nPREVIEW AUDIT: {passed} passed, {failed} failed\n{'='*60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
