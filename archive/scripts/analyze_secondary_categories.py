"""
Analyze arxiv secondary-category overlap across papers in the database.
Goal: For each primary category, compute distribution of secondary-category
overlap counts between random same-primary paper pairs.
This determines if Option A (arxiv secondaries) has enough natural signal
for a 60/30/10 matchmaking split.
"""
import os
import sys
from collections import defaultdict, Counter
from itertools import combinations
import random

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient

client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ.get("DB_NAME", "papersumo")]

# --- Step 1: Understand categories field structure ---
print("=" * 70)
print("STEP 1: Sample categories field structure")
print("=" * 70)

samples = list(db.papers.find(
    {"categories": {"$exists": True}},
    {"_id": 0, "categories": 1, "title": 1}
).limit(5))

for s in samples:
    print(f"  Title: {s.get('title', 'N/A')[:60]}...")
    print(f"  Categories: {s.get('categories')}")
    print()

total_papers = db.papers.count_documents({})
total_with_cats = db.papers.count_documents({"categories": {"$exists": True}})
print(f"Total papers: {total_papers}")
print(f"Papers with categories field: {total_with_cats}")

# --- Step 2: Load all papers with categories ---
print("\n" + "=" * 70)
print("STEP 2: Loading all papers with categories...")
print("=" * 70)

papers = list(db.papers.find(
    {"categories": {"$exists": True, "$ne": []}},
    {"_id": 0, "categories": 1}
))

print(f"Loaded {len(papers)} papers with non-empty categories")

# --- Step 3: Parse primary + secondary categories ---
# Arxiv categories format: first element = primary, rest = secondary
# OR it could be a different structure. Let's detect.

primary_groups = defaultdict(list)  # primary_cat -> list of sets of secondary cats

for p in papers:
    cats = p.get("categories", [])
    if not cats or not isinstance(cats, list):
        continue
    
    primary = cats[0]  # first category = primary
    secondaries = set(cats[1:]) if len(cats) > 1 else set()
    primary_groups[primary].append(secondaries)

print(f"\nFound {len(primary_groups)} distinct primary categories")
print()

# --- Step 4: For each primary, compute secondary overlap distribution ---
print("=" * 70)
print("STEP 3: Secondary-category overlap distribution per primary")
print("=" * 70)

MAX_SAMPLE_PAIRS = 10000  # Max pairs to sample per primary category

results = {}

for primary in sorted(primary_groups.keys(), key=lambda k: -len(primary_groups[k])):
    sec_lists = primary_groups[primary]
    n = len(sec_lists)
    
    if n < 2:
        continue  # need at least 2 papers to form pairs
    
    # Count how many papers have at least 1 secondary
    has_secondary = sum(1 for s in sec_lists if len(s) > 0)
    avg_secondaries = sum(len(s) for s in sec_lists) / n if n else 0
    
    # Sample random pairs and compute overlap
    overlap_counts = Counter()  # overlap_count -> number of pairs
    
    if n <= 200:
        # Small category: enumerate all pairs
        pair_indices = list(combinations(range(n), 2))
    else:
        # Large category: sample random pairs
        pair_indices = set()
        attempts = 0
        while len(pair_indices) < MAX_SAMPLE_PAIRS and attempts < MAX_SAMPLE_PAIRS * 3:
            i = random.randint(0, n - 1)
            j = random.randint(0, n - 1)
            if i != j:
                pair_indices.add((min(i, j), max(i, j)))
            attempts += 1
        pair_indices = list(pair_indices)
    
    for i, j in pair_indices:
        overlap = len(sec_lists[i] & sec_lists[j])
        overlap_counts[overlap] += 1
    
    total_pairs = len(pair_indices)
    results[primary] = {
        "n_papers": n,
        "has_secondary_pct": has_secondary / n * 100,
        "avg_secondaries": avg_secondaries,
        "overlap_dist": dict(sorted(overlap_counts.items())),
        "total_pairs_sampled": total_pairs,
        "pct_with_any_overlap": (total_pairs - overlap_counts.get(0, 0)) / total_pairs * 100 if total_pairs else 0,
    }
    
    # Print summary for this category
    pct_overlap = results[primary]["pct_with_any_overlap"]
    print(f"\n{primary} ({n} papers, {has_secondary/n*100:.0f}% have secondaries, avg {avg_secondaries:.1f} sec/paper)")
    print(f"  Sampled {total_pairs} pairs:")
    for ov in sorted(overlap_counts.keys()):
        pct = overlap_counts[ov] / total_pairs * 100
        bar = "█" * int(pct / 2)
        print(f"    overlap={ov}: {overlap_counts[ov]:>6} pairs ({pct:5.1f}%) {bar}")
    print(f"  => {pct_overlap:.1f}% of same-primary pairs share >=1 secondary")

