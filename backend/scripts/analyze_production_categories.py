"""
Fetch all papers from kurate.org production for cs.AI, cs.LG, stat.ML
and analyze secondary-category overlap using arxiv API for categories.
"""
import requests
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter
from itertools import combinations
import random
import json

KURATE_API = "https://kurate.org/api/leaderboard"
ARXIV_API = "http://export.arxiv.org/api/query"

CATEGORIES_TO_ANALYZE = ["cs.AI", "cs.LG", "stat.ML"]

def fetch_all_papers(category):
    """Fetch all papers for a category from kurate.org production API."""
    papers = []
    cursor = None
    page = 0
    while True:
        params = {"category": category, "period": "all", "sort": "trueskill"}
        if cursor:
            params["cursor"] = cursor
        
        resp = requests.get(KURATE_API, params=params, timeout=30)
        data = resp.json()
        
        batch = data.get("leaderboard", [])
        papers.extend(batch)
        page += 1
        print(f"  Page {page}: got {len(batch)} papers (total: {len(papers)}/{data.get('total_papers', '?')})")
        
        cursor = data.get("next_cursor")
        if not batch or not cursor:
            break
        time.sleep(0.5)  # polite rate limit
    
    return papers, data.get("total_papers", len(papers))

def fetch_arxiv_categories(arxiv_ids, batch_size=200):
    """Fetch categories from arxiv API in batches."""
    all_cats = {}
    
    for i in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[i:i+batch_size]
        # Strip version suffix for API query
        clean_ids = [aid.replace("v1", "").replace("v2", "").replace("v3", "").rstrip("v") for aid in batch]
        id_list = ",".join(clean_ids)
        
        resp = requests.get(ARXIV_API, params={
            "id_list": id_list,
            "max_results": len(batch)
        }, timeout=60)
        
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        
        for entry in root.findall("atom:entry", ns):
            # Get arxiv ID
            entry_id = entry.find("atom:id", ns).text
            arxiv_id = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else entry_id
            
            # Get primary category
            primary_cat = entry.find("arxiv:primary_category", ns)
            primary = primary_cat.attrib.get("term", "") if primary_cat is not None else ""
            
            # Get all categories
            categories = []
            for cat in entry.findall("atom:category", ns):
                categories.append(cat.attrib.get("term", ""))
            
            all_cats[arxiv_id] = {"primary": primary, "all": categories}
        
        print(f"  Fetched categories for batch {i//batch_size + 1} ({len(batch)} papers)")
        time.sleep(1)  # arxiv rate limit (3 sec recommended)
    
    return all_cats

# --- Main ---
print("=" * 70)
print("PRODUCTION ANALYSIS: Secondary-Category Overlap")
print("=" * 70)

all_results = {}

