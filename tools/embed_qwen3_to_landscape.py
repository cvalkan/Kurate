"""Add Qwen3-Embedding-0.6B views to the Similarity Landscape JSONs.

Embeds the same text inputs used by the OpenAI emb_combined_large pipeline
(title + abstract + Claude Opus 4.6 summary). Persists:
  - per-paper `x_emb_qwen3`, `y_emb_qwen3` coords (2D UMAP)
  - `emb_qwen3_cluster_labels` dict keyed by K (HDBSCAN + KMeans at K=2..10)
  - `emb_qwen3_best_k`, `emb_qwen3_silhouette`, etc.
  - quality metrics: trustworthiness, continuity, neighborhood_preservation,
    explainability, davies_bouldin
  - `has_emb_qwen3 = True`

Usage:
    python3 /app/tools/embed_qwen3_to_landscape.py            # all categories
    python3 /app/tools/embed_qwen3_to_landscape.py cs_GT      # single
"""
import os, json, sys
from pathlib import Path
import numpy as np
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

from pymongo import MongoClient
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.cluster import KMeans
from sklearn.manifold import trustworthiness as sk_trustworthiness
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics.pairwise import cosine_similarity
from scipy.spatial.distance import pdist, squareform
import umap, hdbscan

SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
SEED = 42
KNN = 10

TARGETS = [
    ("similarity_landscape_cs_GT.json",          "cs.GT"),
    ("similarity_landscape_physics_comp_ph.json","physics.comp-ph"),
]
PRECOMPUTED = Path("/app/backend/data/precomputed")

MODEL_HF = "Qwen/Qwen3-Embedding-0.6B"
METHOD = "emb_qwen3"


def flatten_tags(t):
    if isinstance(t, list): return list(t)
    if isinstance(t, dict):
        if isinstance(t.get("tags"), list): return list(t["tags"])
        out = []
        for k in ("topics", "methods", "domains", "concepts"): out.extend(t.get(k) or [])
        return out
    return []


