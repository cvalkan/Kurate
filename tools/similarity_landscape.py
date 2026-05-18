"""
Similarity landscape experiment: 200 latest cs.AI papers, 20 comparisons/paper.
Uses Claude Opus 4.6 via Emergent Universal Key. Score range 1-20 integers.
Outputs: similarity data + UMAP 2D embedding + interactive visualization.
"""
import asyncio
import os
import sys
import json
import random
import uuid
import math
import time as _time
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

N_PAPERS = 200
COMPS_PER_PAPER = 20
SEED = 42

PROMPT = """Rate the topical similarity between these two scientific papers on an integer scale from 1 to 20.

1 = completely unrelated topics
5 = same broad field, different subproblems
10 = same subfield, related methods or questions
15 = closely related, overlapping methods and goals
20 = nearly identical topic and research question

**Paper 1: {title1}**
{content1}

**Paper 2: {title2}**
{content2}

Respond with JSON only: {{"similarity": 12}}"""


async def get_papers(db, limit=250):
    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    papers = []
    async for doc in db.papers.find(
        {"categories.0": "cs.AI", f"summaries.{CLAUDE_KEY}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CLAUDE_KEY}": 1,
         "published": 1, "arxiv_id": 1, "link": 1},
    ).sort("published", -1).limit(limit):
        summary = doc.get("summaries", {}).get(CLAUDE_KEY, "")
        if isinstance(summary, str) and len(summary) > 100:
            papers.append({
                "id": doc["id"],
                "title": doc["title"],
                "abstract": doc.get("abstract", "")[:500],
                "content": f"{doc.get('abstract', '')}\n\nAI Impact Assessment:\n{summary[:1500]}",
                "published": doc.get("published", ""),
                "arxiv_id": doc.get("arxiv_id", ""),
                "link": doc.get("link", ""),
            })
    return papers[:N_PAPERS]


def generate_pairs(n_papers, comps_per_paper, seed):
    """Generate random pairs ensuring each paper gets ~comps_per_paper comparisons."""
    random.seed(seed)
    target_total = n_papers * comps_per_paper // 2
    
    # Track comparisons per paper
    counts = defaultdict(int)
    pairs = set()
    
    # Round-robin: each paper picks random partners until it has enough
    paper_ids = list(range(n_papers))
    attempts = 0
    while len(pairs) < target_total and attempts < target_total * 10:
        # Pick a paper that needs more comparisons
        needy = [p for p in paper_ids if counts[p] < comps_per_paper]
        if not needy:
            break
        p1 = random.choice(needy)
        # Pick a random partner (prefer those with fewer comparisons)
        candidates = [p for p in paper_ids if p != p1 and (p1, p) not in pairs and (p, p1) not in pairs]
        if not candidates:
            attempts += 1
            continue
        # Weight toward papers with fewer comparisons
        weights = [max(1, comps_per_paper - counts[p]) for p in candidates]
        total_w = sum(weights)
        r = random.random() * total_w
        cumulative = 0
        p2 = candidates[-1]
        for c, w in zip(candidates, weights):
            cumulative += w
            if cumulative >= r:
                p2 = c
                break
        pair = (min(p1, p2), max(p1, p2))
        if pair not in pairs:
            pairs.add(pair)
            counts[p1] += 1
            counts[p2] += 1
        attempts += 1
    
    # Stats
    comp_counts = [counts[i] for i in range(n_papers)]
    print(f"  Generated {len(pairs)} pairs")
    print(f"  Comparisons per paper: min={min(comp_counts)}, max={max(comp_counts)}, "
          f"mean={sum(comp_counts)/len(comp_counts):.1f}, median={sorted(comp_counts)[len(comp_counts)//2]}")
    
    return list(pairs)


async def call_llm(prompt, retries=2):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    for attempt in range(retries + 1):
        try:
            chat = LlmChat(
                api_key=os.environ.get("EMERGENT_LLM_KEY"),
                session_id=f"sim-{uuid.uuid4().hex[:8]}",
                system_message="You are a scientific paper similarity evaluator. Respond with JSON only."
            ).with_model("anthropic", "claude-opus-4-6")
            response = await chat.send_message(UserMessage(text=prompt))
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3].strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(text)
            score = data.get("similarity")
            if isinstance(score, (int, float)) and 1 <= score <= 20:
                return int(round(score))
            return None
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(2)
            else:
                return None
    return None


