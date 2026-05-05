"""
Comprehensive data integrity audit for Kurate.org.
Tests all rankings, archives, badges, and medals for consistency.

Run: cd /app/backend && python3 tests/test_data_integrity.py
Or via admin endpoint: POST /api/admin/run-audit
"""
import asyncio
import sys
sys.path.insert(0, "/app/backend")

from collections import defaultdict


async def run_audit(production_url: str = None):
    """Run full data integrity audit. Returns dict with results."""
    from core.config import db

    results = {
        "rankings": {"passed": 0, "failed": 0, "issues": []},
        "archives": {"passed": 0, "failed": 0, "issues": []},
        "medals": {"passed": 0, "failed": 0, "issues": []},
        "badges": {"passed": 0, "failed": 0, "issues": []},
    }

    def fail(section, msg):
        results[section]["failed"] += 1
        results[section]["issues"].append(msg)

    def ok(section):
        results[section]["passed"] += 1

    # =========================================================================
    # 1. RANKINGS: Every paper must have all required fields
    # =========================================================================
    REQUIRED_FIELDS = {
        "paper_id": "all", "category": "all", "title": "all",
        "rank": "all", "rank_ts": "all",
        "score": "all", "ts_score": "all", "ts_mu": "all", "ts_sigma": "all",
        "win_rate": "all", "wins": "all", "losses": "all", "comparisons": "all",
    }
    # Fields required only for papers with matches
    MATCH_REQUIRED = {
        "os_score": "with_matches", "os_mu": "with_matches",
        "os_sigma": "with_matches", "rank_os": "with_matches",
    }
    # Desired but not strictly required
    DESIRED_FIELDS = ["ai_rating", "gap_score"]

    categories = await db.rankings.distinct("category")
    total_rankings = 0
    total_missing_rating = 0
    total_missing_gap = 0

    for cat in sorted(categories):
        cat_count = 0
        cat_missing = defaultdict(int)

        async for r in db.rankings.find({"category": cat}, {"_id": 0}):
            cat_count += 1
            total_rankings += 1
            has_matches = (r.get("comparisons") or 0) > 0

            # Check required fields
            for field in REQUIRED_FIELDS:
                if r.get(field) is None:
                    cat_missing[field] += 1

            # Check match-required fields
            if has_matches:
                for field in MATCH_REQUIRED:
                    if r.get(field) is None:
                        cat_missing[f"{field}(matched)"] += 1

            # Track desired fields
            if not r.get("ai_rating"):
                total_missing_rating += 1
            if r.get("gap_score") is None:
                total_missing_gap += 1

        # Report per-category
        for field, count in cat_missing.items():
            fail("rankings", f"{cat}: {count}/{cat_count} missing {field}")

        # Check papers with summaries but no ranking
        papers_with_summary = await db.papers.count_documents(
            {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}}
        )
        if papers_with_summary > cat_count:
            fail("rankings", f"{cat}: {papers_with_summary - cat_count} papers with summaries but no ranking")

        # Check rank_ts sequential
        max_rank = 0
        async for r in db.rankings.find({"category": cat}, {"_id": 0, "rank_ts": 1}).sort("rank_ts", -1).limit(1):
            max_rank = r.get("rank_ts", 0)
        if max_rank != cat_count and cat_count > 0:
            fail("rankings", f"{cat}: rank_ts max={max_rank} but {cat_count} papers (gap in ranks)")

        if not cat_missing:
            ok("rankings")

    # Report desired field totals
    if total_missing_rating > 0:
        results["rankings"]["issues"].append(f"  (info) {total_missing_rating} papers missing ai_rating across all categories")
    if total_missing_gap > 0:
        results["rankings"]["issues"].append(f"  (info) {total_missing_gap} papers missing gap_score across all categories")

    # =========================================================================
    # 2. ARCHIVES: Every entry must have consistent data
    # =========================================================================
    REQUIRED_ARCHIVE = ["id", "title", "ts_score", "ts_sigma", "rank_ts",
                        "os_score", "os_sigma", "rank_os",
                        "score", "wins", "losses", "comparisons", "win_rate"]

    archive_count = 0
    total_wrong_1200 = 0

    async for archive in db.leaderboard_archives.find(
        {"period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "label": 1, "leaderboard": 1}
    ):
        archive_count += 1
        cat = archive["category"]
        label = archive.get("label", "?")
        lb = archive.get("leaderboard", [])
        if not lb:
            fail("archives", f"{cat} {label}: empty leaderboard")
            continue

        missing = defaultdict(int)
        wrong_1200 = 0

        for entry in lb:
            for field in REQUIRED_ARCHIVE:
                if entry.get(field) is None:
                    missing[field] += 1

            # Papers with comparisons but ts_score=1200 (wrong default)
            if (entry.get("comparisons") or 0) > 0 and entry.get("ts_score") == 1200:
                wrong_1200 += 1

        has_issues = False
        for field, count in missing.items():
            if count > 0:
                fail("archives", f"{cat} {label}: {count}/{len(lb)} missing {field}")
                has_issues = True

        if wrong_1200 > 0:
            fail("archives", f"{cat} {label}: {wrong_1200}/{len(lb)} papers have ts_score=1200 despite having matches")
            total_wrong_1200 += wrong_1200
            has_issues = True

        if not has_issues:
            ok("archives")

    if total_wrong_1200 > 0:
        results["archives"]["issues"].append(f"  TOTAL: {total_wrong_1200} archive entries need backfill (ts_score=1200 with matches)")

    # =========================================================================
    # 3. MEDALS: Top 3 in each archive must have badges on paper page
    # =========================================================================
    from core.auth import get_settings
    settings = await get_settings()
    archive_config = settings.get("archive_frequency") or {}
    default_freq = archive_config.get("default", "weekly")
    from routers.badges import _compute_archive_rank, _get_tier, _find_paper_badge

    async for archive in db.leaderboard_archives.find(
        {"period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
         "period_type": 1, "label": 1, "leaderboard": 1}
    ).sort([("year", -1), ("week", -1), ("month", -1)]):
        cat = archive["category"]
        label = archive.get("label", "?")
        lb = archive.get("leaderboard", [])

        cat_freq = archive_config.get(cat, default_freq)
        if archive.get("period_type") != cat_freq:
            continue
        if not lb:
            continue

        sorted_lb = sorted(lb, key=lambda p: p.get("ts_score") or 1200, reverse=True)
        for i, entry in enumerate(sorted_lb[:3]):
            pid = entry.get("id")
            if not pid:
                continue
            # Skip papers below minimum match threshold — they don't get medals
            if (entry.get("comparisons") or 0) < 9:
                continue

            expected_rank = i + 1
            expected_tier = _get_tier(expected_rank)
            if not expected_tier:
                continue

            computed_rank = _compute_archive_rank(lb, pid)
            if computed_rank != expected_rank:
                fail("medals", f"{cat} {label}: {pid[:12]} expected rank {expected_rank} but _compute_archive_rank says {computed_rank}")
                continue

            badge_data = await _find_paper_badge(pid)
            if not badge_data:
                fail("medals", f"{cat} {label}: #{expected_rank} {expected_tier['name']} '{entry.get('title','')[:40]}' — no badge found")
            elif badge_data.get("tier") is None:
                fail("medals", f"{cat} {label}: #{expected_rank} {expected_tier['name']} '{entry.get('title','')[:40]}' — badge has tier=None")
            else:
                ok("medals")

    # =========================================================================
    # 4. BADGES: Paper page badges must match archive medals
    # =========================================================================
    tested_papers = 0
    async for archive in db.leaderboard_archives.find(
        {"period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "year": 1, "week": 1, "month": 1,
         "period_type": 1, "label": 1, "leaderboard": 1}
    ).sort([("year", -1), ("week", -1), ("month", -1)]):
        cat = archive["category"]
        cat_freq = archive_config.get(cat, default_freq)
        if archive.get("period_type") != cat_freq:
            continue
        lb = archive.get("leaderboard", [])
        if not lb:
            continue

        sorted_lb = sorted(lb, key=lambda p: p.get("ts_score") or 1200, reverse=True)
        for i, entry in enumerate(sorted_lb[:3]):
            pid = entry.get("id")
            if not pid:
                continue
            if (entry.get("comparisons") or 0) < 9:
                continue

            expected_tier = _get_tier(i + 1)
            if not expected_tier:
                continue

            ranking = await db.rankings.find_one(
                {"paper_id": pid}, {"_id": 0, "rank_ts": 1, "ts_score": 1}
            )
            if not ranking:
                fail("badges", f"{pid[:12]}: archive medal but no ranking doc")
                continue

            badge_data = await _find_paper_badge(pid)
            if badge_data and badge_data.get("tier"):
                ok("badges")
            else:
                fail("badges", f"{cat} {archive.get('label')}: #{i+1} {expected_tier['name']} '{entry.get('title','')[:40]}' — no badge on paper page")
            tested_papers += 1

    # =========================================================================
    # SUMMARY
    # =========================================================================
    total_passed = sum(r["passed"] for r in results.values())
    total_failed = sum(r["failed"] for r in results.values())
    for section, data in results.items():
        status = "PASS" if data["failed"] == 0 else "FAIL"

    return results


if __name__ == "__main__":
    async def main():
        results = await run_audit()
        total_passed = sum(r["passed"] for r in results.values())
        total_failed = sum(r["failed"] for r in results.values())
        print("\n" + "=" * 60)
        print("AUDIT SUMMARY")
        print("=" * 60)
        for section, data in results.items():
            status = "PASS" if data["failed"] == 0 else "FAIL"
            print(f"  {section.upper()}: {status} ({data['passed']} passed, {data['failed']} failed)")
            for issue in data["issues"][:10]:
                print(f"    - {issue}")
            if len(data["issues"]) > 10:
                print(f"    ... and {len(data['issues']) - 10} more")
        print(f"\n  OVERALL: {'ALL PASSED' if total_failed == 0 else f'{total_failed} FAILURES'} ({total_passed} passed, {total_failed} failed)")
        sys.exit(1 if total_failed > 0 else 0)
    asyncio.run(main())