for category in CATEGORIES_TO_ANALYZE:
    print(f"\n{'='*70}")
    print(f"Fetching {category} from kurate.org...")
    print(f"{'='*70}")
    
    papers, total = fetch_all_papers(category)
    print(f"  Total: {len(papers)} papers fetched ({total} total on platform)")
    
    # Extract arxiv_ids
    arxiv_ids = [p["arxiv_id"] for p in papers if p.get("arxiv_id")]
    print(f"  Papers with arxiv_id: {len(arxiv_ids)}")
    
    # Fetch categories from arxiv
    print(f"\nFetching categories from arxiv API...")
    cats_data = fetch_arxiv_categories(arxiv_ids)
    print(f"  Got categories for {len(cats_data)} papers")
    
    # Build secondary category lists per paper
    sec_lists = []
    papers_with_sec = 0
    all_secondaries = Counter()
    
    for p in papers:
        aid = p.get("arxiv_id", "")
        # Try to find in cats_data (with and without version)
        cat_info = cats_data.get(aid)
        if not cat_info:
            # Try stripping version
            stripped = aid.rsplit("v", 1)[0] if "v" in aid else aid
            cat_info = cats_data.get(stripped)
        
        if cat_info:
            primary = cat_info["primary"]
            secondaries = set(c for c in cat_info["all"] if c != primary)
            sec_lists.append(secondaries)
            if secondaries:
                papers_with_sec += 1
                for s in secondaries:
                    all_secondaries[s] += 1
        else:
            sec_lists.append(set())
    
    n = len(sec_lists)
    avg_sec = sum(len(s) for s in sec_lists) / n if n else 0
    
    print(f"\n--- {category} Summary ---")
    print(f"  Papers: {n}")
    print(f"  With secondaries: {papers_with_sec} ({papers_with_sec/n*100:.0f}%)")
    print(f"  Avg secondaries/paper: {avg_sec:.1f}")
    print(f"  Top secondaries:")
    for sc, cnt in all_secondaries.most_common(15):
        print(f"    {sc}: {cnt} ({cnt/n*100:.1f}%)")
    
    # Sample pairs and compute overlap distribution
    MAX_PAIRS = 50000
    if n <= 300:
        pair_indices = list(combinations(range(n), 2))
    else:
        pair_indices = set()
        attempts = 0
        while len(pair_indices) < MAX_PAIRS and attempts < MAX_PAIRS * 3:
            i = random.randint(0, n - 1)
            j = random.randint(0, n - 1)
            if i != j:
                pair_indices.add((min(i, j), max(i, j)))
            attempts += 1
        pair_indices = list(pair_indices)
    
    overlap_counts = Counter()
    for i, j in pair_indices:
        overlap = len(sec_lists[i] & sec_lists[j])
        overlap_counts[overlap] += 1
    
    total_pairs = len(pair_indices)
    pct_any_overlap = (total_pairs - overlap_counts.get(0, 0)) / total_pairs * 100 if total_pairs else 0
    
    print(f"\n  Overlap distribution ({total_pairs} pairs sampled):")
    for ov in sorted(overlap_counts.keys()):
        pct = overlap_counts[ov] / total_pairs * 100
        bar = "#" * int(pct / 2)
        print(f"    overlap={ov}: {overlap_counts[ov]:>6} pairs ({pct:5.1f}%) {bar}")
    print(f"  => {pct_any_overlap:.1f}% of same-primary pairs share >=1 secondary")
    
    # Per-paper: what fraction of pool shares a secondary?
    match_pcts = []
    for i, my_secs in enumerate(sec_lists):
        if not my_secs:
            continue
        matches = sum(1 for j, other_secs in enumerate(sec_lists) if j != i and len(my_secs & other_secs) > 0)
        match_pcts.append(matches / (n - 1) * 100)
    
    if match_pcts:
        avg_pool = sum(match_pcts) / len(match_pcts)
        median_pool = sorted(match_pcts)[len(match_pcts)//2]
        min_pool = min(match_pcts)
        max_pool = max(match_pcts)
        p25 = sorted(match_pcts)[len(match_pcts)//4]
        p75 = sorted(match_pcts)[3*len(match_pcts)//4]
        
        print(f"\n  For papers WITH secondaries ({len(match_pcts)}), % of pool sharing >=1:")
        print(f"    avg={avg_pool:.1f}%  median={median_pool:.1f}%  p25={p25:.1f}%  p75={p75:.1f}%  max={max_pool:.1f}%")
    
    all_results[category] = {
        "n_papers": n,
        "pct_with_sec": papers_with_sec / n * 100 if n else 0,
        "avg_sec": avg_sec,
        "pct_any_overlap": pct_any_overlap,
        "avg_pool_pct": avg_pool if match_pcts else 0,
        "median_pool_pct": median_pool if match_pcts else 0,
        "papers_without_sec": n - papers_with_sec,
    }

# --- Final Summary ---
print(f"\n{'='*70}")
print("FINAL SUMMARY — Option A Viability for cs.AI, cs.LG, stat.ML")
print(f"{'='*70}")
print(f"{'Category':<12} {'Papers':>7} {'%HasSec':>8} {'AvgSec':>7} {'%PairOverlap':>13} {'AvgPoolMatch':>13} {'MedianPool':>11}")
print("-" * 75)
for cat in CATEGORIES_TO_ANALYZE:
    r = all_results[cat]
    print(f"{cat:<12} {r['n_papers']:>7} {r['pct_with_sec']:>7.0f}% {r['avg_sec']:>6.1f} {r['pct_any_overlap']:>12.1f}% {r['avg_pool_pct']:>12.1f}% {r['median_pool_pct']:>10.1f}%")

print(f"\nConclusion:")
for cat in CATEGORIES_TO_ANALYZE:
    r = all_results[cat]
    if r["pct_any_overlap"] >= 30:
        verdict = "STRONG — Option A viable"
    elif r["pct_any_overlap"] >= 15:
        verdict = "MODERATE — Option A possible with relaxed split"
    elif r["pct_any_overlap"] >= 5:
        verdict = "WEAK — Option A marginal, consider Option B"
    else:
        verdict = "INSUFFICIENT — Need Option B"
    print(f"  {cat}: {verdict}")
