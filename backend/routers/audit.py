"""Archive consistency audit endpoint.
Runs server-side against the DB — no external HTTP calls, no production load."""

from fastapi import APIRouter, Depends
from core.config import db, CATEGORIES
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/audit", tags=["admin-audit"])


@router.get("/archives", dependencies=[Depends(verify_admin)])
async def audit_archives():
    """Full consistency audit of all archives. Runs server-side, no external calls."""

    results = {
        "cross_week_duplicates": {"status": "checking", "issues": []},
        "score_monotonicity": {"status": "checking", "issues": []},
        "badge_consistency": {"status": "checking", "issues": []},
        "stale_fields": {"status": "checking", "issues": []},
        "scoring_method": {"status": "checking", "issues": []},
    }

    # Load all archives (exclude leaderboard content for speed, load separately per check)
    all_archives = []
    async for doc in db.leaderboard_archives.find(
        {}, {"_id": 0, "category": 1, "period_type": 1, "year": 1, "week": 1, "month": 1,
             "label": 1, "paper_count": 1, "scoring_method": 1, "leaderboard": 1}
    ):
        all_archives.append(doc)

    # --- 1. Cross-week duplicates ---
    paper_appearances = {}  # (paper_id, category) -> [labels]
    for arc in all_archives:
        if arc.get("period_type") != "weekly":
            continue
        cat = arc["category"]
        for p in arc.get("leaderboard", []):
            pid = p.get("id")
            if pid:
                key = (pid, cat)
                paper_appearances.setdefault(key, []).append(arc.get("label", f"W{arc.get('week')}"))

    dupes = [(k, v) for k, v in paper_appearances.items() if len(v) > 1]
    if dupes:
        results["cross_week_duplicates"]["status"] = "FAIL"
        for (pid, cat), weeks in dupes[:10]:
            results["cross_week_duplicates"]["issues"].append(
                f"{pid[:12]}... [{cat}] appears in {weeks}")
    else:
        results["cross_week_duplicates"]["status"] = "PASS"
    results["cross_week_duplicates"]["checked"] = len(paper_appearances)

    # --- 2. Score monotonicity ---
    mono_fails = []
    for arc in all_archives:
        lb = arc.get("leaderboard", [])
        for i in range(len(lb) - 1):
            s1 = lb[i].get("score") or lb[i].get("ts_score") or 0
            s2 = lb[i + 1].get("score") or lb[i + 1].get("ts_score") or 0
            if s1 < s2:
                mono_fails.append(
                    f"{arc['category']} {arc.get('label','?')}: pos {i} score={s1} < pos {i+1} score={s2}")
    if mono_fails:
        results["score_monotonicity"]["status"] = "FAIL"
        results["score_monotonicity"]["issues"] = mono_fails[:10]
    else:
        results["score_monotonicity"]["status"] = "PASS"
    results["score_monotonicity"]["checked"] = len(all_archives)

    # --- 3. Badge consistency (server-side, no HTTP calls) ---
    from routers.badges import _get_tier
    badge_issues = []
    for arc in all_archives:
        lb = arc.get("leaderboard", [])
        year = arc.get("year")
        if not year:
            continue
        for i, p in enumerate(lb[:3]):
            expected_rank = i + 1
            expected_tier = _get_tier(expected_rank)
            if not expected_tier:
                continue
            score = p.get("score") or p.get("ts_score") or 0
            if score == 0:
                badge_issues.append(
                    f"{arc['category']} {arc.get('label','?')} pos {i}: score=0 (badge would render empty)")
            comparisons = p.get("comparisons") or 0
            if comparisons < 5:
                badge_issues.append(
                    f"{arc['category']} {arc.get('label','?')} pos {i}: only {comparisons} matches (badge may be unreliable)")
    if badge_issues:
        results["badge_consistency"]["status"] = "WARN"
        results["badge_consistency"]["issues"] = badge_issues[:10]
    else:
        results["badge_consistency"]["status"] = "PASS"
    results["badge_consistency"]["checked"] = sum(min(len(a.get("leaderboard", [])), 3) for a in all_archives)

    # --- 4. Stale fields ---
    stale_archives = []
    for arc in all_archives:
        lb = arc.get("leaderboard", [])
        if lb and "rank" in lb[0]:
            stale_archives.append(f"{arc['category']} {arc.get('label','?')}: has 'rank' field")
        if lb and "ranking_score" in lb[0]:
            stale_archives.append(f"{arc['category']} {arc.get('label','?')}: has 'ranking_score' field")
    if stale_archives:
        results["stale_fields"]["status"] = "WARN"
        results["stale_fields"]["issues"] = stale_archives[:10]
    else:
        results["stale_fields"]["status"] = "PASS"
    results["stale_fields"]["checked"] = len(all_archives)

    # --- 5. Scoring method metadata ---
    missing_method = []
    for arc in all_archives:
        if not arc.get("scoring_method"):
            missing_method.append(f"{arc['category']} {arc.get('label','?')}: no scoring_method")
    if missing_method:
        results["scoring_method"]["status"] = "WARN"
        results["scoring_method"]["issues"] = missing_method[:10]
    else:
        results["scoring_method"]["status"] = "PASS"
    results["scoring_method"]["checked"] = len(all_archives)

    # --- Summary ---
    all_pass = all(r["status"] in ("PASS",) for r in results.values())
    has_fail = any(r["status"] == "FAIL" for r in results.values())

    return {
        "overall": "PASS" if all_pass else "FAIL" if has_fail else "WARN",
        "total_archives": len(all_archives),
        "results": results,
    }
