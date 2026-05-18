"""
Generate LLM-based cluster titles for K=1..10 using the existing similarity landscape data.
Uses Claude Opus 4.6 via Emergent Universal Key.
"""
import asyncio
import os
import sys
import json
import uuid
import numpy as np
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

SEED = 42
DATA_PATH = "/app/backend/data/precomputed/similarity_landscape.json"

TITLE_PROMPT = """Given these paper titles from a cluster of AI research papers, generate a short (2-5 word) theme label that captures the common research topic.

Paper titles:
{titles}

Respond with JSON only: {{"title": "Multi-Agent Systems"}}"""


async def call_llm(prompt):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    try:
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"ct-{uuid.uuid4().hex[:8]}",
            system_message="You are a research topic classifier. Respond with JSON only."
        ).with_model("anthropic", "claude-opus-4-6")
        response = await chat.send_message(UserMessage(text=prompt))
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        return json.loads(text).get("title", "")
    except Exception as e:
        print(f"  LLM error: {str(e)[:80]}")
        return None


async def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    papers = data["papers"]
    n = len(papers)
    print(f"Loaded {n} papers from landscape data")

    # Get MDS coords for clustering
    coords = np.array([[p["x"], p["y"]] for p in papers])

    from sklearn.cluster import KMeans

    all_cluster_titles = {}  # {K: {cluster_id: title}}
    all_cluster_labels = {}  # {K: [label_per_paper]}

    for k in range(1, 11):
        print(f"\n=== K={k} ===")
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        labels = km.fit_predict(coords)

        # Group paper titles by cluster
        cluster_titles_map = {}
        for i, p in enumerate(papers):
            c = int(labels[i])
            if c not in cluster_titles_map:
                cluster_titles_map[c] = []
            cluster_titles_map[c].append(p["title"])

        # Generate title for each cluster
        titles = {}
        for c in sorted(cluster_titles_map.keys()):
            paper_titles = cluster_titles_map[c]
            # Send up to 20 titles (enough for theme detection)
            sample = paper_titles[:20]
            titles_text = "\n".join(f"- {t}" for t in sample)
            prompt = TITLE_PROMPT.format(titles=titles_text)
            title = await call_llm(prompt)
            count = len(paper_titles)
            if title:
                titles[c] = f"{title} ({count})"
                print(f"  Cluster {c}: {title} ({count} papers)")
            else:
                titles[c] = f"Cluster {c + 1} ({count})"
                print(f"  Cluster {c}: FAILED ({count} papers)")

        all_cluster_titles[str(k)] = titles
        all_cluster_labels[str(k)] = [int(l) for l in labels]

    # Update the JSON file
    data["cluster_titles"] = all_cluster_titles
    data["cluster_labels"] = all_cluster_labels

    with open(DATA_PATH, "w") as f:
        json.dump(data, f)

    print(f"\nSaved cluster titles for K=1..10 to {DATA_PATH}")
    total_calls = sum(k for k in range(1, 11))
    print(f"Total LLM calls: {total_calls}")


if __name__ == "__main__":
    asyncio.run(main())