def fetch_text(papers):
    cli = MongoClient(os.environ["MONGO_URL"]); db = cli[os.environ["DB_NAME"]]
    ids = [p["id"] for p in papers]
    docs = {}
    for d in db.papers.find({"id": {"$in": ids}, f"summaries.{SUMMARY_KEY}": {"$exists": True}},
                            {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{SUMMARY_KEY}": 1}):
        s = (d.get("summaries") or {}).get(SUMMARY_KEY) or ""
        docs[d["id"]] = {"title": d.get("title", ""), "abstract": d.get("abstract", ""), "summary": s if isinstance(s, str) else ""}
    return [docs.get(p["id"], {"title": p.get("title", ""), "abstract": "", "summary": ""}) for p in papers]


def embed_qwen3(sentences):
    from sentence_transformers import SentenceTransformer
    print(f"  Loading {MODEL_HF}...")
    model = SentenceTransformer(MODEL_HF, cache_folder="/opt/hf_cache")
    model.max_seq_length = 512
    print(f"  Encoding {len(sentences)} inputs...")
    return model.encode(sentences, batch_size=8, show_progress_bar=True,
                        convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)


def cosine_dist(emb):
    sim = cosine_similarity(emb); np.clip(sim, -1, 1, out=sim)
    d = (1.0 - sim).astype(np.float32); np.fill_diagonal(d, 0.0); return d


def reduce_cluster(emb):
    n = len(emb); nn = min(15, n - 1)
    high = umap.UMAP(n_components=40, n_neighbors=nn, min_dist=0.0,
                     metric="cosine", random_state=SEED).fit_transform(emb)
    min_size = max(5, n // 30)
    hdb = hdbscan.HDBSCAN(min_cluster_size=min_size, min_samples=1, metric="euclidean")
    hdb_labels = hdb.fit_predict(high)
    coords2d = umap.UMAP(n_components=2, n_neighbors=nn, min_dist=0.08,
                         metric="cosine", random_state=SEED).fit_transform(emb)
    kmeans_labels = {}
    sil_per_k = {}
    for k in range(2, 11):
        if k >= n: continue
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit(coords2d)
        kmeans_labels[str(k)] = km.labels_.tolist()
        try: sil_per_k[str(k)] = round(float(silhouette_score(coords2d, km.labels_)), 3)
        except Exception: sil_per_k[str(k)] = 0.0
    return coords2d, hdb_labels, kmeans_labels, sil_per_k


def metric_suite(emb, coords2d, labels, tag_sets):
    dist_high = cosine_dist(emb)
    trust = float(sk_trustworthiness(dist_high, coords2d, n_neighbors=KNN, metric="precomputed"))
    dist_low = squareform(pdist(coords2d, metric="euclidean")).astype(np.float32)
    cont = float(sk_trustworthiness(dist_low, dist_high, n_neighbors=KNN, metric="precomputed"))
    knn_high = np.argsort(dist_high, axis=1)[:, 1:KNN + 1]
    nn_model = NearestNeighbors(n_neighbors=KNN + 1, metric="euclidean").fit(coords2d)
    knn_low = nn_model.kneighbors(coords2d, return_distance=False)[:, 1:]
    nbr = float(np.mean([len(set(knn_high[i]) & set(knn_low[i])) / KNN for i in range(len(emb))]))
    expl_vals = [sum(1 for j in knn_low[i] if tag_sets[j] & tag_sets[i]) / KNN
                 for i in range(len(emb)) if tag_sets[i]]
    expl = float(np.mean(expl_vals)) if expl_vals else None
    valid = labels >= 0
    db_val = sil = None
    if valid.sum() >= 3 and len(set(labels[valid])) >= 2:
        try: db_val = float(davies_bouldin_score(coords2d[valid], labels[valid]))
        except Exception: pass
        try: sil = float(silhouette_score(coords2d[valid], labels[valid]))
        except Exception: pass
    return {
        "trustworthiness": round(trust, 3),
        "continuity": round(cont, 3),
        "neighborhood_preservation": round(nbr, 3),
        "explainability": round(expl, 3) if expl is not None else None,
        "davies_bouldin": round(db_val, 3) if db_val is not None else None,
        "silhouette": round(sil, 3) if sil is not None else None,
        "n_clusters": int(len(set(labels[valid]))) if valid.any() else 0,
        "noise": int((labels == -1).sum()),
    }


def process(json_name, category):
    print(f"\n=== {category} ({METHOD}) ===")
    path = PRECOMPUTED / json_name
    data = json.loads(path.read_text())
    papers = data["papers"]
    text_meta = fetch_text(papers)
    text_inputs = [f"{x['title']}. {x['abstract']}\n\nImpact: {x['summary'][:1500]}".strip() for x in text_meta]
    tag_sets = [set(flatten_tags(p.get("tags_incremental") or p.get("tags") or {})) for p in papers]

    print(f"\n  -- {METHOD} --")
    emb = embed_qwen3(text_inputs)
    coords2d, hdb_labels, kmeans_labels, sil_per_k = reduce_cluster(emb)

    # Write coords per paper
    for i, p in enumerate(papers):
        p[f"x_{METHOD}"] = float(coords2d[i, 0])
        p[f"y_{METHOD}"] = float(coords2d[i, 1])

    # cluster labels — HDBSCAN under key "hdbscan", K-means under K
    label_dict = {"hdbscan": [int(x) for x in hdb_labels]}
    label_dict.update(kmeans_labels)
    data[f"{METHOD}_cluster_labels"] = label_dict
    data[f"{METHOD}_kmeans_silhouettes"] = sil_per_k

    # Best K = K with highest 2D K-means silhouette (matching the fix for SciNCL/SPECTER)
    if sil_per_k:
        best_k = int(max(sil_per_k, key=lambda k: sil_per_k[k]))
    else:
        best_k = 3
    data[f"{METHOD}_best_k"] = best_k

    # Compute metrics on HDBSCAN labels
    m = metric_suite(emb, coords2d, hdb_labels, tag_sets)
    for k, v in m.items():
        data[f"{METHOD}_{k}"] = v
    data[f"has_{METHOD}"] = True

    # Store silhouettes_per_k entry for the UI's per-K cluster selector
    data.setdefault("silhouettes_per_k", {})[METHOD] = sil_per_k

    print(f"  {METHOD}: trust={m['trustworthiness']} cont={m['continuity']} nbr={m['neighborhood_preservation']} expl={m['explainability']} sil={m['silhouette']} best_k={best_k}")

    path.write_text(json.dumps(data))
    print(f"\n  saved {path.name}")


if __name__ == "__main__":
    os.makedirs("/opt/hf_cache", exist_ok=True)
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for fname, cat in TARGETS:
        if target and target not in fname: continue
        process(fname, cat)
