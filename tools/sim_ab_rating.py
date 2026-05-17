"""
A/B test: 1-10 (0.1 steps) vs 1-100 (integer) for SI impact ratings.
Same 50 papers from cs.AI, scored by both scales via Claude Opus 4.6.
Only the rating JSON is compared — we skip the full prose assessment for speed.
"""
import asyncio
import os
import sys
import json
import random
import uuid
import math
from collections import Counter
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

N_PAPERS = 50
SEED = 77

SYSTEM_BASE = """You are a scientific impact analyst. Rate this paper's scientific impact.

Consider: novelty, methodological rigor, potential real-world impact, significance, and clarity.

{scale_instruction}

Respond with JSON only."""

SCALE_10 = 'Rate each dimension from 1.0 to 10.0 (one decimal place).\n\nFormat: {"score": 7.5, "significance": 8.0, "rigor": 7.0, "novelty": 7.5, "clarity": 8.0}'

SCALE_100 = 'Rate each dimension from 1 to 100 (integers only).\n\nFormat: {"score": 75, "significance": 80, "rigor": 70, "novelty": 75, "clarity": 80}'

USER_PROMPT = """Rate this paper:

**Title:** {title}

**Abstract:** {abstract}

**AI Impact Assessment (excerpt):**
{summary}

Respond with JSON only."""


async def get_papers(db, limit=100):
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
                "abstract": doc.get("abstract", "")[:500],
                "summary": summary[:1000],
            })
    return papers


async def call_llm(system_msg, user_msg):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    try:
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"ab-{uuid.uuid4().hex[:8]}",
            system_message=system_msg,
        ).with_model("anthropic", "claude-opus-4-6")
        response = await chat.send_message(UserMessage(text=user_msg))
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
        return json.loads(text)
    except Exception as e:
        print(f"  Error: {str(e)[:80]}")
        return None


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    papers = await get_papers(db)
    random.seed(SEED)
    random.shuffle(papers)
    papers = papers[:N_PAPERS]
    print(f"Selected {len(papers)} cs.AI papers\n")

    sys_10 = SYSTEM_BASE.format(scale_instruction=SCALE_10)
    sys_100 = SYSTEM_BASE.format(scale_instruction=SCALE_100)

    results_10 = []
    results_100 = []
    sem = asyncio.Semaphore(3)

    async def process_paper(idx, paper):
        async with sem:
            user_msg = USER_PROMPT.format(
                title=paper["title"],
                abstract=paper["abstract"],
                summary=paper["summary"],
            )
            r10, r100 = await asyncio.gather(
                call_llm(sys_10, user_msg),
                call_llm(sys_100, user_msg),
            )
            if (idx + 1) % 10 == 0:
                print(f"  {idx + 1}/{N_PAPERS} done...")
            return r10, r100

    tasks = [process_paper(i, p) for i, p in enumerate(papers)]
    results = await asyncio.gather(*tasks)

    for r10, r100 in results:
        results_10.append(r10)
        results_100.append(r100)

    # Extract scores
    DIMS = ["score", "significance", "rigor", "novelty", "clarity"]

    print(f"\n{'='*80}")
    print(f"SIDE-BY-SIDE (overall score)")
    print(f"{'='*80}")
    print(f"{'#':>3}  {'1-10':>6}  {'1-100':>6}  {'100→10':>7}  {'Delta':>6}  Title")
    print("-" * 80)

    deltas = []
    for i in range(N_PAPERS):
        r10, r100 = results_10[i], results_100[i]
        if r10 and r100 and "score" in r10 and "score" in r100:
            s10 = r10["score"]
            s100 = r100["score"]
            s100_norm = round(s100 / 10, 1)
            delta = s100_norm - s10
            deltas.append(delta)
            print(f"  {i+1:>2}  {s10:>6.1f}  {s100:>6.0f}  {s100_norm:>7.1f}  {delta:>+6.1f}  {papers[i]['title'][:40]}")

    print(f"\n{'='*80}")
    print(f"DISTRIBUTION COMPARISON")
    print(f"{'='*80}")

    for dim in DIMS:
        v10 = [r[dim] for r in results_10 if r and dim in r]
        v100 = [r[dim] for r in results_100 if r and dim in r]
        v100_norm = [round(v / 10, 1) for v in v100]

        if not v10 or not v100:
            continue

        c10 = Counter(v10)
        c100 = Counter(v100)

        mean10 = sum(v10) / len(v10)
        mean100 = sum(v100) / len(v100)
        std10 = math.sqrt(sum((x - mean10) ** 2 for x in v10) / len(v10))
        std100 = math.sqrt(sum((x - mean100) ** 2 for x in v100) / len(v100))

        # Correlation
        mn10 = sum(v10) / len(v10)
        mn100n = sum(v100_norm) / len(v100_norm)
        pairs = list(zip(v10[:len(v100_norm)], v100_norm))
        if len(pairs) > 2:
            cov = sum((a - mn10) * (b - mn100n) for a, b in pairs) / len(pairs)
            sx = math.sqrt(sum((a - mn10) ** 2 for a, _ in pairs) / len(pairs))
            sy = math.sqrt(sum((b - mn100n) ** 2 for _, b in pairs) / len(pairs))
            r = cov / (sx * sy) if sx * sy > 0 else 0
        else:
            r = 0

        print(f"\n  {dim.upper()}:")
        print(f"    1-10:  mean={mean10:.2f}  std={std10:.2f}  distinct={len(c10)}")
        print(f"    1-100: mean={mean100:.1f}  std={std100:.1f}  distinct={len(c100)}")
        print(f"    Correlation (normalized): {r:.3f}")

        # Decimal distribution for 1-10 scale
        dec10 = Counter(round(v % 1, 1) for v in v10)
        print(f"    1-10 decimal usage: {dict(sorted(dec10.items()))}")

        # Show if 1-100 avoids round numbers
        round_5 = sum(1 for v in v100 if v % 5 == 0)
        round_10 = sum(1 for v in v100 if v % 10 == 0)
        print(f"    1-100 clustering: {round_10}/{len(v100)} on multiples of 10, {round_5}/{len(v100)} on multiples of 5")

    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    all_v10 = [r["score"] for r in results_10 if r and "score" in r]
    all_v100 = [r["score"] for r in results_100 if r and "score" in r]
    print(f"  1-10 scale:  {len(all_v10)} papers, {len(Counter(all_v10))} distinct scores")
    print(f"  1-100 scale: {len(all_v100)} papers, {len(Counter(all_v100))} distinct scores")
    if deltas:
        print(f"  Mean abs delta (normalized): {sum(abs(d) for d in deltas)/len(deltas):.2f}")
        print(f"  Max abs delta: {max(abs(d) for d in deltas):.1f}")

    with open("/app/memory/rating_ab_test.json", "w") as f:
        json.dump({"results_10": results_10, "results_100": results_100, "paper_titles": [p["title"] for p in papers]}, f, indent=2)
    print(f"\nSaved to /app/memory/rating_ab_test.json")


if __name__ == "__main__":
    asyncio.run(main())
