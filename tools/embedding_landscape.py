"""
Tag extraction + embedding experiment for physics.comp-ph.
Step 1: Claude extracts structured tags from each paper's summary
Step 2: Tags are embedded and cosine similarity computed
Step 3: UMAP + clustering, added to the existing landscape JSON
"""
import asyncio, os, sys, json, uuid, numpy as np
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

CATEGORY = "physics.comp-ph"
SEED = 42
OPENAI_KEY = os.environ.get("OPENAI_API_KEY_GPT54")

TAG_PROMPT = """Extract structured tags from this research paper summary. Use established field terminology and canonical forms (e.g. "molecular dynamics" not "MD simulation", "density functional theory" not "DFT calculations").

Summary:
{summary}

Respond with JSON only:
{{"topics": ["molecular dynamics", "protein folding"], "methods": ["neural network potential", "coarse-graining"], "domains": ["biophysics"], "concepts": ["free energy", "conformational sampling"]}}

Rules:
- topics: 3-5 research topics (specific subfields)
- methods: 2-4 computational methods/algorithms used
- domains: 1-2 application domains
- concepts: 3-5 key scientific concepts"""

async def call_claude(prompt):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    try:
        chat = LlmChat(api_key=os.environ.get("EMERGENT_LLM_KEY"),
                        session_id=f"tg-{uuid.uuid4().hex[:8]}",
                        system_message="Extract structured tags. Respond JSON only."
                        ).with_model("anthropic", "claude-opus-4-6")
        r = await chat.send_message(UserMessage(text=prompt))
        t = r.strip()
        if t.startswith("```"): t = t.split("\n", 1)[-1]
        if t.endswith("```"): t = t[:-3].strip()
        if "{" in t: t = t[t.index("{"):t.rindex("}")+1]
        return json.loads(t)
    except Exception as e:
        print(f"  Tag error: {str(e)[:60]}")
        return None

async def embed_texts(texts, batch_size=50):
    import litellm
    embs = []
    for i in range(0, len(texts), batch_size):
        r = await litellm.aembedding(model="text-embedding-3-small", input=texts[i:i+batch_size], api_key=OPENAI_KEY)
        embs.extend([x["embedding"] for x in r.data])
    return np.array(embs)

async def run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    CK = "anthropic:claude-opus-4-6:thinking"

    # Load papers
    papers = []
    async for doc in db.papers.find(
        {"categories.0": CATEGORY, f"summaries.{CK}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CK}": 1}
    ).sort("published", -1):
        s = doc.get("summaries", {}).get(CK, "")
        if isinstance(s, str) and len(s) > 100:
            papers.append({"id": doc["id"], "title": doc["title"], "summary": s[:2000]})
    n = len(papers)
    print(f"{n} papers")

    # Step 1: Extract tags (with incremental save)
    partial = "/app/backend/data/precomputed/tags_physics_comp_ph.json"
    tags = {}
    if os.path.exists(partial):
        with open(partial) as f:
            tags = json.load(f)
        print(f"Resumed {len(tags)} tags from cache")

    sem = asyncio.Semaphore(3)
    completed = len(tags)

    async def extract_one(paper):
        nonlocal completed
        if paper["id"] in tags:
            return
        async with sem:
            prompt = TAG_PROMPT.format(summary=paper["summary"][:1500])
            result = await call_claude(prompt)
            completed += 1
            if result:
                tags[paper["id"]] = result
            if completed % 25 == 0:
                print(f"  Tags: {completed}/{n}")
                with open(partial, "w") as f:
                    json.dump(tags, f)

    remaining = [p for p in papers if p["id"] not in tags]
    print(f"\nExtracting tags: {len(remaining)} remaining...")
    await asyncio.gather(*[extract_one(p) for p in remaining])
    with open(partial, "w") as f:
        json.dump(tags, f)
    print(f"Tags extracted: {len(tags)}/{n}")

    # Step 2: Build tag strings and embed
    tag_texts = []
    for p in papers:
        t = tags.get(p["id"], {})
        parts = []
        for key in ["topics", "methods", "domains", "concepts"]:
            vals = t.get(key, [])
            if vals:
                parts.append(f"{key}: {', '.join(vals)}")
        tag_texts.append("; ".join(parts) if parts else p["title"])

    print(f"\nEmbedding {len(tag_texts)} tag strings...")
    tag_embs = await embed_texts(tag_texts)
    print(f"  Shape: {tag_embs.shape}")

    # Step 3: Cosine similarity + UMAP
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    import umap

    sim = cosine_similarity(tag_embs)
    dist = np.clip(1 - sim, 0, 2)
    np.fill_diagonal(dist, 0)
    tri = np.triu_indices(n, 1)
    print(f"Tag similarity: mean={sim[tri].mean():.3f} std={sim[tri].std():.3f}")

    print("\nUMAP from tag embeddings...")
    coords = umap.UMAP(metric="precomputed", n_neighbors=12, min_dist=0.5, spread=2.0, random_state=SEED).fit_transform(dist)
    coords -= coords.mean(0)
    s = max(coords[:, 0].max() - coords[:, 0].min(), coords[:, 1].max() - coords[:, 1].min())
    coords = coords / s * 100

    cl = {}; bk, bs = 3, -1
    for k in range(2, 11):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        lb = km.fit_predict(coords)
        cl[str(k)] = [int(x) for x in lb]
        sc = silhouette_score(coords, lb)
        if sc > bs: bk, bs = k, sc
        print(f"  K={k}: sil={sc:.3f}")
    cl["1"] = [0] * n

    # Step 4: Update landscape JSON
    out = "/app/backend/data/precomputed/similarity_landscape_physics_comp_ph.json"
    with open(out) as f:
        data = json.load(f)
    for i, p in enumerate(data["papers"]):
        p["x_emb_tags"] = float(coords[i][0])
        p["y_emb_tags"] = float(coords[i][1])
    data["emb_tags_cluster_labels"] = cl
    data["emb_tags_silhouette"] = round(bs, 3)
    data["emb_tags_best_k"] = bk
    data["has_tag_embeddings"] = True
    with open(out, "w") as f:
        json.dump(data, f)

    print(f"\n{'Method':<25} {'Best K':>7} {'Silhouette':>10}")
    print(f"{'LLM pairwise':<25} {data.get('n_clusters','?'):>7} {data.get('silhouette','?'):>10}")
    print(f"{'Abstract embed':<25} {data.get('emb_abstract_best_k','?'):>7} {data.get('emb_abstract_silhouette','?'):>10}")
    print(f"{'Summary+Abstract embed':<25} {data.get('emb_combined_best_k','?'):>7} {data.get('emb_combined_silhouette','?'):>10}")
    print(f"{'Tags embed':<25} {bk:>7} {bs:>10.3f}")

    # Show sample tags
    print("\nSample tags:")
    for p in papers[:3]:
        t = tags.get(p["id"], {})
        print(f"  {p['title'][:50]}:")
        for key in ["topics", "methods", "domains", "concepts"]:
            print(f"    {key}: {t.get(key, [])}")

if __name__ == "__main__":
    asyncio.run(run())