# --- Step 5: Overall summary ---
print("\n" + "=" * 70)
print("STEP 4: Overall Summary — Viability of Option A")
print("=" * 70)

# Focus on categories with >= 10 papers
significant = {k: v for k, v in results.items() if v["n_papers"] >= 10}

print(f"\nCategories with >=10 papers: {len(significant)}")
print(f"{'Category':<15} {'Papers':>7} {'%HasSec':>8} {'AvgSec':>7} {'%Overlap>=1':>12} {'Viable?':>8}")
print("-" * 65)

viable_count = 0
for cat in sorted(significant.keys(), key=lambda k: -significant[k]["n_papers"]):
    r = significant[cat]
    viable = "YES" if r["pct_with_any_overlap"] >= 30 else "MAYBE" if r["pct_with_any_overlap"] >= 15 else "NO"
    if viable == "YES":
        viable_count += 1
    print(f"{cat:<15} {r['n_papers']:>7} {r['has_secondary_pct']:>7.0f}% {r['avg_secondaries']:>6.1f} {r['pct_with_any_overlap']:>11.1f}% {viable:>8}")

print(f"\n=> {viable_count}/{len(significant)} categories have >=30% secondary overlap (viable for Option A)")
print(f"   Threshold for 60/30/10 split: need ~60% of pairs to have overlap for the 'shared-secondary' bucket")
print(f"   If overlap is too low, fall back to Option B (LLM classifier)")

# --- Step 6: Deep dive on cs.AI (the pilot category) ---
print("\n" + "=" * 70)
print("STEP 5: Deep Dive — cs.AI (pilot category)")
print("=" * 70)

if "cs.AI" in results:
    r = results["cs.AI"]
    print(f"  Papers: {r['n_papers']}")
    print(f"  Papers with >=1 secondary: {r['has_secondary_pct']:.0f}%")
    print(f"  Avg secondaries per paper: {r['avg_secondaries']:.1f}")
    print(f"  Pairs with >=1 shared secondary: {r['pct_with_any_overlap']:.1f}%")
    print(f"\n  Overlap distribution:")
    for ov, cnt in sorted(r["overlap_dist"].items()):
        pct = cnt / r["total_pairs_sampled"] * 100
        print(f"    {ov} shared secondaries: {cnt} pairs ({pct:.1f}%)")
    
    if r["pct_with_any_overlap"] >= 30:
        print(f"\n  CONCLUSION: cs.AI has SUFFICIENT secondary overlap for Option A.")
        print(f"  60% shared-secondary bucket is {'feasible' if r['pct_with_any_overlap'] >= 50 else 'tight — may need to relax to 50/40/10'}.")
    else:
        print(f"\n  CONCLUSION: cs.AI has INSUFFICIENT secondary overlap. Consider Option B.")
else:
    print("  cs.AI not found in database! Checking available categories...")
    for cat in sorted(primary_groups.keys()):
        if "ai" in cat.lower() or "AI" in cat:
            print(f"  Found: {cat} ({len(primary_groups[cat])} papers)")
