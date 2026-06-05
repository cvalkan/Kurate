"""Migration: Fix published dates on papers ingested via OAI-PMH.

The first OAI-PMH deployment (Jun 4-5, 2026) used `published = updated`
(modification date) instead of `published = created` (original submission).
This script fixes the published date for all affected papers using the
authoritative REST API. Papers that can't be fixed (API unavailable) are
skipped — re-run the script later to catch them.

HOW IT WORKS:
  1. Find affected papers: short date format (YYYY-MM-DD) + no version suffix
  2. For each: call REST API to get the correct original published date
  3. Update both papers.published and rankings.published
  4. Final pass: fix any rankings where paper was fixed but ranking was missed

SAFETY:
  - Only touches papers matching the OAI-PMH fingerprint
  - REST API papers are never touched
  - If the REST API is unavailable for a paper, it's skipped (not approximated)
  - Idempotent: already-fixed papers won't match the fingerprint on re-run

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


async def main():
    from core.config import db

    print(f"{'DRY RUN' if DRY_RUN else 'LIVE RUN'} — Fix OAI-PMH published dates")
    print("=" * 60)

    # ── Step 1: Find OAI-PMH papers ──────────────────────────────────
    # Fingerprint: short date (≤10 chars) + no version suffix in arxiv_id
    # REST API papers have full ISO dates and/or versioned IDs — excluded.
    affected = []
    async for doc in db.papers.find(
        {"arxiv_id": {"$exists": True}},
        {"_id": 0, "id": 1, "arxiv_id": 1, "published": 1, "title": 1},
    ):
        pub = str(doc.get("published", ""))
        arxiv_id = doc.get("arxiv_id", "")
        if len(pub) <= 10 and pub and "v" not in arxiv_id:
            affected.append(doc)

    print(f"Found {len(affected)} papers with OAI-PMH date fingerprint")

    if not affected:
        print("Nothing to fix.")
        return

    # ── Step 2: Preview ──────────────────────────────────────────────
    print(f"\nSample (first 15):")
    for p in affected[:15]:
        print(f"  {p['arxiv_id']:16s} pub={p['published']:12s} {p.get('title','')[:50]}")
    if len(affected) > 15:
        print(f"  ... +{len(affected)-15} more")

    if DRY_RUN:
        print(f"\nDRY RUN complete. {len(affected)} papers would be fixed.")
        return

    # ── Step 3: Fix each paper via REST API ──────────────────────────
    import httpx
    print(f"\nFixing {len(affected)} papers via REST API (3s between calls)...")
    fixed, skipped = 0, 0
    for p in affected:
        try:
            await asyncio.sleep(3)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://export.arxiv.org/api/query",
                    params={"id_list": p["arxiv_id"], "max_results": "1"},
                )
                if resp.status_code == 200:
                    pub_match = re.search(r"<published>(.*?)</published>", resp.text)
                    if pub_match:
                        exact_date = pub_match.group(1)
                        await db.papers.update_one(
                            {"id": p["id"]},
                            {"$set": {"published": exact_date}},
                        )
                        await db.rankings.update_one(
                            {"paper_id": p["id"]},
                            {"$set": {"published": exact_date}},
                        )
                        fixed += 1
                        if fixed <= 20:
                            print(f"  [{fixed}] {p['arxiv_id']}: {p['published']} → {exact_date}")
                        elif fixed % 100 == 0:
                            print(f"  ... {fixed}/{len(affected)} fixed")
                        continue
        except Exception:
            pass
        skipped += 1

    print(f"\nDone: {fixed} fixed, {skipped} skipped (API unavailable)")
    if skipped:
        print(f"Re-run the script later to fix the remaining {skipped}.")

    # ── Step 4: Repair rankings where paper was fixed but ranking wasn't ─
    # Only checks OAI papers (no version suffix) with full ISO dates (already fixed).
    print(f"\nChecking for paper/ranking date mismatches...")
    repaired = 0
    async for paper in db.papers.find(
        {"arxiv_id": {"$exists": True, "$not": {"$regex": "v\\d+$"}}},
        {"_id": 0, "id": 1, "published": 1},
    ):
        pub = str(paper.get("published", ""))
        if len(pub) <= 10 or not pub:
            continue  # Not yet fixed
        ranking = await db.rankings.find_one(
            {"paper_id": paper["id"]},
            {"_id": 0, "published": 1},
        )
        if ranking and str(ranking.get("published", "")) != pub:
            await db.rankings.update_one(
                {"paper_id": paper["id"]},
                {"$set": {"published": pub}},
            )
            repaired += 1
    print(f"  Repaired {repaired} ranking date mismatches")


if __name__ == "__main__":
    asyncio.run(main())
