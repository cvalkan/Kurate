"""Compute trust/continuity/neighborhood_preservation for EMBEDDING views.

Regenerates the high-D combined embedding (text + tags via OpenAI
text-embedding-3-large, averaged), caches it to .npz, then computes the three
neighborhood-fidelity metrics against the persisted 2D coords for the
`emb_combined_large` view in each landscape JSON.

This complements `compute_quality_metrics.py` (which can only compute
Davies-Bouldin and Explainability for embedding methods because the high-D
representation isn't stored).

Usage:
    python3 /app/tools/compute_quality_metrics_embeddings.py            # all
    python3 /app/tools/compute_quality_metrics_embeddings.py cs_GT
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

from pymongo import MongoClient
from sklearn.manifold import trustworthiness as sk_trustworthiness
from sklearn.neighbors import NearestNeighbors
from scipy.spatial.distance import pdist, squareform

OPENAI_KEY = os.environ.get("OPENAI_API_KEY_GPT54") or os.environ.get("OPENAI_API_KEY_DIRECT")
PRECOMPUTED_DIR = Path("/app/backend/data/precomputed")
CACHE_DIR = Path("/tmp/embedding_cache")
CACHE_DIR.mkdir(exist_ok=True)
CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
KNN = 10

# (landscape json, mongo category)
TARGETS = [
    ("similarity_landscape_cs_GT.json",         "cs.GT"),
    ("similarity_landscape_physics_comp_ph.json","physics.comp-ph"),
]


async def embed_texts(texts, model="text-embedding-3-large", batch_size=32):
    import litellm
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        r = await litellm.aembedding(model=model, input=chunk, api_key=OPENAI_KEY)
        out.extend([np.asarray(x["embedding"], dtype=np.float32) for x in r.data])
        print(f"    embedded {i + len(chunk)}/{len(texts)}")
    return np.vstack(out)


def flatten_tags(t):
    if isinstance(t, list):
        return list(t)
    if isinstance(t, dict):
        if isinstance(t.get("tags"), list):
            return list(t["tags"])
        out = []
        for k in ("topics", "methods", "domains", "concepts"):
            out.extend(t.get(k) or [])
        return out
    return []


async def get_or_build_embeddings(papers, category):
    """Returns N x D matrix matching `papers` order."""
    cache_path = CACHE_DIR / f"combined_large_{category.replace('.', '_')}.npz"
    ids = [p["id"] for p in papers]
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=True)
        cached_ids = cached["ids"].tolist()
        if cached_ids == ids:
            print(f"  Loaded cached embeddings: {cache_path.name}")
            return cached["combined"]
        print(f"  Cache id-mismatch — regenerating ({len(ids)} vs {len(cached_ids)})")

    # Fetch raw text from Mongo (abstract + Claude summary) and tags from the landscape JSON
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    docs = {}
    for d in db.papers.find(
        {"id": {"$in": ids}, f"summaries.{CLAUDE_KEY}": {"$exists": True}},
        {"_id": 0, "id": 1, "abstract": 1, f"summaries.{CLAUDE_KEY}": 1},
    ):
        s = (d.get("summaries") or {}).get(CLAUDE_KEY, "")
        docs[d["id"]] = (d.get("abstract") or "", s if isinstance(s, str) else "")

    text_inputs, tag_inputs = [], []
    for p in papers:
        abstract, summary = docs.get(p["id"], ("", ""))
        text_inputs.append(f"{abstract}\n\nAI Impact Assessment:\n{summary[:2000]}".strip())
        tags = p.get("tags_incremental") or p.get("tags") or {}
        tag_list = flatten_tags(tags)
        tag_inputs.append(", ".join(tag_list) if tag_list else "no tags")

    print(f"  Embedding {len(text_inputs)} text inputs (text-embedding-3-large)...")
    text_emb = await embed_texts(text_inputs)
    print(f"  Embedding {len(tag_inputs)} tag inputs...")
    tag_emb = await embed_texts(tag_inputs)
    combined = (text_emb + tag_emb) / 2.0
    np.savez_compressed(cache_path, ids=np.asarray(ids), combined=combined.astype(np.float32))
    print(f"  Cached → {cache_path.name}")
    return combined


def cosine_distance_matrix(emb):
    from sklearn.metrics.pairwise import cosine_similarity
    sim = cosine_similarity(emb)
    np.clip(sim, -1.0, 1.0, out=sim)
    dist = 1.0 - sim
    np.fill_diagonal(dist, 0.0)
    return dist.astype(np.float32)


def trust_continuity(dist_high, coords_2d, k=KNN):
    n = len(coords_2d)
    k = min(k, n - 1)
    trust = sk_trustworthiness(dist_high, coords_2d, n_neighbors=k, metric="precomputed")
    dist_low = squareform(pdist(coords_2d, metric="euclidean")).astype(np.float32)
    cont = sk_trustworthiness(dist_low, dist_high, n_neighbors=k, metric="precomputed")
    return float(trust), float(cont)


def knn_overlap(dist_high, coords_2d, k=KNN):
    n = len(coords_2d)
    k = min(k, n - 1)
    knn_high = np.argsort(dist_high, axis=1)[:, 1:k + 1]
    nn = NearestNeighbors(n_neighbors=k + 1, metric="euclidean").fit(coords_2d)
    knn_low = nn.kneighbors(coords_2d, return_distance=False)[:, 1:]
    return float(np.mean([len(set(knn_high[i]) & set(knn_low[i])) / k for i in range(n)]))


# Each entry: method_key -> (x_field, y_field). Compute against the
# `combined_large` embedding (which is what underlies these views in the
# precomputed pipeline — text + tag embeddings averaged).
EMBED_METHODS = {
    "emb_combined_large": ("x_emb_combined_large", "y_emb_combined_large"),
    "emb_abstract":       ("x_emb_abstract",       "y_emb_abstract"),
    "emb_combined":       ("x_emb_combined",       "y_emb_combined"),
    "emb_tags":           ("x_emb_tags",           "y_emb_tags"),
    "emb_tags_consolidated": ("x_emb_tags_consolidated", "y_emb_tags_consolidated"),
}


async def process(json_path, category):
    print(f"\n=== {json_path.name} ({category}) ===")
    data = json.loads(json_path.read_text())
    papers = data.get("papers") or []
    if not papers:
        print("  no papers")
        return

    high_d = await get_or_build_embeddings(papers, category)
    print(f"  High-D shape: {high_d.shape}")
    dist_high = cosine_distance_matrix(high_d)

    updated = False
    for method, (xf, yf) in EMBED_METHODS.items():
        if not all(xf in p for p in papers[:3]):
            continue
        coords = np.array([[float(p[xf]), float(p[yf])] for p in papers], dtype=np.float32)
        try:
            trust, cont = trust_continuity(dist_high, coords, k=KNN)
            nbp = knn_overlap(dist_high, coords, k=KNN)
            data[f"{method}_trustworthiness"] = round(trust, 3)
            data[f"{method}_continuity"] = round(cont, 3)
            data[f"{method}_neighborhood_preservation"] = round(nbp, 3)
            print(f"  {method}: trust={trust:.3f}, continuity={cont:.3f}, neighborhood_preservation={nbp:.3f}")
            updated = True
        except Exception as e:
            print(f"  {method}: failed — {e}")

    if updated:
        json_path.write_text(json.dumps(data))
        print(f"  saved {json_path.name}")


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for fname, cat in TARGETS:
        if target and target not in fname:
            continue
        path = PRECOMPUTED_DIR / fname
        if not path.exists():
            print(f"skip (missing): {path}")
            continue
        await process(path, cat)


if __name__ == "__main__":
    if not OPENAI_KEY:
        print("ERROR: OPENAI_API_KEY_GPT54 or OPENAI_API_KEY_DIRECT not set")
        sys.exit(1)
    asyncio.run(main())
