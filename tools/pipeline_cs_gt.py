"""
Full atomic pipeline for cs.GT similarity landscape.
Sequential incremental tag extraction → Laplacian → Procrustes stability → UMAP → cluster → titles.
"""
import asyncio, os, sys, json, uuid, numpy as np, time as _time
from collections import defaultdict, Counter
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

CATEGORY = "cs.GT"
SEED = 42
TAGS_PATH = "/app/backend/data/precomputed/tags_incremental_cs_GT.json"
OUT_PATH = "/app/backend/data/precomputed/similarity_landscape_cs_GT.json"

TAG_PROMPT = """Extract 8-10 descriptive tags for this research paper. Include research topics, methods, application domains, and key concepts as a single flat list. Use established terminology. Reuse existing tags from the vocabulary below where suitable. Only create new tags when no existing tag fits.

Current vocabulary:
{vocabulary}

Summary:
{summary}

Respond with JSON only: {{"tags": ["game theory", "mechanism design", "auction theory"]}}"""

TITLE_PROMPT = """Below are paper abstracts from {n_clusters} different clusters. Generate a short (2-5 word) DISTINGUISHING theme label for Cluster {cluster_num}.

{all_clusters_text}

Focus on what makes Cluster {cluster_num} UNIQUE. Avoid generic labels.
Respond with JSON only: {{"title": "Mechanism Design"}}"""


async def call_claude(prompt, system_msg="JSON only.", retries=2):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    for attempt in range(retries + 1):
        try:
            chat = LlmChat(api_key=os.environ.get("EMERGENT_LLM_KEY"),
                           session_id=f"gt-{uuid.uuid4().hex[:8]}",
                           system_message=system_msg
                           ).with_model("anthropic", "claude-opus-4-6")
            r = await chat.send_message(UserMessage(text=prompt))
            t = r.strip()
            if t.startswith("```"): t = t.split("\n", 1)[-1]
            if t.endswith("```"): t = t[:-3].strip()
            if "{" in t: t = t[t.index("{"):t.rindex("}") + 1]
            return json.loads(t)
        except:
            if attempt < retries: await asyncio.sleep(2)
    return None


