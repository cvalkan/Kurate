"""A/B test SPECTER2 / SciNCL embeddings vs OpenAI text-embedding-3-large
on the cs.GT and physics.comp-ph Similarity Landscapes.

All else held equal: same input text (abstract + Claude Opus 4.6 summary),
same UMAP-40 + HDBSCAN + UMAP-2 pipeline, same quality-metric suite.
"""
import os, json, sys, random
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

from pymongo import MongoClient
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.manifold import trustworthiness as sk_trustworthiness
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics.pairwise import cosine_similarity
from scipy.spatial.distance import pdist, squareform
import umap, hdbscan

SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
KNN = 10
SEED = 42

TARGETS = [
    ("similarity_landscape_cs_GT.json",          "cs.GT"),
    ("similarity_landscape_physics_comp_ph.json","physics.comp-ph"),
]
PRECOMPUTED = Path("/app/backend/data/precomputed")
OUT_PATH = PRECOMPUTED / "embedding_ab_specter_scincl.json"


def flatten_tags(t):
    if isinstance(t, list): return list(t)
    if isinstance(t, dict):
        if isinstance(t.get("tags"), list): return list(t["tags"])
        out = []
        for k in ("topics","methods","domains","concepts"):
            out.extend(t.get(k) or [])
        return out
    return []


def fetch_inputs(papers, category):
    """Return per-paper title + abstract + summary string (truncated)."""
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    ids = [p["id"] for p in papers]
    docs = {}
    for d in db.papers.find(
        {"id": {"$in": ids}, f"summaries.{SUMMARY_KEY}": {"$exists": True}},
        {"_id":0,"id":1,"title":1,"abstract":1,f"summaries.{SUMMARY_KEY}":1}):
        s = (d.get("summaries") or {}).get(SUMMARY_KEY) or ""
        docs[d["id"]] = {
            "title": d.get("title",""),
            "abstract": d.get("abstract",""),
            "summary": s if isinstance(s,str) else "",
        }
    out = []
    for p in papers:
        meta = docs.get(p["id"], {"title":p.get("title",""),"abstract":"","summary":""})
        out.append(meta)
    return out


def embed_st(model_id, sentences, max_length=512):
    """Embed via sentence-transformers, mean-pool, normalize."""
    from sentence_transformers import SentenceTransformer
    print(f"  Loading {model_id}...")
    model = SentenceTransformer(model_id, cache_folder="/opt/hf_cache")
    print(f"  Encoding {len(sentences)} inputs (max_length={max_length})...")
    if hasattr(model, "max_seq_length"):
        model.max_seq_length = max_length
    emb = model.encode(sentences, batch_size=16, show_progress_bar=False,
                       convert_to_numpy=True, normalize_embeddings=True)
    return emb.astype(np.float32)


def reduce_and_cluster(emb):
    """Same pipeline as our production: 40D UMAP -> HDBSCAN -> 2D UMAP."""
    n = len(emb)
    n_neighbors = min(15, n-1)
    # 40D UMAP for clustering
    high = umap.UMAP(n_components=40, n_neighbors=n_neighbors, min_dist=0.0,
                     metric="cosine", random_state=SEED).fit_transform(emb)
    # HDBSCAN clustering
    min_size = max(5, n // 30)
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_size, min_samples=1,
                                metric="euclidean")
    labels = clusterer.fit_predict(high)
    # 2D UMAP for visualization (separate)
    coords2d = umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=0.08,
                        metric="cosine", random_state=SEED).fit_transform(emb)
    return labels, coords2d


def cosine_dist_matrix(emb):
    sim = cosine_similarity(emb); np.clip(sim, -1, 1, out=sim)
    d = (1.0 - sim).astype(np.float32); np.fill_diagonal(d, 0.0); return d


