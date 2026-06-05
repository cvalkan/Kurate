"""Migration: Fix papers ingested with wrong OAI-PMH dates.

Two populations:
1. OLD papers (created before 2025) that should never have been ingested
   → These are metadata-only updates (category reclassification, etc.)
   → Action: DELETE from papers + rankings + matches

2. RECENT papers with wrong published date (OAI-PMH used 'updated' instead of 'created')
   → Action: Fix published date using the arxiv_id prefix (YYMM → created month)
   → Then batch-verify against OAI-PMH for exact created dates

Usage:
  DRY_RUN=1 python -m scripts.fix_oai_dates   # Preview what would change
  python -m scripts.fix_oai_dates              # Apply fixes

Run from /app/backend directory.
"""
import asyncio
import os
import re
import sys

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"


async def main():
    from core.config import db, logger

    print(f"{'DRY RUN' if DRY_RUN else 'LIVE RUN'} — Fix OAI-PMH date issues")
    print("=" * 60)

    # Step 1: Find all OAI-PMH papers (short published date, no version suffix)
    oai_papers = []
    async for doc in db.papers.find(
        {"arxiv_id": {"$exists": True}},
        {"_id": 0, "id": 1, "arxiv_id": 1, "published": 1, "added_at": 1,
         "title": 1, "categories": 1, "current_version": 1},
    ):
        pub = str(doc.get("published", ""))
        arxiv_id = doc.get("arxiv_id", "")

        # OAI papers: short date (YYYY-MM-DD, ≤10 chars) AND no version suffix
        is_oai = len(pub) <= 10 and pub and "v" not in arxiv_id
        if is_oai:
            oai_papers.append(doc)

    print(f"Found {len(oai_papers)} OAI-PMH papers (short date, no version suffix)")

    # Step 2: Classify each paper
    to_delete = []   # Old papers that shouldn't be in DB
    to_fix = []      # Recent papers with wrong date
    ok = []          # Papers with correct dates

    for doc in oai_papers:
        arxiv_id = doc["arxiv_id"]
        pub = doc["published"]

        # Extract year/month from arxiv_id prefix (YYMM.NNNNN)
        prefix_match = re.match(r'^(\d{2})(\d{2})\.', arxiv_id)
        if not prefix_match:
            continue

        yy, mm = int(prefix_match.group(1)), int(prefix_match.group(2))
        arxiv_year = 2000 + yy if yy < 50 else 1900 + yy
        arxiv_month = mm

        # Parse published date
        pub_year = int(pub[:4]) if len(pub) >= 4 else 0
        pub_month = int(pub[5:7]) if len(pub) >= 7 else 0

        if arxiv_year < 2025:
            # Paper created before 2025 — shouldn't be in a 2026 dataset
            to_delete.append({
                **doc,
                "reason": f"old_paper (created ~{arxiv_year}-{arxiv_month:02d})",
            })
        elif arxiv_year != pub_year or abs(arxiv_month - pub_month) > 1:
            # Published date doesn't match creation month (off by >1 month)
            correct_date = f"{arxiv_year}-{arxiv_month:02d}-01"
            to_fix.append({
                **doc,
                "correct_date_approx": correct_date,
                "reason": f"wrong_date (pub={pub}, should be ~{arxiv_year}-{arxiv_month:02d})",
            })
        else:
            ok.append(doc)

    print(f"\nClassification:")
    print(f"  OK (correct dates):     {len(ok)}")
    print(f"  WRONG DATE (fixable):   {len(to_fix)}")
    print(f"  OLD PAPER (to delete):  {len(to_delete)}")

    # Step 3: Show what would be deleted
    if to_delete:
        print(f"\n--- Papers to DELETE ({len(to_delete)}) ---")
        for p in to_delete[:20]:
            print(f"  {p['arxiv_id']:20s} pub={p['published']:12s} | {p['reason']} | {p.get('title', '')[:50]}")
        if len(to_delete) > 20:
            print(f"  ... and {len(to_delete) - 20} more")

    # Step 4: Show what would be fixed
    if to_fix:
        print(f"\n--- Papers to FIX date ({len(to_fix)}) ---")
        for p in to_fix[:20]:
            print(f"  {p['arxiv_id']:20s} pub={p['published']:12s} → ~{p['correct_date_approx']} | {p.get('title', '')[:50]}")
        if len(to_fix) > 20:
            print(f"  ... and {len(to_fix) - 20} more")

    # Step 5: For papers to fix, get exact created date from REST API
    # (OAI-PMH's <created> is unreliable — can refer to current version, not original)
    if to_fix and not DRY_RUN:
        print(f"\nFetching exact published dates from REST API...")
        import httpx
        fixed_count = 0
        failed_lookups = 0
        for p in to_fix:
            try:
                await asyncio.sleep(3)  # Respect arXiv rate limit
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        "https://export.arxiv.org/api/query",
                        params={"id_list": p["arxiv_id"], "max_results": "1"},
                    )
                    if resp.status_code == 200 and "<published>" in resp.text:
                        pub_match = re.search(r"<published>(.*?)</published>", resp.text)
                        if pub_match:
                            exact_date = pub_match.group(1)
                            await db.papers.update_one(
                                {"id": p["id"]},
                                {"$set": {"published": exact_date}},
                            )
                            # Also fix denormalized published in rankings
                            await db.rankings.update_one(
                                {"paper_id": p["id"]},
                                {"$set": {"published": exact_date}},
                            )
                            fixed_count += 1
                            if fixed_count <= 10:
                                print(f"  Fixed {p['arxiv_id']}: {p['published']} → {exact_date}")
                            continue
                # REST API failed — fall back to arxiv_id prefix approximation
                failed_lookups += 1
                approx = p["correct_date_approx"]
                await db.papers.update_one(
                    {"id": p["id"]},
                    {"$set": {"published": approx}},
                )
                await db.rankings.update_one(
                    {"paper_id": p["id"]},
                    {"$set": {"published": approx}},
                )
                if failed_lookups <= 5:
                    print(f"  Approx {p['arxiv_id']}: {p['published']} → ~{approx} (API unavailable)")
            except Exception as e:
                failed_lookups += 1
                # Fall back to approximation
                approx = p["correct_date_approx"]
                await db.papers.update_one(
                    {"id": p["id"]},
                    {"$set": {"published": approx}},
                )
                await db.rankings.update_one(
                    {"paper_id": p["id"]},
                    {"$set": {"published": approx}},
                )
                if failed_lookups <= 5:
                    print(f"  Approx {p['arxiv_id']}: → ~{approx} (error: {str(e)[:40]})")
        print(f"Fixed {fixed_count}/{len(to_fix)} exact, {failed_lookups} approximate")

    # Step 6: Delete old papers (with safety check — skip if they have matches)
    if to_delete and not DRY_RUN:
        print(f"\nDeleting {len(to_delete)} old papers (with match safety check)...")
        deleted_papers = 0
        deleted_rankings = 0
        deleted_matches = 0
        skipped_with_matches = 0
        for p in to_delete:
            pid = p["id"]
            # Safety: check if paper has any completed matches
            match_count = await db.matches.count_documents({
                "$or": [{"paper1_id": pid}, {"paper2_id": pid}],
                "completed": True,
            })
            if match_count > 0:
                skipped_with_matches += 1
                print(f"  SKIPPED {p['arxiv_id']} — has {match_count} matches (not safe to delete)")
                continue
            # No matches — safe to delete
            r = await db.papers.delete_one({"id": pid})
            deleted_papers += r.deleted_count
            r = await db.rankings.delete_one({"paper_id": pid})
            deleted_rankings += r.deleted_count

        print(f"Deleted: {deleted_papers} papers, {deleted_rankings} rankings")
        if skipped_with_matches:
            print(f"SKIPPED: {skipped_with_matches} papers with matches (manual review needed)")

    if DRY_RUN:
        print(f"\nDRY RUN complete. Set DRY_RUN=0 to apply changes.")
    else:
        print(f"\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
