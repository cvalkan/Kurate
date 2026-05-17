"""
Similarity experiment: 100 pairwise similarity scores per category.
Uses Claude Opus 4.6 via Emergent Universal Key.
"""
import asyncio
import os
import sys
import json
import random
import math
import uuid
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

CATEGORIES = ["cs.AI", "physics.comp-ph", "cs.RO"]
PAIRS_PER_CAT = 100
SEED = 42

PROMPT = """Rate the topical similarity between these two scientific papers on a scale from 1.0 to 10.0.

1.0 = completely unrelated topics
5.0 = loosely related (same broad field, different subproblems)
10.0 = nearly identical topic (same specific research question)

**Paper 1: {title1}**
{content1}

**Paper 2: {title2}**
{content2}

Respond with JSON only: {{"similarity": 7.5}}"""


async def get_papers(db, category, limit=200):
    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    papers = []
    async for doc in db.papers.find(
        {"categories.0": category, f"summaries.{CLAUDE_KEY}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, f"summaries.{CLAUDE_KEY}": 1},
    ).limit(limit):
        summary = doc.get("summaries", {}).get(CLAUDE_KEY, "")
        if isinstance(summary, str) and len(summary) > 100:
            papers.append({
                "id": doc["id"],
                "title": doc["title"],
                "content": f"{doc.get('abstract', '')}\n\nAI Impact Assessment:\n{summary[:1500]}",
            })
    return papers


async def call_llm(prompt):
    """Call Claude Opus 4.6 via Emergent Universal Key using emergentintegrations."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    try:
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        chat = LlmChat(
            api_key=api_key,
            session_id=f"sim-{uuid.uuid4().hex[:8]}",
            system_message="You are a scientific paper similarity evaluator. Respond with JSON only."
        ).with_model("anthropic", "claude-opus-4-6")

        user_msg = UserMessage(text=prompt)
        response = await chat.send_message(user_msg)
        text = response.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()

        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        data = json.loads(text)
        return data.get("similarity", None)
    except Exception as e:
        print(f"  LLM error: {str(e)[:80]}")
        return None


async def run_category(db, category, n_pairs):
    papers = await get_papers(db, category)
    print(f"\n{'='*60}")
    print(f"{category}: {len(papers)} papers available")

    if len(papers) < 10:
        print(f"  Not enough papers, skipping")
        return []

    random.seed(SEED + hash(category))
    all_pairs = []
    paper_ids = [p["id"] for p in papers]
    paper_map = {p["id"]: p for p in papers}
    seen = set()

    while len(all_pairs) < n_pairs:
        i, j = random.sample(range(len(papers)), 2)
        pair = tuple(sorted([paper_ids[i], paper_ids[j]]))
        if pair not in seen:
            seen.add(pair)
            all_pairs.append((paper_ids[i], paper_ids[j]))

    print(f"  Generated {len(all_pairs)} unique pairs")

    scores = []
    sem = asyncio.Semaphore(3)  # 3 concurrent (conservative for Claude)
    completed = 0

    async def process_pair(p1_id, p2_id):
        nonlocal completed
        async with sem:
            p1, p2 = paper_map[p1_id], paper_map[p2_id]
            prompt = PROMPT.format(
                title1=p1["title"], content1=p1["content"][:2000],
                title2=p2["title"], content2=p2["content"][:2000],
            )
            score = await call_llm(prompt)
            completed += 1
            if completed % 10 == 0:
                print(f"  {completed}/{n_pairs} done...")
            return score

    tasks = [process_pair(p1, p2) for p1, p2 in all_pairs]
    results = await asyncio.gather(*tasks)
    scores = [s for s in results if s is not None and isinstance(s, (int, float))]
    print(f"  Got {len(scores)}/{n_pairs} valid scores")

    return scores


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    all_results = {}
    for cat in CATEGORIES:
        scores = await run_category(db, cat, PAIRS_PER_CAT)
        all_results[cat] = scores

    print(f"\n{'='*60}")
    print(f"SIMILARITY DISTRIBUTIONS")
    print(f"{'='*60}")

    for cat, scores in all_results.items():
        if not scores:
            print(f"\n{cat}: NO DATA")
            continue
        print(f"\n{cat} ({len(scores)} pairs):")
        print(f"  Mean: {sum(scores)/len(scores):.2f}")
        s = sorted(scores)
        n = len(s)
        print(f"  Median: {s[n//2]:.1f}")
        print(f"  Min: {min(scores):.1f}  Max: {max(scores):.1f}")
        print(f"  Quartiles: P25={s[n//4]:.1f}  P50={s[n//2]:.1f}  P75={s[3*n//4]:.1f}")

        buckets = {f"{i}-{i+1}": 0 for i in range(1, 10)}
        for sc in scores:
            b = max(1, min(9, int(sc)))
            buckets[f"{b}-{b+1}"] += 1

        max_count = max(buckets.values()) if buckets.values() else 1
        print(f"  Distribution:")
        for label, count in buckets.items():
            bar = "#" * int(count / max_count * 40) if max_count > 0 else ""
            pct = count / len(scores) * 100
            print(f"    {label}: {bar} ({count}, {pct:.0f}%)")

    print(f"\n{'='*60}")
    print(f"CROSS-CATEGORY COMPARISON")
    print(f"{'='*60}")
    print(f"{'Category':<20} {'N':>4} {'Mean':>6} {'Med':>5} {'Std':>6} {'Low<3':>6} {'Mid3-7':>7} {'Hi>7':>5}")
    for cat, scores in all_results.items():
        if not scores:
            continue
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((sc - mean) ** 2 for sc in scores) / len(scores))
        low = sum(1 for sc in scores if sc < 3)
        mid = sum(1 for sc in scores if 3 <= sc <= 7)
        high = sum(1 for sc in scores if sc > 7)
        median = sorted(scores)[len(scores) // 2]
        print(f"{cat:<20} {len(scores):>4} {mean:>6.2f} {median:>5.1f} {std:>6.2f} {low:>6} {mid:>7} {high:>5}")

    # Save raw results
    with open("/app/memory/similarity_experiment.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nRaw results saved to /app/memory/similarity_experiment.json")


if __name__ == "__main__":
    asyncio.run(main())
