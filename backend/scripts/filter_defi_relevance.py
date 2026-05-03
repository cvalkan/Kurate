"""Filter Blockchain & AI Agents papers for relevance using a cheap LLM.

Uses GPT-5-mini via Emergent key to classify each paper as relevant or not.
Reads title + abstract from defi_papers, outputs a relevance score 1-5.
"""
import asyncio, os, sys, time, json
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')

import litellm
from core.config import db
from emergentintegrations.llm.utils import get_integration_proxy_url

EMERGENT_KEY = os.environ["EMERGENT_LLM_KEY"]
PROXY_URL = get_integration_proxy_url()
PARALLEL = 20

SYSTEM = """You are a research paper classifier. Your task is to determine if a paper is specifically about the intersection of BOTH:
1. Blockchain/Cryptocurrency/DeFi/Smart Contracts/Web3 (NOT just general distributed systems)
2. AI Agents/Autonomous agents/Agentic AI/Multi-agent systems/LLM agents (NOT just general ML/AI)

The paper must be substantively about BOTH topics, not just mentioning one in passing.

Respond with ONLY valid JSON:
{"relevant": true/false, "confidence": 1-5, "reason": "one sentence explanation"}"""

async def classify(title, abstract):
    content = f"Title: {title}\n\nAbstract: {abstract[:1500]}" if abstract else f"Title: {title}"
    response = await litellm.acompletion(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        api_key=EMERGENT_KEY,
        api_base=PROXY_URL + "/llm",
        custom_llm_provider="openai",
        max_tokens=100,
        temperature=0,
    )
    text = response.choices[0].message.content.strip()
    try:
        return json.loads(text)
    except:
        # Try extracting JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"relevant": False, "confidence": 1, "reason": "parse error"}


async def run():
    papers = []
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents"},
        {"_id": 1, "title": 1, "abstract": 1}
    ):
        papers.append(doc)

    total = len(papers)
    print(f"Classifying {total} papers for relevance ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    relevant = 0
    irrelevant = 0
    errors = 0
    t0 = time.time()

    async def check_one(doc):
        nonlocal relevant, irrelevant, errors
        async with sem:
            try:
                result = await classify(doc.get("title", ""), doc.get("abstract", ""))
                await db.defi_papers.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {
                        "relevance_check": result,
                        "relevance_score": result.get("confidence", 0) if result.get("relevant") else 0,
                    }}
                )
                if result.get("relevant"):
                    relevant += 1
                else:
                    irrelevant += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"  Error: {doc['title'][:40]}: {str(e)[:80]}", flush=True)

            done = relevant + irrelevant + errors
            if done % 50 == 0 or done == total:
                print(f"  [{done}/{total}] {relevant} relevant, {irrelevant} irrelevant, {errors} errors", flush=True)

    await asyncio.gather(*[check_one(p) for p in papers])

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s", flush=True)
    print(f"Relevant: {relevant}", flush=True)
    print(f"Irrelevant: {irrelevant}", flush=True)
    print(f"Errors: {errors}", flush=True)

    # Show irrelevant papers
    print(f"\n--- Irrelevant papers ---", flush=True)
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents", "relevance_check.relevant": False},
        {"_id": 0, "title": 1, "relevance_check.reason": 1}
    ).sort("title", 1):
        reason = (doc.get("relevance_check") or {}).get("reason", "")
        print(f"  {doc['title'][:65]}  | {reason}", flush=True)

asyncio.run(run())
