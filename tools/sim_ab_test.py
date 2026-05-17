"""
A/B test: 1-10 (0.5 steps) vs 1-50 (integer) for similarity scoring.
Same 20 pairs from cs.AI, scored by both scales.
"""
import asyncio
import os
import sys
import json
import random
import uuid
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

PAIRS = 20
SEED = 99

PROMPT_10 = """Rate the topical similarity between these two scientific papers.

Use a scale from 1.0 to 10.0 in half-point steps only (1.0, 1.5, 2.0, 2.5, ..., 9.5, 10.0).

1.0 = completely unrelated topics
5.0 = loosely related (same broad field, different subproblems)
10.0 = nearly identical topic (same specific research question)

**Paper 1: {title1}**
{content1}

**Paper 2: {title2}**
{content2}

Respond with JSON only: {{"similarity": 5.5}}"""

PROMPT_50 = """Rate the topical similarity between these two scientific papers.

Use an integer scale from 1 to 50.

1 = completely unrelated topics
25 = loosely related (same broad field, different subproblems)
50 = nearly identical topic (same specific research question)

**Paper 1: {title1}**
{content1}

**Paper 2: {title2}**
{content2}

Respond with JSON only: {{"similarity": 25}}"""


async def get_papers(db, limit=200):
    CLAUDE_KEY = "anthropic:claude-opus-4-6:thinking"
    papers = []
    async for doc in db.papers.find(
        {"categories.0": "cs.AI", f"summaries.{CLAUDE_KEY}": {"$exists": True}},
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
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    try:
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"ab-{uuid.uuid4().hex[:8]}",
            system_message="You are a scientific paper similarity evaluator. Respond with JSON only."
        ).with_model("anthropic", "claude-opus-4-6")
        response = await chat.send_message(UserMessage(text=prompt))
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        data = json.loads(text)
        return data.get("similarity", None)
    except Exception as e:
        print(f"  Error: {str(e)[:80]}")
        return None


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    papers = await get_papers(db)
    print(f"Loaded {len(papers)} cs.AI papers")

    random.seed(SEED)
    pairs = []
    ids = [p["id"] for p in papers]
    pmap = {p["id"]: p for p in papers}
    seen = set()
    while len(pairs) < PAIRS:
        i, j = random.sample(range(len(papers)), 2)
        pair = tuple(sorted([ids[i], ids[j]]))
        if pair not in seen:
            seen.add(pair)
            pairs.append((ids[i], ids[j]))

    print(f"Generated {len(pairs)} pairs\n")

    # Run both scales sequentially (same pairs, same order)
    results_10 = []
    results_50 = []

    for idx, (p1_id, p2_id) in enumerate(pairs):
        p1, p2 = pmap[p1_id], pmap[p2_id]

        prompt_a = PROMPT_10.format(
            title1=p1["title"], content1=p1["content"][:2000],
            title2=p2["title"], content2=p2["content"][:2000],
        )
        prompt_b = PROMPT_50.format(
            title1=p1["title"], content1=p1["content"][:2000],
            title2=p2["title"], content2=p2["content"][:2000],
        )

        score_10, score_50 = await asyncio.gather(
            call_llm(prompt_a),
            call_llm(prompt_b),
        )

        results_10.append(score_10)
        results_50.append(score_50)

        if (idx + 1) % 5 == 0:
            print(f"  {idx + 1}/{PAIRS} done...")

    # Print side-by-side
    print(f"\n{'='*70}")
    print(f"{'Pair':>4}  {'1-10 (0.5 steps)':>16}  {'1-50 (integer)':>14}  {'1-50 → 1-10':>12}  {'Delta':>6}")
    print("-" * 70)
    valid_pairs = 0
    deltas = []
    for i in range(PAIRS):
        s10 = results_10[i]
        s50 = results_50[i]
        if s10 is not None and s50 is not None:
            s50_norm = round(s50 / 5, 1)  # normalize 1-50 to 1-10
            delta = s50_norm - s10
            deltas.append(delta)
            valid_pairs += 1
            print(f"  {i+1:>2}   {s10:>12.1f}      {s50:>10.0f}      {s50_norm:>8.1f}    {delta:>+6.1f}")
        else:
            print(f"  {i+1:>2}   {str(s10):>12}      {str(s50):>10}      {'—':>8}    {'—':>6}")

    # Distribution comparison
    print(f"\n{'='*70}")
    print(f"DISTRIBUTION COMPARISON ({valid_pairs} valid pairs)")
    print(f"{'='*70}")

    v10 = [s for s in results_10 if s is not None]
    v50 = [s for s in results_50 if s is not None]
    v50_norm = [round(s / 5, 1) for s in v50]

    if v10:
        from collections import Counter
        import math

        print(f"\n1-10 scale (0.5 steps):")
        print(f"  Mean={sum(v10)/len(v10):.2f}  Std={math.sqrt(sum((x-sum(v10)/len(v10))**2 for x in v10)/len(v10)):.2f}")
        c10 = Counter(v10)
        print(f"  Distinct values used: {len(c10)}")
        print(f"  Values: {sorted(c10.keys())}")

        print(f"\n1-50 scale (integers):")
        print(f"  Mean={sum(v50)/len(v50):.1f}  Std={math.sqrt(sum((x-sum(v50)/len(v50))**2 for x in v50)/len(v50)):.1f}")
        c50 = Counter(v50)
        print(f"  Distinct values used: {len(c50)}")
        print(f"  Values: {sorted(c50.keys())}")

        print(f"\n1-50 normalized to 1-10:")
        print(f"  Mean={sum(v50_norm)/len(v50_norm):.2f}  Std={math.sqrt(sum((x-sum(v50_norm)/len(v50_norm))**2 for x in v50_norm)/len(v50_norm)):.2f}")
        c50n = Counter(v50_norm)
        print(f"  Distinct values used: {len(c50n)}")

        print(f"\nAgreement (normalized 1-50 vs 1-10):")
        print(f"  Mean delta: {sum(deltas)/len(deltas):+.2f}")
        print(f"  Mean abs delta: {sum(abs(d) for d in deltas)/len(deltas):.2f}")
        print(f"  Correlation: ", end="")
        # Pearson correlation
        mx, my = sum(v10)/len(v10), sum(v50_norm)/len(v50_norm)
        cov = sum((a-mx)*(b-my) for a, b in zip(v10, v50_norm)) / len(v10)
        sx = math.sqrt(sum((a-mx)**2 for a in v10) / len(v10))
        sy = math.sqrt(sum((b-my)**2 for b in v50_norm) / len(v50_norm))
        r = cov / (sx * sy) if sx * sy > 0 else 0
        print(f"{r:.3f}")

    # Save
    with open("/app/memory/similarity_ab_test.json", "w") as f:
        json.dump({"pairs": [(p1, p2) for p1, p2 in pairs], "scale_10": results_10, "scale_50": results_50}, f, indent=2)
    print(f"\nResults saved to /app/memory/similarity_ab_test.json")


if __name__ == "__main__":
    asyncio.run(main())
