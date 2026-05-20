"""Compute map-quality metrics for every method in similarity_landscape_*.json.

Metrics persisted (per method, keyed as `{method}_<metric>`):
  - trustworthiness          (sklearn.manifold.trustworthiness, n_neighbors=10)
  - continuity               (reverse trustworthiness)
  - neighborhood_preservation (avg KNN overlap, k=10)
  - explainability           (avg fraction of 2D-neighbors sharing >=1 tag, k=10)
  - davies_bouldin           (sklearn.metrics.davies_bouldin_score on best-K labels)

For Jaccard-based methods we can reconstruct the high-D feature matrix from
the per-paper tag lists. Embedding methods (e.g. emb_combined_large) don't
persist raw embeddings, so we only compute davies_bouldin + explainability.

Usage:
    python3 /app/tools/compute_quality_metrics.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.manifold import trustworthiness as sk_trustworthiness
from sklearn.metrics import davies_bouldin_score
from sklearn.neighbors import NearestNeighbors

PRECOMPUTED_DIR = Path("/app/backend/data/precomputed")
FILES = [
    PRECOMPUTED_DIR / "similarity_landscape.json",
    PRECOMPUTED_DIR / "similarity_landscape_cs_GT.json",
    PRECOMPUTED_DIR / "similarity_landscape_physics_comp_ph.json",
]
KNN = 10  # neighborhood size for all neighborhood-based metrics


# ---------- helpers ---------------------------------------------------------
def paper_tag_set(paper):
    """Flatten a paper's tag dict / list into a single set of strings."""
    t = paper.get("tags") or {}
    if isinstance(t, list):
        return set(t)
    if isinstance(t, dict):
        if isinstance(t.get("tags"), list):
            return set(t["tags"])
        out = set()
        for key in ("topics", "methods", "domains", "concepts"):
            out.update(t.get(key) or [])
        return out
    return set()


def paper_tags_incremental(paper):
    """Incremental-vocabulary tags (used by Jaccard methods if present)."""
    t = paper.get("tags_incremental")
    if not t:
        return paper_tag_set(paper)
    if isinstance(t, list):
        return set(t)
    if isinstance(t, dict):
        out = set()
        for key in ("topics", "methods", "domains", "concepts"):
            out.update(t.get(key) or [])
        if not out and isinstance(t.get("tags"), list):
            out.update(t["tags"])
        return out
    return set()


def build_binary_matrix(papers, vocab, get_tags):
    """N x V binary matrix; rows=papers, cols=vocab. Returns dense float32."""
    v_idx = {t: i for i, t in enumerate(vocab)}
    mat = np.zeros((len(papers), len(vocab)), dtype=np.float32)
    for i, p in enumerate(papers):
        for t in get_tags(p):
            j = v_idx.get(t)
            if j is not None:
                mat[i, j] = 1.0
    return mat


def jaccard_distance_matrix(binary):
    """Pairwise Jaccard distance. binary is float32 0/1."""
    # |A ∩ B| via matrix product
    inter = binary @ binary.T
    sums = binary.sum(axis=1, keepdims=True)
    union = sums + sums.T - inter
    # Avoid div by zero — set distance=1 for empty unions
    with np.errstate(divide="ignore", invalid="ignore"):
        sim = np.where(union > 0, inter / union, 0.0)
    dist = 1.0 - sim
    np.fill_diagonal(dist, 0.0)
    return dist.astype(np.float32)


def trust_continuity(dist_high, coords_2d, k=KNN):
    """Trustworthiness (using sklearn) + manual continuity using rank-based defs."""
    n = len(coords_2d)
    k = min(k, n - 1)
    # Trustworthiness: how many close-in-low were also close-in-high
    trust = sk_trustworthiness(dist_high, coords_2d, n_neighbors=k, metric="precomputed")

    # Continuity (reverse): close-in-high should remain close-in-low
    # We compute it as the trustworthiness of the inverse mapping.
    # Equivalent formulation: build 2D pairwise distance, then call sklearn
    # again with roles swapped.
    from scipy.spatial.distance import pdist, squareform
    dist_low = squareform(pdist(coords_2d, metric="euclidean")).astype(np.float32)
    cont = sk_trustworthiness(dist_low, dist_high, n_neighbors=k, metric="precomputed")
    return float(trust), float(cont)


def knn_overlap(dist_high, coords_2d, k=KNN):
    """Avg overlap between top-k neighbors in high-D vs 2D (0..1)."""
    n = len(coords_2d)
    k = min(k, n - 1)
    # Top-k indices (excluding self) in high-D
    knn_high = np.argsort(dist_high, axis=1)[:, 1 : k + 1]
    nn = NearestNeighbors(n_neighbors=k + 1, metric="euclidean").fit(coords_2d)
    knn_low = nn.kneighbors(coords_2d, return_distance=False)[:, 1:]
    overlaps = []
    for i in range(n):
        overlaps.append(len(set(knn_high[i]) & set(knn_low[i])) / k)
    return float(np.mean(overlaps))