def metric_suite(emb, coords2d, labels, tag_sets):
    """All 6 quality metrics in one shot."""
    dist_high = cosine_dist_matrix(emb)
    # Trustworthiness + Continuity
    trust = sk_trustworthiness(dist_high, coords2d, n_neighbors=KNN, metric="precomputed")
    dist_low = squareform(pdist(coords2d, metric="euclidean")).astype(np.float32)
    cont = sk_trustworthiness(dist_low, dist_high, n_neighbors=KNN, metric="precomputed")
    # Neighborhood preservation
    knn_high = np.argsort(dist_high, axis=1)[:, 1:KNN+1]
    nn = NearestNeighbors(n_neighbors=KNN+1, metric="euclidean").fit(coords2d)
    knn_low = nn.kneighbors(coords2d, return_distance=False)[:, 1:]
    nbr = float(np.mean([len(set(knn_high[i]) & set(knn_low[i])) / KNN for i in range(len(emb))]))
    # Explainability — fraction of 2D nbrs sharing ≥1 tag
    nn2 = NearestNeighbors(n_neighbors=KNN+1, metric="euclidean").fit(coords2d)
    idxs = nn2.kneighbors(coords2d, return_distance=False)[:, 1:]
    expl_vals = []
    for i, anchor in enumerate(tag_sets):
        if not anchor: continue
        expl_vals.append(sum(1 for j in idxs[i] if tag_sets[j] & anchor) / KNN)
    expl = float(np.mean(expl_vals)) if expl_vals else None
    # Davies-Bouldin (skip HDBSCAN noise)
    valid = labels >= 0
    db_val = None
    if valid.sum() >= 3 and len(set(labels[valid])) >= 2:
        try: db_val = float(davies_bouldin_score(coords2d[valid], labels[valid]))
        except Exception: pass
    # Silhouette on 2D
    sil = None
    if len(set(labels[valid])) >= 2:
        try: sil = float(silhouette_score(coords2d[valid], labels[valid]))
        except Exception: pass
    # HDBSCAN noise %
    noise = int((labels == -1).sum())
    return {
        "trustworthiness": round(trust,3),
        "continuity": round(cont,3),
        "neighborhood_preservation": round(nbr,3),
        "explainability": round(expl,3) if expl is not None else None,
        "davies_bouldin": round(db_val,3) if db_val is not None else None,
        "silhouette_2d": round(sil,3) if sil is not None else None,
        "hdbscan_clusters": int(len(set(labels[valid]))) if valid.any() else 0,
        "hdbscan_noise": noise,
    }


def run_for_category(json_name, category):
    print(f"\n=== {category} ===")
    d = json.loads((PRECOMPUTED / json_name).read_text())
    papers = d["papers"]
    print(f"  {len(papers)} papers")
    inputs = fetch_inputs(papers, category)
    tag_sets = [set(flatten_tags(p.get("tags_incremental") or p.get("tags") or {})) for p in papers]

    # Same text input as our combined-large pipeline: abstract + summary
    text_inputs = [f"{x['title']}. {x['abstract']}\n\nImpact: {x['summary'][:1500]}".strip() for x in inputs]

    results = {"category": category, "n_papers": len(papers), "methods": {}}

    # 1. OpenAI baseline — pull persisted metrics from the landscape JSON
    openai_metrics = {
        "dim": 3072,
        "trustworthiness": d.get("emb_combined_large_trustworthiness"),
        "continuity": d.get("emb_combined_large_continuity"),
        "neighborhood_preservation": d.get("emb_combined_large_neighborhood_preservation"),
        "explainability": d.get("emb_combined_large_explainability"),
        "davies_bouldin": d.get("emb_combined_large_davies_bouldin"),
        "silhouette_2d": d.get("emb_combined_large_silhouette"),
        "hdbscan_clusters": d.get("emb_combined_large_n_clusters"),
        "hdbscan_noise": d.get("emb_combined_large_noise"),
    }
    results["methods"]["openai_text_embedding_3_large"] = openai_metrics
    print(f"  OpenAI (from landscape JSON): {openai_metrics}")

    # 2 & 3. SciNCL + SPECTER1 (both BERT-based, sentence-transformers compatible)
    # SPECTER expects "title[SEP]abstract" — we'll feed our richer text.
    for label, model_id in [
        ("scincl", "malteos/scincl"),
        ("specter", "allenai/specter"),
    ]:
        try:
            emb = embed_st(model_id, text_inputs, max_length=512)
            print(f"  {label}: emb shape = {emb.shape}")
            labels, coords2d = reduce_and_cluster(emb)
            results["methods"][label] = {
                "dim": int(emb.shape[1]),
                **metric_suite(emb, coords2d, labels, tag_sets),
            }
            print(f"  {label}: {results['methods'][label]}")
        except Exception as e:
            print(f"  {label}: FAILED — {e}")
            results["methods"][label] = {"error": str(e)}

    return results


def main():
    all_results = {}
    for fname, cat in TARGETS:
        all_results[cat] = run_for_category(fname, cat)
    OUT_PATH.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved → {OUT_PATH}")
    # Compact table
    print("\n=== A/B comparison table ===")
    print(f"{'category':<20} {'method':<35} {'dim':>5} {'trust':>6} {'cont':>6} {'nbr':>6} {'expl':>6} {'DB':>6} {'sil':>6}")
    for cat, res in all_results.items():
        for m, vals in res["methods"].items():
            if "error" in vals:
                print(f"{cat:<20} {m:<35} ERROR: {vals['error'][:30]}")
                continue
            print(f"{cat:<20} {m:<35} {vals.get('dim',0):>5} "
                  f"{vals.get('trustworthiness','?'):>6} "
                  f"{vals.get('continuity','?'):>6} "
                  f"{vals.get('neighborhood_preservation','?'):>6} "
                  f"{vals.get('explainability','?'):>6} "
                  f"{vals.get('davies_bouldin','?'):>6} "
                  f"{vals.get('silhouette_2d','?'):>6}")


if __name__ == "__main__":
    main()
