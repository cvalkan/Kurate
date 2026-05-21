"""Add SciNCL and SPECTER embedding views to the Similarity Landscape JSONs.

Embeds the same text inputs used by the OpenAI emb_combined_large pipeline
(title + abstract + Claude Opus 4.6 summary). For each new method we persist:
  - per-paper `x_emb_<method>`, `y_emb_<method>` coords (2D UMAP)
  - `<method>_cluster_labels` dict keyed by K (HDBSCAN + KMeans at K=3,5,7,10)
  - `<method>_best_k`, `<method>_silhouette`, `<method>_n_clusters`, `<method>_noise`
  - `<method>_trustworthiness`, `<method>_continuity`, `<method>_neighborhood_preservation`,
    `<method>_explainability`, `<method>_davies_bouldin`
  - `has_emb_<method> = True`
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

MODELS = [
    ("scincl",  "malteos/scincl"),
    ("specter", "allenai/specter"),
]


def flatten_tags(t):
    if isinstance(t,list): return list(t)
    if isinstance(t,dict):
        if isinstance(t.get("tags"),list): return list(t["tags"])
        out=[]
        for k in ("topics","methods","domains","concepts"): out.extend(t.get(k) or [])
        return out
    return []


def fetch_text(papers):
    cli = MongoClient(os.environ["MONGO_URL"]); db = cli[os.environ["DB_NAME"]]
    ids = [p["id"] for p in papers]
    docs = {}
    for d in db.papers.find({"id":{"$in":ids}, f"summaries.{SUMMARY_KEY}":{"$exists":True}},
                            {"_id":0,"id":1,"title":1,"abstract":1,f"summaries.{SUMMARY_KEY}":1}):
        s = (d.get("summaries") or {}).get(SUMMARY_KEY) or ""
        docs[d["id"]] = {"title": d.get("title",""), "abstract": d.get("abstract",""), "summary": s if isinstance(s,str) else ""}
    return [docs.get(p["id"], {"title":p.get("title",""),"abstract":"","summary":""}) for p in papers]


def embed_st(model_id, sentences):
    from sentence_transformers import SentenceTransformer
    print(f"  Loading {model_id}...")
    model = SentenceTransformer(model_id, cache_folder="/opt/hf_cache")
    model.max_seq_length = 512
    print(f"  Encoding {len(sentences)} inputs...")
    return model.encode(sentences, batch_size=16, show_progress_bar=False,
                        convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)


def cosine_dist(emb):
    sim = cosine_similarity(emb); np.clip(sim,-1,1,out=sim)
    d = (1.0 - sim).astype(np.float32); np.fill_diagonal(d,0.0); return d


def reduce_cluster(emb):
    n = len(emb); nn = min(15, n-1)
    high = umap.UMAP(n_components=40, n_neighbors=nn, min_dist=0.0,
                     metric="cosine", random_state=SEED).fit_transform(emb)
    min_size = max(5, n//30)
    hdb = hdbscan.HDBSCAN(min_cluster_size=min_size, min_samples=1, metric="euclidean")
    hdb_labels = hdb.fit_predict(high)
    coords2d = umap.UMAP(n_components=2, n_neighbors=nn, min_dist=0.08,
                         metric="cosine", random_state=SEED).fit_transform(emb)
    # K-means at K=2..10 for cluster selector
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
    knn_high = np.argsort(dist_high, axis=1)[:, 1:KNN+1]
    nn = NearestNeighbors(n_neighbors=KNN+1, metric="euclidean").fit(coords2d)
    knn_low = nn.kneighbors(coords2d, return_distance=False)[:, 1:]
    nbr = float(np.mean([len(set(knn_high[i]) & set(knn_low[i])) / KNN for i in range(len(emb))]))
    idxs = knn_low
    expl_vals = [sum(1 for j in idxs[i] if tag_sets[j] & tag_sets[i]) / KNN
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
        "trustworthiness": round(trust,3),
        "continuity": round(cont,3),
        "neighborhood_preservation": round(nbr,3),
        "explainability": round(expl,3) if expl is not None else None,
        "davies_bouldin": round(db_val,3) if db_val is not None else None,
        "silhouette": round(sil,3) if sil is not None else None,
        "n_clusters": int(len(set(labels[valid]))) if valid.any() else 0,
        "noise": int((labels==-1).sum()),
    }


def process(json_name, category):
    print(f"\n=== {category} ===")
    path = PRECOMPUTED / json_name
    data = json.loads(path.read_text())
    papers = data["papers"]
    text_meta = fetch_text(papers)
    text_inputs = [f"{x['title']}. {x['abstract']}\n\nImpact: {x['summary'][:1500]}".strip() for x in text_meta]
    tag_sets = [set(flatten_tags(p.get("tags_incremental") or p.get("tags") or {})) for p in papers]

    for short, hf_id in MODELS:
        method = f"emb_{short}"
        print(f"\n  -- {method} --")
        emb = embed_st(hf_id, text_inputs)
        coords2d, hdb_labels, kmeans_labels, sil_per_k = reduce_cluster(emb)
        # Write coords per paper
        for i,p in enumerate(papers):
            p[f"x_{method}"] = float(coords2d[i,0])
            p[f"y_{method}"] = float(coords2d[i,1])
        # cluster labels — HDBSCAN under key "hdbscan", K-means under K
        label_dict = {"hdbscan": [int(x) for x in hdb_labels]}
        label_dict.update(kmeans_labels)
        data[f"{method}_cluster_labels"] = label_dict
        data[f"{method}_kmeans_silhouettes"] = sil_per_k
        # Best K = HDBSCAN n_clusters (excluding noise)
        valid = hdb_labels[hdb_labels >= 0]
        best_k = int(len(set(valid.tolist()))) if len(valid) else 3
        data[f"{method}_best_k"] = best_k
        # Compute all metrics on HDBSCAN labels
        m = metric_suite(emb, coords2d, hdb_labels, tag_sets)
        for k,v in m.items():
            data[f"{method}_{k}"] = v
        data[f"has_{method}"] = True
        # Store silhouettes_per_k entry for the UI's per-K cluster selector
        data.setdefault("silhouettes_per_k", {})[method] = sil_per_k
        print(f"  {method}: trust={m['trustworthiness']} cont={m['continuity']} nbr={m['neighborhood_preservation']} expl={m['explainability']} sil={m['silhouette']} K={best_k}")

    path.write_text(json.dumps(data))
    print(f"\n  saved {path.name}")


if __name__ == "__main__":
    os.makedirs("/opt/hf_cache", exist_ok=True)
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for fname, cat in TARGETS:
        if target and target not in fname: continue
        process(fname, cat)