def explainability(coords_2d, tag_sets, k=KNN):
    """Avg fraction of 2D nearest-neighbors that share ≥1 tag with the anchor."""
    n = len(coords_2d)
    k = min(k, n - 1)
    if k == 0:
        return None
    nn = NearestNeighbors(n_neighbors=k + 1, metric="euclidean").fit(coords_2d)
    idxs = nn.kneighbors(coords_2d, return_distance=False)[:, 1:]
    scores = []
    for i in range(n):
        anchor = tag_sets[i]
        if not anchor:
            continue
        shared = sum(1 for j in idxs[i] if tag_sets[j] & anchor)
        scores.append(shared / k)
    return float(np.mean(scores)) if scores else None


def db_score(coords_2d, labels):
    """Davies-Bouldin requires ≥2 clusters and ≥1 sample per cluster."""
    labels = np.asarray(labels)
    valid_mask = labels >= 0  # ignore HDBSCAN noise (-1)
    if valid_mask.sum() < 3:
        return None
    uniq = np.unique(labels[valid_mask])
    if len(uniq) < 2:
        return None
    try:
        return float(davies_bouldin_score(coords_2d[valid_mask], labels[valid_mask]))
    except Exception:
        return None


# ---------- per-method drivers ---------------------------------------------
METHOD_COORDS = {
    # method_key: (x_field, y_field, labels_field_template_or_const)
    "mds":                 ("x", "y", "cluster_labels"),
    "umap":                ("x_umap", "y_umap", "umap_cluster_labels"),
    "emb_abstract":        ("x_emb_abstract", "y_emb_abstract", "emb_abstract_cluster_labels"),
    "emb_combined":        ("x_emb_combined", "y_emb_combined", "emb_combined_cluster_labels"),
    "emb_tags":            ("x_emb_tags", "y_emb_tags", "emb_tags_cluster_labels"),
    "emb_tags_consolidated":("x_emb_tags_consolidated", "y_emb_tags_consolidated", "emb_tags_consolidated_cluster_labels"),
    "emb_combined_large":  ("x_emb_combined_large", "y_emb_combined_large", "emb_combined_large_cluster_labels"),
    "jaccard_incr":        ("x_jaccard_incr", "y_jaccard_incr", "jaccard_incr_cluster_labels"),
    "jaccard_topics":      ("x_jaccard_topics", "y_jaccard_topics", "jaccard_topics_cluster_labels"),
    "jaccard_methods":     ("x_jaccard_methods", "y_jaccard_methods", "jaccard_methods_cluster_labels"),
    "jaccard_domains":     ("x_jaccard_domains", "y_jaccard_domains", "jaccard_domains_cluster_labels"),
    "jaccard_concepts":    ("x_jaccard_concepts", "y_jaccard_concepts", "jaccard_concepts_cluster_labels"),
    "jaccard_laplacian":   ("x_jaccard_laplacian", "y_jaccard_laplacian", "jaccard_laplacian_cluster_labels"),
    "jaccard_lap14":       ("x_jaccard_lap14", "y_jaccard_lap14", "jaccard_lap14_cluster_labels"),
    "jaccard_lap10":       ("x_jaccard_lap10", "y_jaccard_lap10", "jaccard_lap10_cluster_labels"),
    "jaccard_stable":      ("x_jaccard_stable", "y_jaccard_stable", "jaccard_stable_cluster_labels"),
    "jaccard_ce":          ("x_jaccard_ce", "y_jaccard_ce", "jaccard_ce_cluster_labels"),
    "jaccard_ce10":        ("x_jaccard_ce10", "y_jaccard_ce10", "jaccard_ce10_cluster_labels"),
    "jaccard_pmi50":       ("x_jaccard_pmi50", "y_jaccard_pmi50", "jaccard_pmi50_cluster_labels"),
    "jaccard_pmi60":       ("x_jaccard_pmi60", "y_jaccard_pmi60", "jaccard_pmi60_cluster_labels"),
    "jaccard_all":         ("x_jaccard_all", "y_jaccard_all", "jaccard_all_cluster_labels"),
}

