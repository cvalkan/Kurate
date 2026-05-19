"""
End-to-end similarity landscape pipeline.
Atomic: UMAP → cluster → title generation in one pass.
Call this whenever coordinates change — never recompute steps independently.

Usage:
  python3 /app/tools/landscape_pipeline.py physics.comp-ph  # full pipeline
  python3 /app/tools/landscape_pipeline.py physics.comp-ph --titles-only  # just regen titles
"""
import asyncio, os, sys, json, uuid, re, numpy as np
from collections import defaultdict, Counter
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

SEED = 42

TITLE_PROMPT = """Below are paper abstracts from {n_clusters} different clusters of research papers. Generate a short (2-5 word) DISTINGUISHING theme label for Cluster {cluster_num}.

{all_clusters_text}

Focus on what makes Cluster {cluster_num} UNIQUE. Avoid generic labels.
Respond with JSON only: {{"title": "Molecular Dynamics Simulations"}}"""


async def call_llm(prompt, retries=2):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    for attempt in range(retries + 1):
        try:
            chat = LlmChat(api_key=os.environ.get("EMERGENT_LLM_KEY"),
                           session_id=f"lp-{uuid.uuid4().hex[:8]}",
                           system_message="Research topic classifier. JSON only."
                           ).with_model("anthropic", "claude-opus-4-6")
            r = await chat.send_message(UserMessage(text=prompt))
            t = r.strip()
            if t.startswith("```"): t = t.split("\n", 1)[-1]
            if t.endswith("```"): t = t[:-3].strip()
            if "{" in t: t = t[t.index("{"):t.rindex("}") + 1]
            return json.loads(t).get("title", "")
        except:
            if attempt < retries: await asyncio.sleep(1)
    return None


async def compute_view(name, td_matrix, papers, abstracts, data, sem):
    """
    ATOMIC pipeline for one view:
    1. UMAP on binary vectors with native metric
    2. K-Means for K=1..10 on UMAP coords
    3. Silhouette per K
    4. Title generation per K (parallel)
    All stored together — no partial/stale state.
    """
    import umap
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(papers)
    print(f"\n=== {name} ({td_matrix.shape[1]} features) ===")

    # Step 1: UMAP
    empty_rows = (td_matrix.sum(1) == 0)
    metric = "cosine" if empty_rows.any() else "jaccard"
    coords = umap.UMAP(metric=metric, n_neighbors=15, min_dist=0.3, spread=1.5,
                        random_state=SEED).fit_transform(td_matrix)
    coords = np.nan_to_num(coords, 0)
    coords -= coords.mean(0)
    s = max(coords[:, 0].max() - coords[:, 0].min(), coords[:, 1].max() - coords[:, 1].min())
    if s > 0:
        coords = coords / s * 100
    print(f"  UMAP done (metric={metric})")

    # Step 2+3: Cluster + silhouette
    cluster_labels = {"1": [0] * n}
    sil_per_k = {"1": 0.0}
    best_k, best_s = 2, -1
    for k in range(2, 11):
        lb = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(coords)
        cluster_labels[str(k)] = [int(x) for x in lb]
        sc = silhouette_score(coords, lb)
        sil_per_k[str(k)] = round(sc, 3)
        if sc > best_s:
            best_k, best_s = k, sc
    print(f"  Clustering done (best K={best_k}, sil={best_s:.3f})")

    # Step 4: Titles (parallel within each K, sequential across K)
    all_titles = {}

    async def gen_one(k, c, all_text, count):
        async with sem:
            prompt = TITLE_PROMPT.format(n_clusters=k, cluster_num=c, all_clusters_text=all_text)
            title = await call_llm(prompt)
            return str(c), f"{title} ({count})" if title else f"Cluster {c + 1} ({count})"

    for k in range(1, 11):
        labels = cluster_labels[str(k)]
        cp = defaultdict(list)
        for i, p in enumerate(papers):
            cp[labels[i]].append(p)
        if k == 1:
            all_titles["1"] = {"0": f"All Papers ({n})"}
            continue
        parts = []
        for cc in sorted(cp.keys()):
            block = "\n".join(f"  - {abstracts.get(p['id'], p['title'][:100])[:300]}" for p in cp[cc][:10])
            parts.append(f"Cluster {cc} ({len(cp[cc])}):\n{block}")
        all_text = "\n\n".join(parts)
        pairs = await asyncio.gather(*[gen_one(k, c, all_text, len(cp[c])) for c in sorted(cp.keys())])
        all_titles[str(k)] = dict(pairs)
        print(f"  K={k} titles done")

    # Store everything atomically
    for i, p in enumerate(papers):
        p[f"x_{name}"] = float(coords[i][0])
        p[f"y_{name}"] = float(coords[i][1])
    data[f"{name}_cluster_labels"] = cluster_labels
    data[f"{name}_cluster_titles"] = all_titles
    data[f"{name}_silhouette"] = round(best_s, 3)
    data[f"{name}_best_k"] = best_k
    data["silhouettes_per_k"][name] = sil_per_k

    print(f"  Stored: coords + labels + titles + silhouettes")
    return best_s, best_k


if __name__ == "__main__":
    print("This is a library module. Import compute_view() from your pipeline script.")
    print("Or run regen_titles.py for title-only regeneration.")
