"""
Vision vs Text Experiment Runner (Parallel)
=============================================
For each of 100 selected papers, generates two new Claude Opus 4.6 Thinking summaries:
  (a) Text mode: existing PyPDF2 extracted full_text (current pipeline)
  (b) PDF mode: native type:document via Anthropic direct API (text + vision)

Runs 5 concurrent workers. Saves progress to DB after each paper.
Run with: cd /app/backend && python3 scripts/run_vision_experiment.py > /tmp/vision_experiment.log 2>&1 &
"""
import asyncio
import os
import sys
import json
import time
import base64
import re
import logging
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

import anthropic
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("vision-exp")

# Config
EXPERIMENT_ID = "vision-vs-text-v1"
MODEL = "claude-opus-4-6"
THINKING_BUDGET = 10000
MAX_TOKENS = 16000
CONCURRENCY = 5  # 5 workers × ~2 req/min = ~10 RPM (well under 50 RPM limit)

SYSTEM_PROMPT = """You are a scientific impact analyst. Your task is to evaluate the potential scientific impact of research papers.
You must be objective, thorough, and provide a quantitative score."""


def build_user_prompt(title, abstract):
    """Build the assessment prompt — same structure as existing pipeline."""
    return f"""Write a comprehensive scientific impact assessment for the following paper.

Title: {title}

Abstract: {abstract or "N/A"}

Provide your assessment covering:
1. Summary of key contributions
2. Novelty and originality
3. Methodological rigor
4. Potential real-world impact
5. Limitations and weaknesses

Then provide your ratings as a JSON block at the end in this exact format:
{{"score": <overall 1-10>, "significance": <1-10>, "rigor": <1-10>, "novelty": <1-10>, "clarity": <1-10>, "impact": <1-10>}}"""


def extract_ratings(text):
    """Extract the JSON ratings block from a summary."""
    if not text:
        return None
    matches = list(re.finditer(r'\{[^{}]*"score"[^{}]*\}', text))
    if matches:
        try:
            return json.loads(matches[-1].group())
        except json.JSONDecodeError:
            pass
    return None


def call_anthropic_text(api_key, paper):
    """Synchronous call for text mode (runs in thread pool)."""
    client = anthropic.Anthropic(api_key=api_key)
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    full_text = paper.get("full_text", "")

    if not full_text:
        return {"error": "no_full_text"}, None

    prompt = build_user_prompt(title, abstract)
    # Add full text as content
    content = f"{prompt}\n\nFull Paper Text:\n{full_text}"

    start = time.time()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        messages=[{"role": "user", "content": content}],
    )
    elapsed = time.time() - start

    summary = ""
    thinking_len = 0
    for block in response.content:
        if block.type == "text":
            summary += block.text
        elif block.type == "thinking":
            thinking_len = len(block.thinking)

    ratings = extract_ratings(summary)
    return {
        "summary": summary,
        "ratings": ratings,
        "thinking_len": thinking_len,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "elapsed_s": round(elapsed, 1),
    }, ratings


def call_anthropic_pdf(api_key, pdf_bytes, paper):
    """Synchronous call for PDF mode (runs in thread pool)."""
    client = anthropic.Anthropic(api_key=api_key)
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = build_user_prompt(title, abstract)

    start = time.time()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    elapsed = time.time() - start

    summary = ""
    thinking_len = 0
    for block in response.content:
        if block.type == "text":
            summary += block.text
        elif block.type == "thinking":
            thinking_len = len(block.thinking)

    ratings = extract_ratings(summary)
    return {
        "summary": summary,
        "ratings": ratings,
        "thinking_len": thinking_len,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "elapsed_s": round(elapsed, 1),
        "pdf_size_kb": len(pdf_bytes) // 1024,
    }, ratings


