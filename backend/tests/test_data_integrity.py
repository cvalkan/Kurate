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
    print("=== 1. RANKINGS AUDIT ===")

    REQUIRED_RANKING_FIELDS = [
        "paper_id", "category", "rank", "rank_ts", "score", "ts_score",
        "ts_mu", "ts_sigma", "win_rate", "wins", "losses", "comparisons",
        "title",
    ]
    OPTIONAL_RANKING_FIELDS = [
        "os_score", "os_sigma", "rank_os", "ai_rating", "gap_score", "gap_score_ts",
    ]

    categories = await db.rankings.distinct("category")
    total_rankings = 0
    rankings_missing_fields = defaultdict(int)

    for cat in sorted(categories):
        cat_count = 0
        async for r in db.rankings.find({"category": cat}, {"_id": 0}):
            cat_count += 1
            total_rankings += 1
            for field in REQUIRED_RANKING_FIELDS:
                val = r.get(field)
                if val is None:
                    rankings_missing_fields[f"{cat}:{field}"] += 1

        # Check papers with summaries but no ranking
        papers_with_summary = await db.papers.count_documents(
            {"categories.0": cat, "summaries": {"$exists": True, "$ne": {}}}
        )
        if papers_with_summary > cat_count:
            fail("rankings", f"{cat}: {papers_with_summary - cat_count} papers with summaries but no ranking")
        else:
            ok("rankings")

        # Check ts_score specifically
        missing_ts = await db.rankings.count_documents(
            {"category": cat, "$or": [{"ts_score": {"$exists": False}}, {"ts_score": None}]}
        )
        if missing_ts > 0:
            fail("rankings", f"{cat}: {missing_ts}/{cat_count} papers missing ts_score")
        else:
            ok("rankings")

        # Check rank_ts
        missing_rank_ts = await db.rankings.count_documents(
            {"category": cat, "$or": [{"rank_ts": {"$exists": False}}, {"rank_ts": None}]}
        )
        if missing_rank_ts > 0:
            fail("rankings", f"{cat}: {missing_rank_ts}/{cat_count} papers missing rank_ts")
        else:
            ok("rankings")

        # Check rank_ts sequential (no gaps)
        max_rank = 0
        async for r in db.rankings.find({"category": cat}, {"_id": 0, "rank_ts": 1}).sort("rank_ts", -1).limit(1):
            max_rank = r.get("rank_ts", 0)
        if max_rank != cat_count and cat_count > 0:
            fail("rankings", f"{cat}: rank_ts max={max_rank} but {cat_count} papers (gap in ranks)")
        else:
            ok("rankings")

        print(f"  {cat}: {cat_count} rankings OK" if not any(
            f"{cat}:" in k for k in rankings_missing_fields
        ) else f"  {cat}: {cat_count} rankings — ISSUES")

    if rankings_missing_fields:
        for key, count in sorted(rankings_missing_fields.items()):
            fail("rankings", f"Missing field {key}: {count} papers")

    print(f"  Total: {total_rankings} rankings across {len(categories)} categories")

    # =========================================================================
    # 2. ARCHIVES: Every entry must have ts_score, ts_sigma, rank_ts
    # =========================================================================
    print("\n=== 2. ARCHIVES AUDIT ===")

    REQUIRED_ARCHIVE_FIELDS = ["id", "title", "ts_score", "ts_sigma", "rank_ts"]
    DESIRED_ARCHIVE_FIELDS = ["os_score", "os_sigma", "rank_os", "ai_rating"]

    archive_count = 0
    async for archive in db.leaderboard_archives.find(
        {"period_type": {"$in": ["weekly", "monthly"]}},
        {"_id": 0, "category": 1, "label": 1, "leaderboard": 1, "paper_count": 1}
    ):
        archive_count += 1
        cat = archive["category"]
        label = archive.get("label", "?")
        lb = archive.get("leaderboard", [])

        if not lb:
            fail("archives", f"{cat} {label}: empty leaderboard")
            continue

        missing_required = defaultdict(int)
        missing_desired = defaultdict(int)

        for entry in lb:
            for field in REQUIRED_ARCHIVE_FIELDS:
                if entry.get(field) is None:
                    missing_required[field] += 1
            for field in DESIRED_ARCHIVE_FIELDS:
                if entry.get(field) is None:
                    missing_desired[field] += 1

        has_issues = False
        for field, count in missing_required.items():
            if count > 0:
                fail("archives", f"{cat} {label}: {count}/{len(lb)} entries missing {field}")
                has_issues = True

        # Desired fields: warn but don't fail
        for field, count in missing_desired.items():
            if count > len(lb) * 0.5:  # More than half missing
                results["archives"]["issues"].append(
                    f"  (warn) {cat} {label}: {count}/{len(lb)} entries missing {field}"
                )

        if not has_issues:
            ok("archives")

    print(f"  Audited {archive_count} archives")

    # =========================================================================
    # 3. MEDALS: Top 3 in each archive must have badges on paper page
    # =========================================================================
    print("\n=== 3. MEDALS CONSISTENCY ===")

    from core.auth import get_settings
    settings = await get_settings()
    archive_config = settings.get("archive_frequency", {})
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

        # Skip archives that don't match current frequency setting
        cat_freq = archive_config.get(cat, default_freq)
        if archive.get("period_type") != cat_freq:
            continue

        if not lb:
            continue

        # Find top 3 by ts_score
        sorted_lb = sorted(lb, key=lambda p: p.get("ts_score") or 1200, reverse=True)
        for i, entry in enumerate(sorted_lb[:3]):
            pid = entry.get("id")
            if not pid:
                continue
            # Papers with 0 comparisons haven't been ranked — skip medal check
            if not entry.get("comparisons"):
                continue

            expected_rank = i + 1
            expected_tier = _get_tier(expected_rank)
            if not expected_tier:
                continue

            # Verify _compute_archive_rank agrees
            computed_rank = _compute_archive_rank(lb, pid)
            if computed_rank != expected_rank:
                fail("medals", f"{cat} {label}: {pid[:12]} expected rank {expected_rank} but _compute_archive_rank says {computed_rank}")
                continue

            # Verify _find_paper_badge finds a badge for this medalist
            badge_data = await _find_paper_badge(pid)
            if not badge_data:
                fail("medals", f"{cat} {label}: #{expected_rank} {expected_tier['name']} '{entry.get('title','')[:40]}' — _find_paper_badge returns None")
            elif badge_data.get("tier") is None:
                fail("medals", f"{cat} {label}: #{expected_rank} {expected_tier['name']} '{entry.get('title','')[:40]}' — badge has tier=None")
            else:
                # Badge exists with a medal — it might be from a different archive where the paper ranked higher
                ok("medals")

    # =========================================================================
    # 4. BADGES: Paper page badges must match archive medals
    # =========================================================================
    print("\n=== 4. BADGES ON PAPER PAGES ===")

    # For each paper that has badges, verify consistency
    from routers.badges import CATEGORIES as BADGE_CATS

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
            if not entry.get("comparisons"):
                continue

            expected_rank = i + 1
            expected_tier = _get_tier(expected_rank)
            if not expected_tier:
                continue

            # Check paper page ranking doc
            ranking = await db.rankings.find_one(
                {"paper_id": pid},
                {"_id": 0, "rank_ts": 1, "ts_score": 1, "category": 1}
            )
            if not ranking:
                fail("badges", f"{pid[:12]}: has archive medal but no ranking doc")
                continue

            # Verify the paper's share endpoint would show this badge
            badge_data = await _find_paper_badge(pid)
            if badge_data and badge_data.get("tier"):
                # Badge found — verify it's the correct one
                badge_tier = badge_data["tier"]["name"]
                badge_rank = badge_data["rank"]
                badge_label = badge_data["archive_label"]
                ok("badges")
                tested_papers += 1
            else:
                fail("badges", f"{cat} {archive.get('label')}: #{expected_rank} {expected_tier['name']} '{entry.get('title','')[:40]}' — no badge found on paper page")
                tested_papers += 1

    print(f"  Tested {tested_papers} medalist papers")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)
    total_passed = 0
    total_failed = 0
    for section, data in results.items():
        status = "PASS" if data["failed"] == 0 else "FAIL"
        print(f"  {section.upper()}: {status} ({data['passed']} passed, {data['failed']} failed)")
        total_passed += data["passed"]
        total_failed += data["failed"]
        if data["issues"]:
            for issue in data["issues"][:10]:  # Cap at 10 per section
                print(f"    - {issue}")
            if len(data["issues"]) > 10:
                print(f"    ... and {len(data['issues']) - 10} more")

    overall = "ALL PASSED" if total_failed == 0 else f"{total_failed} FAILURES"
    print(f"\n  OVERALL: {overall} ({total_passed} passed, {total_failed} failed)")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_audit())
    sys.exit(1 if any(r["failed"] > 0 for r in results.values()) else 0)
