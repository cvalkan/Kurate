"""
Similarity landscape experiment for physics.comp-ph.
Same methodology as cs.AI: 20 comparisons/paper, 1-20 integer scale, Claude Opus 4.6.
Then: MDS + UMAP embedding, K-Means clustering K=1..10, LLM cluster titles.
"""
import asyncio
import os
import sys
import json
import random
import uuid
import math
import time as _time
import numpy as np
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

CATEGORY = "physics.comp-ph"
COMPS_PER_PAPER = 20
SEED = 42
OUT_PATH = "/app/backend/data/precomputed/similarity_landscape_physics_comp_ph.json"

SIMILARITY_PROMPT = """Rate the topical similarity between these two scientific papers on an integer scale from 1 to 20.

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

TITLE_PROMPT = """Given these paper abstracts from a cluster of computational physics research papers, generate a short (2-5 word) theme label that captures the common research topic.

Paper abstracts:
{abstracts}

Respond with JSON only: {{"title": "Molecular Dynamics Simulations"}}"""


async def get_papers(db):
    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    papers = []
    async for doc in db.papers.find(
        {"categories.0": CATEGORY, f"summaries.{CLAUDE_KEY}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CLAUDE_KEY}": 1,
         "published": 1, "arxiv_id": 1},
    ).sort("published", -1):
        summary = doc.get("summaries", {}).get(CLAUDE_KEY, "")
        if isinstance(summary, str) and len(summary) > 100:
            papers.append({
                "id": doc["id"],
                "title": doc["title"],
                "abstract": doc.get("abstract", "")[:500],
                "content": f"{doc.get('abstract', '')}\n\nAI Impact Assessment:\n{summary[:1500]}",
                "published": doc.get("published", ""),
                "arxiv_id": doc.get("arxiv_id", ""),
            })
    return papers


def generate_pairs(n_papers, comps_per_paper, seed):
    random.seed(seed)
    target_total = n_papers * comps_per_paper // 2
    counts = defaultdict(int)
    pairs = set()
    paper_ids = list(range(n_papers))
    attempts = 0
    while len(pairs) < target_total and attempts < target_total * 10:
        needy = [p for p in paper_ids if counts[p] < comps_per_paper]
        if not needy:
            break
        p1 = random.choice(needy)
        candidates = [p for p in paper_ids if p != p1 and (p1, p) not in pairs and (p, p1) not in pairs]
        if not candidates:
            attempts += 1
            continue
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
    comp_counts = [counts[i] for i in range(n_papers)]
    print(f"  Generated {len(pairs)} pairs")
    print(f"  Comparisons per paper: min={min(comp_counts)}, max={max(comp_counts)}, mean={sum(comp_counts)/len(comp_counts):.1f}")
    return list(pairs)


async def call_llm(prompt, system_msg="You are a scientific paper similarity evaluator. Respond with JSON only.", retries=2):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    for attempt in range(retries + 1):
        try:
            chat = LlmChat(
                api_key=os.environ.get("EMERGENT_LLM_KEY"),
                session_id=f"sim-{uuid.uuid4().hex[:8]}",
                system_message=system_msg,
            ).with_model("anthropic", "claude-opus-4-6")
            response = await chat.send_message(UserMessage(text=prompt))
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3].strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(text)
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(2)
    return None


async def run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # Step 1: Get papers
    papers = await get_papers(db)
    print(f"Loaded {len(papers)} {CATEGORY} papers")
    if papers:
        print(f"Date range: {papers[-1]['published'][:10]} to {papers[0]['published'][:10]}")

    # Step 2: Generate pairs
    n = len(papers)
    print(f"\nGenerating pairs ({COMPS_PER_PAPER} comparisons/paper)...")
    pairs = generate_pairs(n, COMPS_PER_PAPER, SEED)

    # Step 3: Run similarity comparisons (with incremental save)
    print(f"\nRunning {len(pairs)} similarity comparisons...")
    t0 = _time.time()
    
    # Load any previously saved partial results
    partial_path = OUT_PATH + ".partial"
    results = {}
    if os.path.exists(partial_path):
        with open(partial_path) as f:
            saved = json.load(f)
        results = {(r[0], r[1]): r[2] for r in saved}
        print(f"  Resumed {len(results)} pairs from partial save")
    
    # Filter out already-completed pairs
    remaining_pairs = [(i, j) for i, j in pairs if (i, j) not in results]
    print(f"  {len(remaining_pairs)} pairs remaining")
    
    sem = asyncio.Semaphore(3)
    completed = len(results)
    failed = 0

    async def process_pair(i, j):
        nonlocal completed, failed
        async with sem:
            p1, p2 = papers[i], papers[j]
            prompt = SIMILARITY_PROMPT.format(
                title1=p1["title"], content1=p1["content"][:2000],
                title2=p2["title"], content2=p2["content"][:2000],
            )
            data = await call_llm(prompt)
            score = None
            if data and "similarity" in data:
                s = data["similarity"]
                if isinstance(s, (int, float)) and 1 <= s <= 20:
                    score = int(round(s))
            completed += 1
            if score is None:
                failed += 1
            else:
                results[(i, j)] = score
            # Save partial results every 50 pairs
            if completed % 50 == 0:
                elapsed = _time.time() - t0
                rate = completed / elapsed * 60 if elapsed > 0 else 0
                remaining = len(pairs) - completed
                eta = remaining / (rate / 60) if rate > 0 else 0
                print(f"  {completed}/{len(pairs)} done ({failed} failed) [{rate:.0f}/min, ETA {eta/60:.0f}min]")
                # Incremental save
                with open(partial_path, "w") as f:
                    json.dump([[i, j, s] for (i, j), s in results.items()], f)
            return (i, j), score

    tasks = [process_pair(i, j) for i, j in remaining_pairs]
    await asyncio.gather(*tasks)
    
    # Final save of partial results
    with open(partial_path, "w") as f:
        json.dump([[i, j, s] for (i, j), s in results.items()], f)

    elapsed = _time.time() - t0
    print(f"\nCompleted: {len(results)}/{len(pairs)} ({len(pairs)-len(results)} failed)")
    print(f"Time: {elapsed/60:.1f} min")

    # Step 4: Build distance matrix
    dist_matrix = np.full((n, n), 10.0)
    np.fill_diagonal(dist_matrix, 0.0)
    for (i, j), score in results.items():
        dist = 20 - score
        dist_matrix[i][j] = dist
        dist_matrix[j][i] = dist

    # Step 5: MDS
    from sklearn.manifold import MDS
    print("\nComputing MDS embedding...")
    mds = MDS(n_components=2, dissimilarity="precomputed", random_state=SEED, max_iter=500, n_init=4)
    coords = mds.fit_transform(dist_matrix)
    stress = mds.stress_
    print(f"  MDS stress: {stress:.2f}")

    # Step 6: UMAP
    import umap
    print("Computing UMAP embedding...")
    # Compute UMAP from MDS distances (better spread)
    from scipy.spatial.distance import pdist, squareform
    mds_dist = squareform(pdist(coords))
    reducer = umap.UMAP(metric="precomputed", n_neighbors=10, min_dist=0.8, spread=2.5, random_state=SEED)
    coords_umap = reducer.fit_transform(mds_dist)
    print("  UMAP done")

    # Step 7: Clustering K=1..10 + titles
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    best_k, best_score = 5, -1
    for k in range(3, 12):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        labels = km.fit_predict(coords)
        sc = silhouette_score(coords, labels)
        if sc > best_score:
            best_k, best_score = k, sc

    km = KMeans(n_clusters=best_k, random_state=SEED, n_init=10)
    default_clusters = km.fit_predict(coords)
    print(f"  Best clustering: K={best_k} (silhouette={best_score:.3f})")

    # Generate cluster labels and titles for K=1..10
    all_cluster_titles = {}
    all_cluster_labels = {}

    for k in range(1, 11):
        print(f"\n  Generating titles for K={k}...")
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        labels = km.fit_predict(coords)
        all_cluster_labels[str(k)] = [int(l) for l in labels]

        cluster_papers = defaultdict(list)
        for i, p in enumerate(papers):
            cluster_papers[int(labels[i])].append(p)

        titles = {}
        for c in sorted(cluster_papers.keys()):
            sample = cluster_papers[c][:20]
            abstracts_text = "\n\n".join(f"- {p['abstract'][:400]}" for p in sample)
            prompt = TITLE_PROMPT.format(abstracts=abstracts_text)
            data = await call_llm(prompt, system_msg="You are a research topic classifier. Respond with JSON only.")
            title = data.get("title", "") if data else ""
            count = len(cluster_papers[c])
            titles[str(c)] = f"{title} ({count})" if title else f"Cluster {c+1} ({count})"
            print(f"    Cluster {c}: {titles[str(c)]}")

        all_cluster_titles[str(k)] = titles

    # Step 8: Get Kurate scores
    scores = {}
    async for doc in db.rankings.find({"category": CATEGORY}, {"_id": 0, "paper_id": 1, "ts_score": 1, "score": 1}):
        scores[doc["paper_id"]] = doc.get("ts_score") or doc.get("score", 1200)

    # Step 9: Build output
    from collections import Counter
    score_dist = Counter(results.values())

    paper_data = []
    for idx, p in enumerate(papers):
        paper_data.append({
            "id": p["id"], "title": p["title"], "abstract": p["abstract"][:200],
            "published": p["published"][:10] if p["published"] else "",
            "arxiv_id": p.get("arxiv_id", ""),
            "x": float(coords[idx][0]), "y": float(coords[idx][1]),
            "x_umap": float(coords_umap[idx][0]), "y_umap": float(coords_umap[idx][1]),
            "cluster": int(default_clusters[idx]),
            "score": scores.get(p["id"], 1200),
        })

    output = {
        "category": CATEGORY,
        "n_papers": len(papers), "n_pairs": len(results),
        "comps_per_paper": COMPS_PER_PAPER, "score_range": "1-20",
        "model": "claude-opus-4-6",
        "n_clusters": best_k, "silhouette": round(best_score, 3),
        "mds_stress": round(stress, 2), "has_umap": True,
        "score_distribution": {str(k): v for k, v in sorted(score_dist.items())},
        "cluster_titles": all_cluster_titles,
        "cluster_labels": all_cluster_labels,
        "papers": paper_data,
    }

    with open(OUT_PATH, "w") as f:
        json.dump(output, f)
    print(f"\nSaved to {OUT_PATH}")

    # Summary
    print(f"\n{'='*60}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*60}")
    print(f"Category: {CATEGORY}")
    print(f"Papers: {len(papers)}")
    print(f"Pairs compared: {len(results)}")
    print(f"Clusters: {best_k} (silhouette {best_score:.3f})")
    print(f"Score distribution:")
    for s in range(1, 21):
        count = score_dist.get(s, 0)
        if count:
            print(f"  {s:>2}: {'#' * int(count / max(score_dist.values()) * 40)} ({count})")


if __name__ == "__main__":
    asyncio.run(run())
