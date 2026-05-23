"""Compute PMI-based surprise/multidisciplinarity scores for Similarity Landscape papers.

For each paper, computes the negative average PMI across all pairs of its tags.
High score = tags rarely co-occur = surprising/multidisciplinary combination.
Scores are normalized to [0, 1] within each category.

Adds per-paper `surprise_score` and top-level `surprise_ranking` to the landscape JSON.

Usage:
    python3 /app/tools/compute_surprise_scores.py
    python3 /app/tools/compute_surprise_scores.py cs_GT
"""
import json, sys, math
from pathlib import Path
from collections import Counter

PRECOMPUTED = Path("/app/backend/data/precomputed")
TARGETS = [
    ("similarity_landscape_cs_GT.json", "cs.GT"),
    ("similarity_landscape_physics_comp_ph.json", "physics.comp-ph"),
]


def get_tags(p):
    t = p.get("tags_incremental") or p.get("tags") or {}
    if isinstance(t, list): return t
    if isinstance(t, dict):
        if "tags" in t and isinstance(t["tags"], list): return t["tags"]
        out = []
        for k in ("topics", "methods", "domains", "concepts"):
            out.extend(t.get(k) or [])
        return out
    return []


def compute_scores(papers):
    n = len(papers)
    all_tags = [sorted(set(get_tags(p))) for p in papers]

    # Tag frequency
    tag_freq = Counter()
    for tags in all_tags:
        for t in tags:
            tag_freq[t] += 1

    # Co-occurrence frequency
    cooccur = Counter()
    for tags in all_tags:
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                cooccur[(tags[i], tags[j])] += 1

    # PMI surprise per paper
    raw_scores = []
    for i, tags in enumerate(all_tags):
        if len(tags) < 2:
            raw_scores.append(0.0)
            continue
        pmis = []
        for a in range(len(tags)):
            for b in range(a + 1, len(tags)):
                key = (tags[a], tags[b])
                p_a = tag_freq[tags[a]] / n
                p_b = tag_freq[tags[b]] / n
                p_ab = cooccur.get(key, 0) / n
                if p_ab > 0 and p_a > 0 and p_b > 0:
                    pmis.append(math.log2(p_ab / (p_a * p_b)))
                else:
                    pmis.append(-5)
        raw_scores.append(-sum(pmis) / len(pmis) if pmis else 0.0)

    # Normalize to [0, 1]
    mn, mx = min(raw_scores), max(raw_scores)
    rng = mx - mn if mx > mn else 1.0
    return [(s - mn) / rng for s in raw_scores]


def process(json_name, category):
    path = PRECOMPUTED / json_name
    data = json.loads(path.read_text())
    papers = data["papers"]
    print(f"\n=== {category} ({len(papers)} papers) ===")

    scores = compute_scores(papers)

    # Add per-paper score
    for i, p in enumerate(papers):
        p["surprise_score"] = round(scores[i], 4)

    # Build ranked list (top 50)
    ranked = sorted(range(len(papers)), key=lambda i: -scores[i])
    ranking = []
    for rank, idx in enumerate(ranked[:50], 1):
        p = papers[idx]
        tags = get_tags(p)
        ranking.append({
            "rank": rank,
            "id": p["id"],
            "title": p["title"],
            "score": round(scores[idx], 4),
            "tags": tags[:8],
            "elo_score": p.get("score", 0),
        })
    data["surprise_ranking"] = ranking

    path.write_text(json.dumps(data))
    print(f"  Saved {len(ranking)} surprise rankings")
    for r in ranking[:5]:
        print(f"  {r['rank']}. [{r['score']:.3f}] {r['title'][:60]}")
        print(f"     {r['tags'][:5]}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for fname, cat in TARGETS:
        if target and target not in fname:
            continue
        process(fname, cat)
