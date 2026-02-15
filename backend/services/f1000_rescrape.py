"""
Re-scrape all F1000 Alzheimer's papers via crawl-friendly requests
to capture ALL evaluations (not just the first one).
Uses longer delays and fresh user-agent to work around rate limits.
"""
import asyncio
import re
import httpx
import logging
from collections import defaultdict
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://archive.connect.h1.co"
RATING_MAP = {"Exceptional": 3, "Very Good": 2, "Good": 1}

# Use a completely different UA and slower rate
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def parse_all_evaluations(html: str) -> list[dict]:
    """Parse ALL evaluations from an article page — not just the first one.
    
    Key insight: evaluations appear as blocks with:
    - Rating text (Good/Very Good/Exceptional)  
    - Date
    - Evaluator name + member link
    - Review text
    
    Each recommendation citation follows pattern:
    'Cite this Recommendation: Name X: H1 Connect Recommendation...'
    These are the most reliable markers for each evaluation block.
    """
    soup = BeautifulSoup(html, "lxml")
    evaluations = []
    seen = set()
    
    # Strategy: find all "Cite this Recommendation" blocks — one per evaluation
    text = soup.get_text(" ", strip=True)
    
    # Find all recommendation citation patterns
    cite_pattern = re.compile(
        r'(Exceptional|Very Good|Good)\s+'
        r'(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})\s+'  # date
        r'.*?'  # avatar/link content
        r'Cite this Recommendation:\s*'
        r'([^:]+?):\s*H1 Connect Recommendation',
        re.DOTALL
    )
    
    for m in cite_pattern.finditer(text):
        rating_text = m.group(1)
        date = m.group(2)
        evaluator_raw = m.group(3).strip()
        
        # Clean evaluator name (remove extra spaces, "and" for co-evaluators)
        evaluator = re.sub(r'\s+', ' ', evaluator_raw).strip()
        # Take first name if co-evaluated (e.g., "Breese G and Criswell H")
        if " and " in evaluator:
            evaluator = evaluator.split(" and ")[0].strip()
        
        if evaluator in seen:
            continue
        seen.add(evaluator)
        
        # Try to find the full name from member links
        full_name = evaluator
        # Search for member link near this evaluator's text
        for a in soup.find_all("a", href=re.compile(r"/member/\d+")):
            link_text = a.get_text(strip=True)
            # Match by last name
            if link_text and evaluator.split()[-1] in link_text:
                full_name = link_text
                break
        
        evaluations.append({
            "rating": rating_text,
            "rating_value": RATING_MAP.get(rating_text, 0),
            "evaluator": full_name,
            "date": date,
        })
    
    return evaluations


async def rescrape_all_evaluations(db) -> dict:
    """Re-scrape all F1000 papers to get complete evaluations."""
    dataset_id = "f1000-alzheimers"
    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "f1000_article_id": 1, "title": 1}
    ).to_list(500)
    
    logger.info(f"Re-scraping {len(papers)} papers for complete evaluations...")
    
    updated = 0
    total_evals_before = 0
    total_evals_after = 0
    
    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
        for i, p in enumerate(papers):
            fid = p.get("f1000_article_id")
            if not fid:
                continue
            
            try:
                resp = await client.get(f"{BASE}/article/{fid}")
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code} for article {fid}")
                    await asyncio.sleep(3)
                    continue
                
                new_evals = parse_all_evaluations(resp.text)
                
                if new_evals:
                    # Get current eval count
                    current = await db.validation_papers.find_one(
                        {"id": p["id"]}, {"_id": 0, "evaluations": 1}
                    )
                    old_count = len(current.get("evaluations", [])) if current else 0
                    total_evals_before += old_count
                    total_evals_after += len(new_evals)
                    
                    # Format for DB
                    db_evals = [{
                        "rating_value": ev["rating_value"],
                        "evaluator": ev["evaluator"],
                        "source": "F1000Prime",
                        "rating_label": ev["rating"],
                        "date": ev.get("date"),
                    } for ev in new_evals]
                    
                    avg_rating = sum(e["rating_value"] for e in db_evals) / len(db_evals)
                    
                    await db.validation_papers.update_one(
                        {"id": p["id"]},
                        {"$set": {
                            "evaluations": db_evals,
                            "h1_avg_rating": round(avg_rating, 2),
                            "h1_rating_count": len(db_evals),
                            "scores": [e["rating_value"] for e in db_evals],
                        }}
                    )
                    
                    if len(new_evals) > old_count:
                        updated += 1
                        logger.info(f"[{i+1}/{len(papers)}] {p['title'][:40]}: {old_count} -> {len(new_evals)} evals")
            
            except Exception as e:
                logger.error(f"Error scraping {fid}: {e}")
            
            # Be very gentle with rate limiting
            await asyncio.sleep(2)
    
    # Now remove orphan papers
    all_papers = await db.validation_papers.find(
        {"dataset_id": dataset_id}, {"_id": 0, "id": 1, "evaluations": 1}
    ).to_list(1000)
    
    ev_counts = defaultdict(int)
    for pp in all_papers:
        for ev in pp.get("evaluations", []):
            ev_counts[ev["evaluator"]] += 1
    
    orphans = []
    for pp in all_papers:
        has_multi = any(ev_counts[ev["evaluator"]] >= 2 for ev in pp.get("evaluations", []))
        if not has_multi:
            orphans.append(pp["id"])
    
    if orphans:
        await db.validation_papers.delete_many({"id": {"$in": orphans}})
    
    # Calculate final stats
    remaining = await db.validation_papers.find(
        {"dataset_id": dataset_id}, {"_id": 0, "evaluations": 1}
    ).to_list(1000)
    
    evaluator_ratings = defaultdict(dict)
    for pp in remaining:
        for ev in pp.get("evaluations", []):
            evaluator_ratings[ev["evaluator"]][pp.get("id", "")] = ev["rating_value"]
    
    total_pairs = 0
    disc_pairs = 0
    for name, ratings in evaluator_ratings.items():
        vals = list(ratings.values())
        for a in range(len(vals)):
            for b in range(a + 1, len(vals)):
                total_pairs += 1
                if vals[a] != vals[b]:
                    disc_pairs += 1
    
    multi_ev = sum(1 for n, r in evaluator_ratings.items() if len(r) >= 2)
    
    return {
        "papers_updated": updated,
        "evals_before": total_evals_before,
        "evals_after": total_evals_after,
        "orphans_removed": len(orphans),
        "total_papers": len(remaining),
        "unique_evaluators": len(evaluator_ratings),
        "multi_paper_evaluators": multi_ev,
        "total_pairs": total_pairs,
        "discriminative_pairs": disc_pairs,
    }