async def run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    CK = "anthropic:claude-opus-4-6:thinking"

    # Load papers
    papers = []
    async for doc in db.papers.find(
        {"categories.0": CATEGORY, f"summaries.{CK}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CK}": 1, "published": 1, "arxiv_id": 1},
    ).sort("published", -1):
        s = doc.get("summaries", {}).get(CK, "")
        if isinstance(s, str) and len(s) > 100:
            papers.append({"id": doc["id"], "title": doc["title"], "abstract": doc.get("abstract", ""),
                           "summary": s[:2000], "published": doc.get("published", ""), "arxiv_id": doc.get("arxiv_id", "")})
    n = len(papers)
    print(f"Step 0: {n} {CATEGORY} papers loaded")

    # Get scores
    scores = {}
    async for doc in db.rankings.find({"category": CATEGORY}, {"_id": 0, "paper_id": 1, "ts_score": 1, "score": 1}):
        scores[doc["paper_id"]] = doc.get("ts_score") or doc.get("score", 1200)

    # ========== STEP 1: Incremental tag extraction ==========
    print("\nStep 1: Incremental tag extraction (sequential)...")
    t0 = _time.time()
    
    all_tags = {}
    processed_order = []
    if os.path.exists(TAGS_PATH):
        with open(TAGS_PATH) as f:
            saved = json.load(f)
        all_tags = saved.get("tags", {})
        processed_order = saved.get("order", [])
        print(f"  Resumed {len(all_tags)} papers from cache")

    import random
    random.seed(SEED)
    if not processed_order:
        order = list(range(n))
        random.shuffle(order)
    else:
        done_ids = set(processed_order)
        order = [i for i in range(n) if papers[i]["id"] not in done_ids]

    def build_vocab(tags_dict):
        all_t = set()
        for t in tags_dict.values():
            all_t.update(t.get("tags", []))
        return sorted(all_t)

    for step, idx in enumerate(order):
        p = papers[idx]
        if p["id"] in all_tags:
            continue
        vocab = build_vocab(all_tags)
        vocab_str = ", ".join(vocab) if vocab else "(none yet — create new tags as needed)"
        prompt = TAG_PROMPT.format(vocabulary=vocab_str, summary=p["summary"][:1500])
        result = await call_claude(prompt, "Extract tags. Reuse vocabulary. JSON only.")
        if result and "tags" in result:
            # Deduplicate
            seen = set()
            deduped = []
            for tag in result["tags"]:
                if tag not in seen:
                    seen.add(tag)
                    deduped.append(tag)
            all_tags[p["id"]] = {"tags": deduped}
            processed_order.append(p["id"])
        completed = len(all_tags)
        if completed % 25 == 0:
            unique = len(set(tag for t in all_tags.values() for tag in t.get("tags", [])))
            elapsed = _time.time() - t0
            print(f"  {completed}/{n} papers, {unique} unique tags ({elapsed:.0f}s)")
            with open(TAGS_PATH, "w") as f:
                json.dump({"tags": all_tags, "order": processed_order}, f)

    with open(TAGS_PATH, "w") as f:
        json.dump({"tags": all_tags, "order": processed_order}, f)
    
    unique_tags = set(tag for t in all_tags.values() for tag in t.get("tags", []))
    print(f"  Done: {len(all_tags)} papers, {len(unique_tags)} unique tags ({_time.time()-t0:.0f}s)")

    # ========== STEP 2: Build tag matrix ==========
    print("\nStep 2: Building tag matrix...")
    paper_tag_sets = []
    tag_freq = Counter()
    for p in papers:
        t = all_tags.get(p["id"], {})
        s = set(t.get("tags", []))
        paper_tag_sets.append(s)
        tag_freq.update(s)

    vocab = sorted(tag_freq.keys())
    V = len(vocab)
    td = np.zeros((n, V))
    for i, ts in enumerate(paper_tag_sets):
        for t in ts:
            td[i, vocab.index(t)] = 1
    print(f"  Matrix: {n} x {V}")

    # ========== STEP 3: Laplacian scores ==========
    print("\nStep 3: Computing Laplacian scores...")
    full_sim = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n):
            a, b = paper_tag_sets[i], paper_tag_sets[j]
            if a and b:
                full_sim[i][j] = len(a & b) / len(a | b)
                full_sim[j][i] = full_sim[i][j]
    W = np.zeros((n, n))
    for i in range(n):
        nn = np.argsort(-full_sim[i])[:12]
        for j in nn:
            if j != i: W[i,j] = full_sim[i,j]; W[j,i] = full_sim[j,i]
    D = np.diag(W.sum(1))
    L = D - W
    lap_scores = []
    for j in range(V):
        f = td[:,j]; ft = f-f.mean(); d = ft@D@ft
        lap_scores.append(float(ft@L@ft/d) if d>1e-10 else float('inf'))
    lap_order = np.argsort(lap_scores)
    print(f"  Done")

    # ========== STEP 4: Procrustes stability ==========
    print("\nStep 4: Procrustes stability analysis...")
    import umap
    from scipy.spatial import procrustes as proc_fn
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    prev_coords = None
    procrustes_data = []
    for top_n in range(2, min(81, V)):
        idx = lap_order[:top_n]
        td_f = td[:, idx]
        empty = td_f.sum(1) == 0
        metric = "cosine" if empty.any() else "jaccard"
        coords = umap.UMAP(metric=metric, n_neighbors=15, min_dist=0.3, spread=1.5, random_state=SEED).fit_transform(td_f)
        coords = np.nan_to_num(coords, 0)
        if prev_coords is not None:
            _, _, disp = proc_fn(prev_coords, coords)
            procrustes_data.append({"top_n": top_n, "disparity": round(disp, 4)})
        prev_coords = coords.copy()

    # Smoothed curve, find elbow
    window = 3
    smoothed = []
    for i in range(len(procrustes_data)):
        lo, hi = max(0, i-window), min(len(procrustes_data), i+window+1)
        avg = np.mean([procrustes_data[j]["disparity"] for j in range(lo, hi)])
        smoothed.append(avg)
    
    # Stability cutoff: first point where smoothed < 0.20 and stays there for 5+ steps
    stable_n = 35  # default
    for i in range(len(smoothed) - 5):
        if all(smoothed[j] < 0.20 for j in range(i, min(i+5, len(smoothed)))):
            stable_n = procrustes_data[i]["top_n"]
            break
    print(f"  Stability cutoff: {stable_n} tags")

    # ========== STEP 5: UMAP at stable cutoff ==========
    print(f"\nStep 5: UMAP with {stable_n} tags...")
    stable_idx = lap_order[:stable_n]
    td_stable = td[:, stable_idx]
    empty = td_stable.sum(1) == 0
    metric = "cosine" if empty.any() else "jaccard"
    coords = umap.UMAP(metric=metric, n_neighbors=15, min_dist=0.3, spread=1.5, random_state=SEED).fit_transform(td_stable)
    coords = np.nan_to_num(coords, 0)
    coords -= coords.mean(0)
    s = max(coords[:,0].max()-coords[:,0].min(), coords[:,1].max()-coords[:,1].min())
    if s > 0: coords = coords / s * 100

    # ========== STEP 6: Clustering ==========
    print("\nStep 6: Clustering K=1..10...")
    cl = {"1": [0]*n}
    sil_per_k = {"1": 0.0}
    bk, bs = 2, -1
    for k in range(2, 11):
        lb = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(coords)
        cl[str(k)] = [int(x) for x in lb]
        sc = silhouette_score(coords, lb)
        sil_per_k[str(k)] = round(sc, 3)
        if sc > bs: bk, bs = k, sc
        print(f"  K={k}: sil={sc:.3f}")

    # ========== STEP 7: Titles ==========
    print(f"\nStep 7: Generating cluster titles (best K={bk})...")
    abstracts = {}
    for p in papers:
        doc = await db.papers.find_one({"id": p["id"]}, {"_id": 0, "abstract": 1})
        if doc and doc.get("abstract"): abstracts[p["id"]] = doc["abstract"][:400]

    all_titles = {}
    sem = asyncio.Semaphore(5)
    async def gen_one(k, c, all_text, count):
        async with sem:
            prompt = TITLE_PROMPT.format(n_clusters=k, cluster_num=c, all_clusters_text=all_text)
            result = await call_claude(prompt, "Research topic classifier. JSON only.")
            title = result.get("title", "") if result else ""
            return str(c), f"{title} ({count})" if title else f"Cluster {c+1} ({count})"

    for k in range(1, 11):
        labels = cl[str(k)]
        cp = defaultdict(list)
        for i, p in enumerate(papers): cp[labels[i]].append(p)
        if k == 1:
            all_titles["1"] = {"0": f"All Papers ({n})"}
            continue
        parts = []
        for cc in sorted(cp.keys()):
            block = "\n".join(f"  - {abstracts.get(p['id'],p['title'][:100])[:300]}" for p in cp[cc][:10])
            parts.append(f"Cluster {cc} ({len(cp[cc])}):\n{block}")
        all_text = "\n\n".join(parts)
        pairs = await asyncio.gather(*[gen_one(k, c, all_text, len(cp[c])) for c in sorted(cp.keys())])
        all_titles[str(k)] = dict(pairs)
        print(f"  K={k} done")

    # ========== STEP 8: Save ==========
    print("\nStep 8: Saving...")
    selected_tags = [vocab[j] for j in stable_idx]
    tag_summary = {tag: int(tag_freq[tag]) for tag in sorted(tag_freq.keys(), key=lambda t: -tag_freq[t])[:30]}

    paper_data = []
    for i, p in enumerate(papers):
        paper_data.append({
            "id": p["id"], "title": p["title"],
            "published": p["published"][:10] if p["published"] else "",
            "arxiv_id": p.get("arxiv_id", ""),
            "x": round(float(coords[i][0]), 1),
            "y": round(float(coords[i][1]), 1),
            "cluster": int(cl[str(bk)][i]),
            "score": scores.get(p["id"], 1200),
            "tags": all_tags.get(p["id"], {}),
        })

    output = {
        "category": CATEGORY,
        "n_papers": n, "n_pairs": 0, "comps_per_paper": 0,
        "score_range": "jaccard", "model": "claude-opus-4-6",
        "method": "incremental_tags_laplacian_stable",
        "stable_cutoff": stable_n,
        "n_clusters": bk, "silhouette": round(bs, 3),
        "has_umap": False, "has_embeddings": False,
        "has_jaccard_stable": True,
        "jaccard_stable_cluster_labels": cl,
        "jaccard_stable_cluster_titles": all_titles,
        "jaccard_stable_silhouette": round(bs, 3),
        "jaccard_stable_best_k": bk,
        "silhouettes_per_k": {"jaccard_stable": sil_per_k},
        "stable_selected_tags": {t: int(tag_freq[t]) for t in selected_tags},
        "stable_tag_set": selected_tags,
        "incremental_tag_summary": tag_summary,
        "procrustes_data": procrustes_data,
        "papers": paper_data,
    }

    with open(OUT_PATH, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"Saved to {OUT_PATH} ({os.path.getsize(OUT_PATH)//1024}KB)")
    print(f"\n=== DONE: {CATEGORY} ===")
    print(f"Papers: {n}, Tags: {len(unique_tags)}, Stable cutoff: {stable_n}")
    print(f"Best K={bk}, Silhouette={bs:.3f}")


if __name__ == "__main__":
    asyncio.run(run())
