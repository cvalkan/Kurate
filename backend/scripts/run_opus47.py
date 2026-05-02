import asyncio, os, time
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

import sys
sys.path.insert(0, '/app/backend')

import litellm
from core.config import db
from services.llm import IMPACT_ASSESSMENT_PROMPT, parse_ratings_from_summary, track_llm_usage
from datetime import datetime, timezone

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = "claude-opus-4-7-20260416"
SUMMARY_KEY = "anthropic:claude-opus-4-7:thinking"
PARALLEL = 15

async def gen_summary(paper):
    """Call Anthropic directly — no Emergent proxy."""
    abstract = paper.get("abstract", "")
    full_text = paper.get("full_text", "")
    content = f"Abstract: {abstract}\n\nFull Paper Text:\n{full_text}"

    response = await litellm.acompletion(
        model=f"anthropic/{MODEL}",
        messages=[
            {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
            {"role": "user", "content": content},
        ],
        api_key=ANTHROPIC_KEY,
        extra_body={"thinking": {"type": "enabled", "budget_tokens": 10000}},
    )

    text = response.choices[0].message.content
    usage = response.usage
    tokens = {
        "input": getattr(usage, "prompt_tokens", 0) or 0,
        "output": getattr(usage, "completion_tokens", 0) or 0,
    }
    details = getattr(usage, "completion_tokens_details", None)
    if details:
        tokens["thinking"] = getattr(details, "reasoning_tokens", 0) or 0

    return text, tokens


async def run():
    paper_ids = []
    async for doc in db.papers.find(
        {"summaries.openai:gpt-5_5": {"$exists": True},
         f"summaries.{SUMMARY_KEY}": {"$exists": False},
         "full_text": {"$ne": None}},
        {"_id": 0, "id": 1}
    ):
        paper_ids.append(doc["id"])

    total = len(paper_ids)
    print(f"Generating Claude Opus 4.7 Thinking summaries for {total} papers ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    generated = 0
    failed = 0
    t0 = time.time()

    async def gen_one(paper_id):
        nonlocal generated, failed
        async with sem:
            paper = await db.papers.find_one(
                {"id": paper_id},
                {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1, "categories": 1}
            )
            if not paper:
                return
            check = await db.papers.find_one({"id": paper_id, f"summaries.{SUMMARY_KEY}": {"$exists": True}}, {"_id": 0, "id": 1})
            if check:
                return
            try:
                summary_text, tokens = await gen_summary(paper)
                if summary_text and len(summary_text) > 50:
                    update = {
                        f"summaries.{SUMMARY_KEY}": summary_text,
                        f"summary_dates.{SUMMARY_KEY}": datetime.now(timezone.utc).isoformat(),
                        f"summary_tokens.{SUMMARY_KEY}": tokens,
                    }
                    ratings = parse_ratings_from_summary(summary_text)
                    if ratings:
                        update["ai_ratings_by_model.claude47"] = ratings
                    await db.papers.update_one({"id": paper_id}, {"$set": update})
                    await track_llm_usage("anthropic", MODEL, context="summary", success=True,
                                          paper_title=paper.get("title", "")[:80],
                                          input_tokens=tokens.get("input", 0),
                                          output_tokens=tokens.get("output", 0),
                                          thinking_tokens=tokens.get("thinking", 0),
                                          api_source="direct")
                    generated += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  Error: {str(e)[:150]}", flush=True)

            done = generated + failed
            if done % 25 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] {generated} ok, {failed} fail ({rate:.1f}/s, ETA {eta:.0f}s)", flush=True)

    tasks = [gen_one(pid) for pid in paper_ids]
    await asyncio.gather(*tasks)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s: {generated} generated, {failed} failed", flush=True)

asyncio.run(run())
