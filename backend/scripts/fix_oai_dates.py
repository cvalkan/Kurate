"""Migration: Fix papers ingested with wrong OAI-PMH dates.

The first OAI-PMH deployment (Jun 4-5, 2026) used `published = updated`
(revision/modification date) instead of `published = created` (original
submission date). This caused two problems:

1. Old papers (e.g., from 2017) that arXiv reclassified appeared as new
   papers with a June 2026 publication date. These should be removed.

2. Recent papers got the wrong published date (e.g., a Jan 2026 paper
   showing as Jun 2026). These need their date corrected.

HOW IT WORKS:
  1. Find affected papers: short date format (YYYY-MM-DD) + no version suffix
     in arxiv_id — this fingerprint only matches OAI-PMH-ingested papers
  2. Compare arxiv_id prefix (YYMM) with published date to detect mismatches
  3. For old papers (pre-2025): delete (with safety check for matches)
  4. For wrong dates: fix via REST API lookup (exact) or YYMM prefix (approx)

SAFETY:
  - Only touches papers with the OAI-PMH fingerprint (short date + no version)
  - REST API papers (full ISO date or versioned ID) are NEVER touched
  - Old papers with completed matches are SKIPPED (flagged for manual review)
  - DRY_RUN mode previews all changes before applying

Usage:
  DRY_RUN=1 python -m scripts.fix_oai_dates   # Preview
  python -m scripts.fix_oai_dates              # Apply
"""
import asyncio
import os
import re

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"


def _arxiv_id_to_year_month(arxiv_id: str):
    """Extract (year, month) from arxiv_id prefix. '2601.18175' → (2026, 1)."""
    m = re.match(r'^(\d{2})(\d{2})\.', arxiv_id)
    if not m:
        return None, None
    yy, mm = int(m.group(1)), int(m.group(2))
    return (2000 + yy if yy < 50 else 1900 + yy), mm


def _month_diff(y1, m1, y2, m2):
    """Absolute month difference between two (year, month) pairs."""
    return abs((y1 * 12 + m1) - (y2 * 12 + m2))


async def _fix_published_date(db, paper, exact_date):
    """Update published date in both papers and rankings collections."""
    await db.papers.update_one({"id": paper["id"]}, {"$set": {"published": exact_date}})
    await db.rankings.update_one({"paper_id": paper["id"]}, {"$set": {"published": exact_date}})


async def main():
    from core.config import db

    print(f"{'DRY RUN' if DRY_RUN else 'LIVE RUN'} — Fix OAI-PMH date issues")
    print("=" * 60)

    # ── Step 1: Find OAI-PMH papers ──────────────────────────────────
    # Fingerprint: short date (≤10 chars) + no version suffix in arxiv_id
    oai_papers = []
    async for doc in db.papers.find(
        {"arxiv_id": {"$exists": True}},
        {"_id": 0, "id": 1, "arxiv_id": 1, "published": 1, "title": 1},
    ):
        pub = str(doc.get("published", ""))
        arxiv_id = doc.get("arxiv_id", "")
        if len(pub) <= 10 and pub and "v" not in arxiv_id:
            oai_papers.append(doc)

    print(f"Found {len(oai_papers)} OAI-PMH papers")

    # ── Step 2: Classify ─────────────────────────────────────────────
    to_delete = []
    to_fix = []
    ok = []

    for doc in oai_papers:
        arxiv_id = doc["arxiv_id"]
        pub = doc["published"]
        arxiv_year, arxiv_month = _arxiv_id_to_year_month(arxiv_id)
        if not arxiv_year:
            continue

        pub_year = int(pub[:4]) if len(pub) >= 4 else 0
        pub_month = int(pub[5:7]) if len(pub) >= 7 else 0

        if arxiv_year < 2025:
            to_delete.append({**doc, "reason": f"old ({arxiv_year}-{arxiv_month:02d})"})
        elif _month_diff(arxiv_year, arxiv_month, pub_year, pub_month) > 1:
            approx = f"{arxiv_year}-{arxiv_month:02d}-01"
            to_fix.append({**doc, "approx_date": approx})
        else:
            ok.append(doc)

    print(f"  OK: {len(ok)}  |  Wrong date: {len(to_fix)}  |  Old (delete): {len(to_delete)}")

    # ── Step 3: Preview ──────────────────────────────────────────────
    if to_delete:
        print(f"\nWill DELETE ({len(to_delete)}):")
        for p in to_delete[:15]:
            print(f"  {p['arxiv_id']:16s} pub={p['published']:12s} {p['reason']:20s} {p.get('title','')[:45]}")
        if len(to_delete) > 15:
            print(f"  ... +{len(to_delete)-15} more")

    if to_fix:
        print(f"\nWill FIX date ({len(to_fix)}):")
        for p in to_fix[:15]:
            print(f"  {p['arxiv_id']:16s} {p['published']:12s} → will lookup via REST API")
        if len(to_fix) > 15:
            print(f"  ... +{len(to_fix)-15} more")

    if DRY_RUN:
        print(f"\nDRY RUN complete.")
        return

    # ── Step 4: Fix dates (REST API for exact, skip if unavailable) ────
    if to_fix:
        import httpx
        print(f"\nFixing {len(to_fix)} dates...")
        fixed, skipped_api = 0, 0
        for p in to_fix:
            try:
                await asyncio.sleep(3)
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get("https://export.arxiv.org/api/query",
                                            params={"id_list": p["arxiv_id"], "max_results": "1"})
                    pub_match = re.search(r"<published>(.*?)</published>", resp.text) if resp.status_code == 200 else None
                    if pub_match:
                        await _fix_published_date(db, p, pub_match.group(1))
                        fixed += 1
                        if fixed <= 10:
                            print(f"  {p['arxiv_id']}: {p['published']} → {pub_match.group(1)}")
                        continue
            except Exception:
                pass
            # API unavailable — skip, re-run the script later
            skipped_api += 1
        print(f"  Fixed: {fixed}, Skipped (API unavailable): {skipped_api}")
        if skipped_api:
            print(f"  Re-run script later to fix the {skipped_api} remaining")

    # ── Step 5: Delete old papers ────────────────────────────────────
    if to_delete:
        print(f"\nDeleting {len(to_delete)} old papers...")
        deleted, skipped = 0, 0
        for p in to_delete:
            has_matches = await db.matches.count_documents(
                {"$or": [{"paper1_id": p["id"]}, {"paper2_id": p["id"]}], "completed": True}
            )
            if has_matches > 0:
                skipped += 1
                print(f"  SKIP {p['arxiv_id']} — {has_matches} matches (manual review)")
                continue
            await db.papers.delete_one({"id": p["id"]})
            await db.rankings.delete_one({"paper_id": p["id"]})
            deleted += 1
        print(f"  Deleted: {deleted}, Skipped (has matches): {skipped}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