async def run_experiment():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    
    # Get papers
    papers = await get_papers(db)
    print(f"Loaded {len(papers)} cs.AI papers (latest by publication date)")
    print(f"Date range: {papers[-1]['published'][:10]} to {papers[0]['published'][:10]}")
    
    # Generate pairs
    print(f"\nGenerating pairs ({COMPS_PER_PAPER} comparisons/paper)...")
    pairs = generate_pairs(len(papers), COMPS_PER_PAPER, SEED)
    
    # Run similarity calls
    print(f"\nRunning {len(pairs)} similarity comparisons...")
    t0 = _time.time()
    
    results = {}  # (i, j) -> score
    sem = asyncio.Semaphore(3)
    completed = 0
    failed = 0
    
    async def process_pair(i, j):
        nonlocal completed, failed
        async with sem:
            p1, p2 = papers[i], papers[j]
            prompt = PROMPT.format(
                title1=p1["title"], content1=p1["content"][:2000],
                title2=p2["title"], content2=p2["content"][:2000],
            )
            score = await call_llm(prompt)
            completed += 1
            if score is None:
                failed += 1
            if completed % 50 == 0:
                elapsed = _time.time() - t0
                rate = completed / elapsed * 60
                eta = (len(pairs) - completed) / (rate / 60) if rate > 0 else 0
                print(f"  {completed}/{len(pairs)} done ({failed} failed) "
                      f"[{rate:.0f}/min, ETA {eta/60:.0f}min]")
            return (i, j), score
    
    tasks = [process_pair(i, j) for i, j in pairs]
    batch_results = await asyncio.gather(*tasks)
    
    for (i, j), score in batch_results:
        if score is not None:
            results[(i, j)] = score
    
    elapsed = _time.time() - t0
    print(f"\nCompleted: {len(results)}/{len(pairs)} ({len(pairs)-len(results)} failed)")
    print(f"Time: {elapsed/60:.1f} min")
    
    # Build similarity matrix (sparse → dense for MDS/UMAP)
    n = len(papers)
    import numpy as np
    
    # Distance matrix: 20 - similarity (higher similarity = lower distance)
    dist_matrix = np.full((n, n), 10.0)  # default: mid-distance for uncompared pairs
    np.fill_diagonal(dist_matrix, 0.0)
    
    for (i, j), score in results.items():
        dist = 20 - score  # convert similarity to distance
        dist_matrix[i][j] = dist
        dist_matrix[j][i] = dist
    
    # MDS embedding
    from sklearn.manifold import MDS
    print("\nComputing MDS embedding...")
    mds = MDS(n_components=2, dissimilarity="precomputed", random_state=SEED, max_iter=500, n_init=4)
    coords = mds.fit_transform(dist_matrix)
    stress = mds.stress_
    print(f"  MDS stress: {stress:.2f}")
    
    # Also try UMAP for comparison
    try:
        import umap
        print("Computing UMAP embedding...")
        reducer = umap.UMAP(metric="precomputed", n_neighbors=15, min_dist=0.1, random_state=SEED)
        coords_umap = reducer.fit_transform(dist_matrix)
        has_umap = True
        print("  UMAP done")
    except ImportError:
        print("  UMAP not available, using MDS only")
        coords_umap = coords
        has_umap = False
    
    # Clustering with simple K-means on the 2D coordinates
    from sklearn.cluster import KMeans
    # Try different K, pick best silhouette
    from sklearn.metrics import silhouette_score
    best_k, best_score = 5, -1
    for k in range(3, 12):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        labels = km.fit_predict(coords)
        sc = silhouette_score(coords, labels)
        if sc > best_score:
            best_k, best_score = k, sc
    
    km = KMeans(n_clusters=best_k, random_state=SEED, n_init=10)
    clusters = km.fit_predict(coords)
    print(f"  Best clustering: K={best_k} (silhouette={best_score:.3f})")
    
    # Get Kurate scores for sizing dots
    scores = {}
    async for doc in db.rankings.find(
        {"category": "cs.AI"},
        {"_id": 0, "paper_id": 1, "ts_score": 1, "score": 1},
    ):
        scores[doc["paper_id"]] = doc.get("ts_score") or doc.get("score", 1200)
    
    # Build output data
    paper_data = []
    for idx, p in enumerate(papers):
        paper_data.append({
            "id": p["id"],
            "title": p["title"],
            "abstract": p["abstract"][:200],
            "published": p["published"][:10] if p["published"] else "",
            "arxiv_id": p.get("arxiv_id", ""),
            "x": float(coords[idx][0]),
            "y": float(coords[idx][1]),
            "x_umap": float(coords_umap[idx][0]) if has_umap else float(coords[idx][0]),
            "y_umap": float(coords_umap[idx][1]) if has_umap else float(coords[idx][1]),
            "cluster": int(clusters[idx]),
            "score": scores.get(p["id"], 1200),
        })
    
    # Similarity distribution
    all_scores = list(results.values())
    from collections import Counter
    score_dist = Counter(all_scores)
    
    output = {
        "category": "cs.AI",
        "n_papers": len(papers),
        "n_pairs": len(results),
        "comps_per_paper": COMPS_PER_PAPER,
        "score_range": "1-20",
        "model": "claude-opus-4-6",
        "n_clusters": best_k,
        "silhouette": round(best_score, 3),
        "mds_stress": round(stress, 2),
        "has_umap": has_umap,
        "score_distribution": {str(k): v for k, v in sorted(score_dist.items())},
        "papers": paper_data,
    }
    
    out_path = "/app/backend/data/precomputed/similarity_landscape.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f)
    print(f"\nSaved to {out_path}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*60}")
    print(f"Papers: {len(papers)}")
    print(f"Pairs compared: {len(results)}")
    print(f"Score distribution (1-20):")
    for s in range(1, 21):
        count = score_dist.get(s, 0)
        bar = "#" * int(count / max(score_dist.values()) * 40) if score_dist else ""
        print(f"  {s:>2}: {bar} ({count})")
    print(f"Clusters found: {best_k}")
    print(f"MDS stress: {stress:.2f}")


if __name__ == "__main__":
    asyncio.run(run_experiment())