# Tag-set field per method (used to reconstruct high-D Jaccard matrix).
# None means "use raw tag list (all tags)" — for jaccard_all / jaccard_incr.
JACCARD_VOCAB = {
    "jaccard_all":      None,                 # all incremental tags
    "jaccard_incr":     None,
    "jaccard_topics":   ("tags_incremental", "topics"),
    "jaccard_methods":  ("tags_incremental", "methods"),
    "jaccard_domains":  ("tags_incremental", "domains"),
    "jaccard_concepts": ("tags_incremental", "concepts"),
    "jaccard_laplacian":("laplacian100_tag_set",),
    "jaccard_lap14":    ("laplacian14_tag_set",),
    "jaccard_lap10":    ("lap10_tag_set",),
    "jaccard_stable":   ("stable_tag_set",),
    "jaccard_ce":       ("ce_tag_set",),
    "jaccard_ce10":     ("ce10_tag_set",),
    "jaccard_pmi50":    ("pmi50_tag_set",),
    "jaccard_pmi60":    ("pmi60_tag_set",),
}


def process_method(data, method, papers, coords, labels, tag_sets):
    """Returns dict of computed metrics (only successful ones)."""
    out = {}
    # Davies-Bouldin always doable if we have labels + coords
    if labels is not None:
        db = db_score(coords, labels)
        if db is not None:
            out[f"{method}_davies_bouldin"] = round(db, 3)

    # Explainability: 2D + tag sets (raw, not filtered)
    expl = explainability(coords, tag_sets, k=KNN)
    if expl is not None:
        out[f"{method}_explainability"] = round(expl, 3)

    # High-D reconstruction is only possible for Jaccard methods
    if method.startswith("jaccard"):
        spec = JACCARD_VOCAB.get(method)
        # Pick vocabulary
        if spec is None:
            # Union of all tags (per-paper)
            vocab = sorted({t for ts in tag_sets for t in ts})
            getter = lambda p, idx=None: tag_sets[papers.index(p)] if isinstance(p, dict) else set()
        elif len(spec) == 1:
            vocab = list(data.get(spec[0]) or [])
            vocab_set = set(vocab)
            getter = lambda p: tag_sets[papers.index(p)] & vocab_set
        else:  # tag_field, category
            field, cat = spec
            cat_tags = set()
            for p in papers:
                cat_tags.update(((p.get(field) or {}).get(cat) or []))
            vocab = sorted(cat_tags)
            vocab_set = set(vocab)
            getter = lambda p, c=cat, f=field: set(((p.get(f) or {}).get(c) or [])) & vocab_set

        if vocab:
            binary = build_binary_matrix(papers, vocab, getter)
            if binary.sum() > 0:
                dist_high = jaccard_distance_matrix(binary)
                try:
                    trust, cont = trust_continuity(dist_high, coords, k=KNN)
                    out[f"{method}_trustworthiness"] = round(trust, 3)
                    out[f"{method}_continuity"] = round(cont, 3)
                except Exception as e:
                    print(f"    trust/cont failed for {method}: {e}")
                try:
                    nbp = knn_overlap(dist_high, coords, k=KNN)
                    out[f"{method}_neighborhood_preservation"] = round(nbp, 3)
                except Exception as e:
                    print(f"    knn_overlap failed for {method}: {e}")
    return out


def process_file(path):
    print(f"\n=== {path.name} ===")
    data = json.loads(path.read_text())
    papers = data.get("papers") or []
    if not papers:
        print("  no papers — skipping")
        return
    # Pre-compute tag sets (incremental preferred)
    tag_sets = [paper_tags_incremental(p) for p in papers]

    for method, (x_field, y_field, labels_field) in METHOD_COORDS.items():
        if not all(x_field in p for p in papers[:3]):
            # Coords not present — skip
            continue
        coords = np.array([[float(p[x_field]), float(p[y_field])] for p in papers], dtype=np.float32)

        # Labels: prefer pre-stored per-K labels at best_k
        best_k = data.get(f"{method}_best_k") or data.get("n_clusters")
        label_dict = data.get(labels_field) or {}
        labels = label_dict.get(str(best_k)) if isinstance(label_dict, dict) else None
        if labels is None:
            # fall back to per-paper "cluster" field for default method
            if method in ("mds", "umap"):
                labels = [p.get("cluster") for p in papers]
            elif method == "emb_combined_large":
                labels = [p.get("hdbscan_label") for p in papers]
        if labels is None or any(l is None for l in labels):
            labels = None

        print(f"  {method}: computing (best_k={best_k})...")
        metrics = process_method(data, method, papers, coords, labels, tag_sets)
        if metrics:
            print(f"    -> {metrics}")
            data.update(metrics)

    path.write_text(json.dumps(data))
    print(f"  saved {path.name}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for f in FILES:
        if target and target not in f.name:
            continue
        if not f.exists():
            print(f"skip (missing): {f}")
            continue
        process_file(f)
