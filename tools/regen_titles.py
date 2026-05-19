"""
Regenerate cluster titles for all 6 Jaccard views.
Max parallelization: all K values and clusters called concurrently.
"""
import asyncio, os, sys, json, uuid, re
from collections import defaultdict, Counter
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

PARTIAL_PATH = "/tmp/regen_titles_partial.json"

TITLE_PROMPT = """Below are paper abstracts from {n_clusters} different clusters of research papers. Each cluster contains topically similar papers. Generate a short (2-5 word) DISTINGUISHING theme label for Cluster {cluster_num}.

{all_clusters_text}

Focus on what makes Cluster {cluster_num} UNIQUE compared to the others. Avoid generic labels — be specific about the distinguishing topic, application domain, or methodology.

Respond with JSON only: {{"title": "Molecular Dynamics Simulations"}}"""


async def call_llm(prompt, retries=2):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    for attempt in range(retries + 1):
        try:
            chat = LlmChat(api_key=os.environ.get("EMERGENT_LLM_KEY"),
                           session_id=f"rt-{uuid.uuid4().hex[:8]}",
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


async def gen_titles_for_view(view_name, labels_map, papers, abstracts, sem):
    """Generate titles for all K=1..10 for one view, with concurrency limit."""
    results = {}

    async def gen_one(k, c, all_text, count):
        async with sem:
            prompt = TITLE_PROMPT.format(n_clusters=k, cluster_num=c, all_clusters_text=all_text)
            title = await call_llm(prompt)
            label = f"{title} ({count})" if title else f"Cluster {c+1} ({count})"
            return str(c), label

    for k in range(1, 11):
        labels = labels_map.get(str(k))
        if not labels:
            continue
        cp = defaultdict(list)
        for i, p in enumerate(papers):
            cp[labels[i]].append(p)

        parts = []
        for cc in sorted(cp.keys()):
            block = "\n".join(f"  - {abstracts.get(p['id'], p['title'][:100])[:300]}" for p in cp[cc][:10])
            parts.append(f"Cluster {cc} ({len(cp[cc])}):\n{block}")
        all_text = "\n\n".join(parts)

        if k == 1:
            results["1"] = {"0": f"All Papers ({len(papers)})"}
            continue

        tasks = [gen_one(k, c, all_text, len(cp[c])) for c in sorted(cp.keys())]
        pairs = await asyncio.gather(*tasks)
        results[str(k)] = dict(pairs)
        print(f"  {view_name} K={k}: done")

    return results


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    with open("/app/backend/data/precomputed/similarity_landscape_physics_comp_ph.json") as f:
        data = json.load(f)
    papers = data["papers"]

    abstracts = {}
    for p in papers:
        doc = await db.papers.find_one({"id": p["id"]}, {"_id": 0, "abstract": 1})
        if doc and doc.get("abstract"):
            abstracts[p["id"]] = doc["abstract"][:400]
    print(f"{len(abstracts)} abstracts loaded")

    # Load partial results
    partial = {}
    if os.path.exists(PARTIAL_PATH):
        with open(PARTIAL_PATH) as f:
            partial = json.load(f)
        print(f"Resumed {len(partial)} views from partial")

    views = [
        ("jaccard_incr", "jaccard_incr_cluster_labels", "jaccard_incr_cluster_titles"),
        ("jaccard_topics", "jaccard_topics_cluster_labels", "jaccard_topics_cluster_titles"),
        ("jaccard_methods", "jaccard_methods_cluster_labels", "jaccard_methods_cluster_titles"),
        ("jaccard_domains", "jaccard_domains_cluster_labels", "jaccard_domains_cluster_titles"),
        ("jaccard_concepts", "jaccard_concepts_cluster_labels", "jaccard_concepts_cluster_titles"),
        ("jaccard_laplacian", "jaccard_laplacian_cluster_labels", "jaccard_laplacian_cluster_titles"),
    ]

    sem = asyncio.Semaphore(5)  # 5 concurrent LLM calls

    for view_name, labels_key, titles_key in views:
        if view_name in partial:
            data[titles_key] = partial[view_name]
            print(f"{view_name}: loaded from partial")
            continue

        labels_map = data.get(labels_key, {})
        if not labels_map:
            print(f"{view_name}: no labels, skipping")
            continue

        print(f"\n{view_name}:")
        titles = await gen_titles_for_view(view_name, labels_map, papers, abstracts, sem)
        data[titles_key] = titles
        partial[view_name] = titles

        # Save partial after each view
        with open(PARTIAL_PATH, "w") as f:
            json.dump(partial, f)

    with open("/app/backend/data/precomputed/similarity_landscape_physics_comp_ph.json", "w") as f:
        json.dump(data, f)
    print("\nSaved all titles")


if __name__ == "__main__":
    asyncio.run(main())
