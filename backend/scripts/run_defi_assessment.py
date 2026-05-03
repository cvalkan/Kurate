"""Extract PDF text + generate Claude 4.6 Thinking summaries for unassessed Blockchain & AI Agent papers."""
import asyncio, os, sys, time
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')

from core.config import db, logger
from services.llm import download_and_extract_pdf, generate_precomparison_impact_summary, parse_ratings_from_summary
from datetime import datetime, timezone

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
MODEL_INFO = {
    "provider": "anthropic",
    "model": "claude-opus-4-6",
    "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
}
SUMMARY_KEY = "anthropic:claude-opus-4-6:thinking"
PARALLEL_EXTRACT = 5
PARALLEL_SUMMARIZE = 10

async def run():
    # Step 1: Find papers needing work
    papers = []
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents", "ai_rating": {"$exists": False}},
        {"_id": 1, "title": 1, "pdf_path": 1, "pdf_url": 1, "full_text": 1, "doi": 1, "abstract": 1}
    ):
        papers.append(doc)

    total = len(papers)
    need_extract = sum(1 for p in papers if not p.get("full_text"))
    print(f"Papers to process: {total} ({need_extract} need text extraction)", flush=True)

    # Step 2: Extract text from PDFs
    sem_ext = asyncio.Semaphore(PARALLEL_EXTRACT)
    extracted = 0
    ext_failed = 0
    t0 = time.time()

    async def extract_one(doc):
        nonlocal extracted, ext_failed
        if doc.get("full_text"):
            return
        pdf_path = doc.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            ext_failed += 1
            return
        async with sem_ext:
            try:
                # Extract text directly from local PDF file
                from PyPDF2 import PdfReader
                import io

                def _parse_local_pdf(path):
                    with open(path, "rb") as f:
                        reader = PdfReader(f)
                        parts = []
                        for page in reader.pages:
                            text = page.extract_text()
                            if text:
                                parts.append(text)
                    full = "\n".join(parts)
                    full = " ".join(full.split())
                    return full.encode("utf-8", errors="replace").decode("utf-8")

                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, _parse_local_pdf, pdf_path)
                if text and len(text) > 200:
                    await db.defi_papers.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"full_text": text}}
                    )
                    doc["full_text"] = text
                    extracted += 1
                else:
                    ext_failed += 1
            except Exception as e:
                ext_failed += 1
                if ext_failed <= 3:
                    print(f"  Extract error: {doc['title'][:40]}: {str(e)[:80]}", flush=True)

            done = extracted + ext_failed
            if done % 20 == 0:
                print(f"  Extract: [{done}/{need_extract}] {extracted} ok, {ext_failed} fail", flush=True)

    extract_tasks = [extract_one(p) for p in papers if not p.get("full_text")]
    if extract_tasks:
        print(f"\n--- Step 1: Extracting text from {len(extract_tasks)} PDFs ---", flush=True)
        await asyncio.gather(*extract_tasks)
        print(f"Extraction done: {extracted} ok, {ext_failed} fail ({time.time()-t0:.0f}s)", flush=True)

    # Step 3: Generate Claude 4.6 Thinking summaries
    to_summarize = [p for p in papers if p.get("full_text")]
    print(f"\n--- Step 2: Generating Claude 4.6 summaries for {len(to_summarize)} papers ---", flush=True)

    sem_sum = asyncio.Semaphore(PARALLEL_SUMMARIZE)
    generated = 0
    sum_failed = 0
    t1 = time.time()

    async def summarize_one(doc):
        nonlocal generated, sum_failed
        async with sem_sum:
            paper = {
                "title": doc.get("title", ""),
                "abstract": doc.get("abstract", ""),
                "full_text": doc["full_text"],
                "categories": ["defi"],
            }
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=MODEL_INFO)
                if result and result.get("summary") and len(result["summary"]) > 50:
                    update = {
                        f"summaries.{SUMMARY_KEY}": result["summary"],
                        f"summary_dates.{SUMMARY_KEY}": datetime.now(timezone.utc).isoformat(),
                    }
                    if result.get("tokens"):
                        update[f"summary_tokens.{SUMMARY_KEY}"] = result["tokens"]
                    ratings = parse_ratings_from_summary(result["summary"])
                    if ratings:
                        update["ai_rating"] = ratings["score"]
                        update["summary_scores"] = ratings
                    await db.defi_papers.update_one({"_id": doc["_id"]}, {"$set": update})
                    generated += 1
                else:
                    sum_failed += 1
            except Exception as e:
                sum_failed += 1
                if sum_failed <= 3:
                    print(f"  Summary error: {doc['title'][:40]}: {str(e)[:80]}", flush=True)

            done = generated + sum_failed
            if done % 10 == 0 or done == len(to_summarize):
                elapsed = time.time() - t1
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(to_summarize) - done) / rate if rate > 0 else 0
                print(f"  Summary: [{done}/{len(to_summarize)}] {generated} ok, {sum_failed} fail (ETA {eta:.0f}s)", flush=True)

    await asyncio.gather(*[summarize_one(p) for p in to_summarize])

    elapsed = time.time() - t0
    print(f"\n=== Done in {elapsed:.0f}s ===", flush=True)
    print(f"Text extracted: {extracted}", flush=True)
    print(f"Summaries generated: {generated}", flush=True)
    print(f"Failed: {ext_failed} extract, {sum_failed} summary", flush=True)

    assessed = await db.defi_papers.count_documents({"group": "blockchain_ai_agents", "ai_rating": {"$exists": True}})
    print(f"Total assessed in group: {assessed}/237", flush=True)

asyncio.run(run())
