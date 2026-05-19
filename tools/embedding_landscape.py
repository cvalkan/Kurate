"""Embedding experiment: abstract vs summary+abstract for physics.comp-ph"""
import asyncio, os, sys, json, numpy as np
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient
CATEGORY = "physics.comp-ph"
SEED = 42
OPENAI_KEY = os.environ.get("OPENAI_API_KEY_GPT54")
async def get_papers(db):
    CK = "anthropic:claude-opus-4-6:thinking"
    papers = []
    async for d in db.papers.find({"categories.0": CATEGORY, f"summaries.{CK}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CK}": 1, "published": 1}).sort("published", -1):
        s = d.get("summaries", {}).get(CK, "")
        if isinstance(s, str) and len(s) > 100:
            papers.append({"id": d["id"], "title": d["title"], "abstract": d.get("abstract", ""), "summary": s[:2000]})
    return papers
async def embed_texts(texts, bs=50):
    import litellm
    embs = []
    for i in range(0, len(texts), bs):
        r = await litellm.aembedding(model="text-embedding-3-small", input=texts[i:i+bs], api_key=OPENAI_KEY)
        embs.extend([x["embedding"] for x in r.data])
        print(f"  {len(embs)}/{len(texts)}")
    return np.array(embs)
async def run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    papers = await get_papers(db)
    n = len(papers)
    print(f"{n} papers")
    print("\nAbstract embeddings:")
    ea = await embed_texts([p["abstract"][:1500] for p in papers])
    print("\nSummary+Abstract embeddings:")
    eb = await embed_texts([f"{p['abstract'][:500]}\n\n{p['summary'][:1500]}" for p in papers])
    from sklearn.metrics.pairwise import cosine_similarity
    sa, sb = cosine_similarity(ea), cosine_similarity(eb)
    da, db2 = np.clip(1-sa, 0, 2), np.clip(1-sb, 0, 2)
    np.fill_diagonal(da, 0); np.fill_diagonal(db2, 0)
    t = np.triu_indices(n, 1)
    print(f"\nAbstract sim: mean={sa[t].mean():.3f} std={sa[t].std():.3f}")
    print(f"Combined sim: mean={sb[t].mean():.3f} std={sb[t].std():.3f}")
    import umap
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    res = {}
    for lb, dm in [("abstract", da), ("combined", db2)]:
        print(f"\nUMAP: {lb}")
        c = umap.UMAP(metric="precomputed", n_neighbors=12, min_dist=0.5, spread=2.0, random_state=SEED).fit_transform(dm)
        c -= c.mean(0); s = max(c[:, 0].max()-c[:, 0].min(), c[:, 1].max()-c[:, 1].min()); c = c / s * 100
        cl = {}; bk, bs = 3, -1
        for k in range(2, 11):
            km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
            l = km.fit_predict(c); cl[str(k)] = [int(x) for x in l]
            sc = silhouette_score(c, l)
            if sc > bs: bk, bs = k, sc
            print(f"  K={k}: sil={sc:.3f}")
        cl["1"] = [0]*n
        res[lb] = {"coords": c, "cl": cl, "bk": bk, "bs": round(bs, 3)}
    out = "/app/backend/data/precomputed/similarity_landscape_physics_comp_ph.json"
    with open(out) as f: data = json.load(f)
    for i, p in enumerate(data["papers"]):
        p["x_emb_abstract"] = float(res["abstract"]["coords"][i][0])
        p["y_emb_abstract"] = float(res["abstract"]["coords"][i][1])
        p["x_emb_combined"] = float(res["combined"]["coords"][i][0])
        p["y_emb_combined"] = float(res["combined"]["coords"][i][1])
    data["emb_abstract_cluster_labels"] = res["abstract"]["cl"]
    data["emb_combined_cluster_labels"] = res["combined"]["cl"]
    data["emb_abstract_silhouette"] = res["abstract"]["bs"]
    data["emb_combined_silhouette"] = res["combined"]["bs"]
    data["emb_abstract_best_k"] = res["abstract"]["bk"]
    data["emb_combined_best_k"] = res["combined"]["bk"]
    data["has_embeddings"] = True
    with open(out, "w") as f: json.dump(data, f)
    print(f"\n{'Method':<20} {'Best K':>7} {'Silhouette':>10}")
    print(f"{'LLM pairwise':<20} {data.get('n_clusters','?'):>7} {data.get('silhouette','?'):>10}")
    print(f"{'Abstract embed':<20} {res['abstract']['bk']:>7} {res['abstract']['bs']:>10.3f}")
    print(f"{'Summary+Abstract':<20} {res['combined']['bk']:>7} {res['combined']['bs']:>10.3f}")
if __name__ == "__main__":
    asyncio.run(run())