async def process_paper(sem, api_key, db, http_client, paper_id, meta, idx, total):
    """Process one paper: text + PDF runs."""
    async with sem:
        paper = await db.papers.find_one({"id": paper_id}, {"_id": 0})
        if not paper:
            log.warning(f"[{idx}/{total}] Paper {paper_id[:8]} not found")
            return

        group = meta.get("group", "?")
        title_short = paper.get("title", "")[:50]
        results_coll = db.experiment_results

        # Check what's already done
        existing = await results_coll.find_one(
            {"experiment_id": EXPERIMENT_ID, "paper_id": paper_id},
            {"_id": 0, "text_result": 1, "pdf_result": 1}
        )
        has_text = existing and existing.get("text_result") and not existing["text_result"].get("error")
        has_pdf = existing and existing.get("pdf_result") and not existing["pdf_result"].get("error")

        # --- Run (a): Text mode ---
        if not has_text:
            log.info(f"[{idx}/{total}] TEXT  {group:>7} {title_short}")
            try:
                loop = asyncio.get_event_loop()
                text_result, text_ratings = await loop.run_in_executor(
                    None, call_anthropic_text, api_key, paper
                )
                if text_result.get("error"):
                    log.warning(f"  Text error: {text_result['error']}")
                else:
                    score = text_ratings.get("score") if text_ratings else "?"
                    cost = (text_result["input_tokens"] * 15 + text_result["output_tokens"] * 75) / 1_000_000
                    log.info(f"  → score={score}, in={text_result['input_tokens']}, out={text_result['output_tokens']}, ${cost:.3f}, {text_result['elapsed_s']}s")
            except Exception as e:
                log.error(f"  Text exception: {e}")
                text_result = {"error": str(e)[:200]}

            await results_coll.update_one(
                {"experiment_id": EXPERIMENT_ID, "paper_id": paper_id},
                {"$set": {
                    "experiment_id": EXPERIMENT_ID,
                    "paper_id": paper_id,
                    "group": group,
                    "title": paper.get("title"),
                    "category": meta.get("category"),
                    "existing_rating": meta.get("existing_rating"),
                    "visual_score": meta.get("visual_score"),
                    "text_result": text_result,
                    "text_completed_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
        else:
            log.info(f"[{idx}/{total}] TEXT  {group:>7} {title_short} — done")

        # --- Run (b): PDF mode ---
        if not has_pdf:
            pdf_link = paper.get("pdf_link") or (f"https://arxiv.org/pdf/{paper['arxiv_id']}" if paper.get("arxiv_id") else None)
            if not pdf_link:
                log.warning(f"[{idx}/{total}] PDF   {group:>7} no pdf_link, skipping")
                await results_coll.update_one(
                    {"experiment_id": EXPERIMENT_ID, "paper_id": paper_id},
                    {"$set": {"pdf_result": {"error": "no_pdf_link"}, "pdf_completed_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
                return

            log.info(f"[{idx}/{total}] PDF   {group:>7} {title_short}")
            try:
                # Download PDF
                resp = await http_client.get(pdf_link, timeout=30, follow_redirects=True)
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")
                pdf_bytes = resp.content

                loop = asyncio.get_event_loop()
                pdf_result, pdf_ratings = await loop.run_in_executor(
                    None, call_anthropic_pdf, api_key, pdf_bytes, paper
                )
                if pdf_result.get("error"):
                    log.warning(f"  PDF error: {pdf_result['error']}")
                else:
                    score = pdf_ratings.get("score") if pdf_ratings else "?"
                    cost = (pdf_result["input_tokens"] * 15 + pdf_result["output_tokens"] * 75) / 1_000_000
                    log.info(f"  → score={score}, in={pdf_result['input_tokens']}, out={pdf_result['output_tokens']}, ${cost:.3f}, {pdf_result['elapsed_s']}s")
            except Exception as e:
                log.error(f"  PDF exception: {e}")
                pdf_result = {"error": str(e)[:200]}

            await results_coll.update_one(
                {"experiment_id": EXPERIMENT_ID, "paper_id": paper_id},
                {"$set": {
                    "pdf_result": pdf_result,
                    "pdf_completed_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
        else:
            log.info(f"[{idx}/{total}] PDF   {group:>7} {title_short} — done")


async def main():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    exp = await db.experiments.find_one({"experiment_id": EXPERIMENT_ID})
    if not exp:
        log.error(f"Experiment {EXPERIMENT_ID} not found")
        return

    paper_ids = exp["all_paper_ids"]
    papers_meta = {p["id"]: p for p in exp["papers"]}
    total = len(paper_ids)
    log.info(f"Experiment: {total} papers, {CONCURRENCY} workers")

    # Count already done
    done_text = await db.experiment_results.count_documents(
        {"experiment_id": EXPERIMENT_ID, "text_result": {"$exists": True}, "text_result.error": {"$exists": False}}
    )
    done_pdf = await db.experiment_results.count_documents(
        {"experiment_id": EXPERIMENT_ID, "pdf_result": {"$exists": True}, "pdf_result.error": {"$exists": False}}
    )
    log.info(f"Already done: {done_text} text, {done_pdf} pdf")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as http:
        tasks = [
            process_paper(sem, api_key, db, http, pid, papers_meta.get(pid, {}), i+1, total)
            for i, pid in enumerate(paper_ids)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # Final summary
    done_text = await db.experiment_results.count_documents(
        {"experiment_id": EXPERIMENT_ID, "text_result.ratings": {"$exists": True}}
    )
    done_pdf = await db.experiment_results.count_documents(
        {"experiment_id": EXPERIMENT_ID, "pdf_result.ratings": {"$exists": True}}
    )
    log.info(f"\nComplete: {done_text}/100 text, {done_pdf}/100 pdf")


if __name__ == "__main__":
    asyncio.run(main())
