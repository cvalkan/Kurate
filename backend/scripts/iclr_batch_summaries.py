#!/usr/bin/env python3
"""
ICLR 2026 Batch Summary Pipeline
=================================
Optimized for maximal throughput using Claude Opus 4.6 Thinking.

- Downloads PDFs from OpenReview via Playwright (bypasses IP blocks)
- Generates summaries using the exact same prompts as the live leaderboard
- Extracts structured ai_rating (score, significance, rigor, novelty, clarity)
- Resumable: skips papers already completed in the output file
- Detailed error logging

Usage:
    cd /app/backend && nohup python3 scripts/iclr_batch_summaries.py > /tmp/iclr_batch.log 2>&1 &

Output: JSONL file, one line per paper.
"""

import argparse
import asyncio
import csv
import json
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

from PyPDF2 import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import litellm
from emergentintegrations.llm.utils import get_integration_proxy_url

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
if not EMERGENT_LLM_KEY:
    from core.config import EMERGENT_LLM_KEY

# ── Exact same prompt as live leaderboard ──
IMPACT_ASSESSMENT_PROMPT = {
    "system_prompt": """You are a scientific impact analyst. Your task is to write a detailed scientific impact assessment of a research paper. This assessment will later be used in a pairwise tournament to compare papers' scientific impact.

Write up to 1000 words (can be shorter if the paper warrants it). Structure your assessment around:

1. **Core Contribution**: What is the main novelty? What problem does it solve and how?
2. **Methodological Rigor**: How sound is the approach? Are the experiments/proofs convincing?
3. **Potential Impact**: What are the real-world applications? How broadly could this influence the field or adjacent fields?
4. **Timeliness & Relevance**: Does this address a current bottleneck or emerging need?
5. **Strengths & Limitations**: Key strengths that make this paper stand out, and notable weaknesses or gaps.

Feel free to add any other observations you deem important for judging scientific impact (e.g., scalability, reproducibility, dataset contributions, theoretical insights, comparison to prior art).

Be specific and analytical — avoid generic praise. Your assessment should give enough detail for another evaluator to judge this paper's impact without reading the full text.

After your assessment, provide numerical ratings on a JSON line. Rate each dimension from 1.0 to 10.0 (one decimal place):

```json
{"score": 7.5, "significance": 8.0, "rigor": 7.0, "novelty": 7.5, "clarity": 8.0}
```""",
    "user_prompt": """Write a scientific impact assessment for the following paper:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words), then provide your numerical ratings as a JSON line at the end:""",
}

MODEL_INFO = {
    "provider": "anthropic",
    "model": "claude-opus-4-6",
    "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}},
}

TOKEN_LIMIT_KEYWORDS = (
    "token", "context_length", "context length", "too long", "too many tokens",
    "maximum context", "max_tokens", "content_too_large", "request too large",
    "input too long", "payload too large",
)

_llm_pool = ThreadPoolExecutor(max_workers=25, thread_name_prefix="llm")


# ═══════════════════════════════════════════════════════════════════════
# Author Anonymization
# ═══════════════════════════════════════════════════════════════════════

import re as _re

def anonymize_text(text: str) -> str:
    """Strip author names from ICLR PDF text to prevent bias.

    ICLR accepted papers have authors between the title and ABSTRACT.
    Rejected/withdrawn papers already say "Anonymous authors".
    Also strips author-identifying footnotes (corresponding author, emails, affiliations).
    """
    # Already anonymous — still strip any footnotes that might leak
    is_anonymous = "anonymous authors" in text[:2000].lower()

    if not is_anonymous:
        # Strip author block between header and ABSTRACT
        abstract_match = _re.search(r'\bABSTRACT\b', text[:5000])
        if abstract_match:
            header_patterns = [
                r'Published as a conference paper at ICLR \d{4}\s*',
                r'Under review as a conference paper at ICLR \d{4}\s*',
                r'Workshop paper at ICLR \d{4}\s*',
            ]
            header_end = 0
            for pat in header_patterns:
                m = _re.search(pat, text[:abstract_match.start()], _re.IGNORECASE)
                if m:
                    header_end = m.end()
                    break
            if header_end == 0:
                header_end = min(500, abstract_match.start())

            text = text[:header_end] + "Anonymous authors. Paper under double-blind review. " + text[abstract_match.start():]

    # Strip author-identifying footnotes that appear anywhere in the text:
    # Pattern: ∗ or † followed by a name and parenthesized content (email, affiliation)
    text = _re.sub(r'[∗†\*][A-Z][a-zA-Z\s\-\.]{1,60}\([^)]*@[^)]*\)', '', text)
    text = _re.sub(r'[∗†\*][A-Z][^.]{0,200}@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^.]*\.?', '', text)
    # Pattern: "Corresponding author" sentences
    text = _re.sub(r'[∗†\*]?\s*[Cc]orresponding authors?[^.]*\.', '', text)
    # Pattern: "Equal contribution" with names
    text = _re.sub(r'[∗†\*]?\s*[Ee]qual [Cc]ontribution[^.]*\.?', '', text)
    # Pattern: "This work is done when ... interns at ..."
    text = _re.sub(r'[†∗\*]?\s*This work (?:is|was) done (?:when|while)[^.]*\.', '', text)
    # Curly-brace email groups
    text = _re.sub(r'\{[a-zA-Z0-9_.,-]+\}@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '', text)
    # Standalone email addresses
    text = _re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '[email removed]', text)
    # Strip ACKNOWLEDGMENTS section entirely (contains grants, affiliations, lab names)
    # This section sits between the paper body and REFERENCES/APPENDIX
    text = _re.sub(
        r'(?:Acknowledgements?|Acknowledgments?|ACKNOWLEDGEMENTS?|ACKNOWLEDGMENTS?)[\s.:]*'
        r'(?:.*?)'
        r'(?=\bREFERENCES\b|\bAPPENDI[XC]\b|\b[A-Z]\s+(?:ADDITIONAL|PROOF|DETAIL|IMPLEMENTATION|EXTENDED|EXPERIMENTAL)\b)',
        'ACKNOWLEDGMENTS [removed for blind review] ',
        text,
        flags=_re.IGNORECASE | _re.DOTALL,
    )

    return text


# ═══════════════════════════════════════════════════════════════════════
# PDF Download via Playwright (shared browser)
# ═══════════════════════════════════════════════════════════════════════

_browser = None
_pw = None

async def _get_browser():
    global _browser, _pw
    if _browser and _browser.is_connected():
        return _browser
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
    )
    return _browser


async def download_pdf_playwright(openreview_id: str, max_retries: int = 3) -> Optional[str]:
    """Download PDF from OpenReview via Playwright and extract text. Retries on failure."""
    for attempt in range(max_retries):
        browser = await _get_browser()
        ctx = await browser.new_context(accept_downloads=True)
        page = await ctx.new_page()
        url = f"https://openreview.net/pdf?id={openreview_id}"

        try:
            dl_future = page.expect_download(timeout=30000)
            try:
                await page.goto(url, timeout=15000)
            except Exception:
                pass  # goto throws "Download is starting" — expected

            download = await dl_future.__aenter__()
            dl = await download.value
            path = await dl.path()

            with open(path, "rb") as f:
                content = f.read()

            if not content or content[:5] != b"%PDF-":
                await ctx.close()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            def _parse(data: bytes) -> str:
                reader = PdfReader(io.BytesIO(data))
                parts = [pg.extract_text() or "" for pg in reader.pages]
                text = "\n".join(parts)
                text = " ".join(text.split())
                return text.encode("utf-8", errors="replace").decode("utf-8")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _parse, content)
            await ctx.close()
            return result

        except Exception:
            pass
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)

    return None


# ═══════════════════════════════════════════════════════════════════════
# Summary Generation
# ═══════════════════════════════════════════════════════════════════════

def _build_litellm_params(title: str, content: str) -> dict:
    prompt = IMPACT_ASSESSMENT_PROMPT["user_prompt"].format(title=title, content=content)
    messages = [
        {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
        {"role": "user", "content": prompt},
    ]
    params = {
        "messages": messages,
        "api_key": EMERGENT_LLM_KEY,
    }
    is_emergent = EMERGENT_LLM_KEY and EMERGENT_LLM_KEY.startswith("sk-emergent")
    if is_emergent:
        proxy_url = get_integration_proxy_url()
        params["api_base"] = proxy_url + "/llm"
        params["custom_llm_provider"] = "openai"
        params["model"] = MODEL_INFO["model"]
    else:
        params["model"] = f"{MODEL_INFO['provider']}/{MODEL_INFO['model']}"
    params.update(MODEL_INFO.get("extra_params", {}))
    return params


def parse_ratings(summary_text: str) -> Optional[dict]:
    import re
    matches = list(re.finditer(r'\{[^{}]*"score"[^{}]*\}', summary_text))
    if not matches:
        return None
    try:
        data = json.loads(matches[-1].group())
        score = float(data.get("score", 0))
        if 1.0 <= score <= 10.0:
            return {
                "score": round(score, 1),
                "significance": round(float(data.get("significance", 0)), 1),
                "rigor": round(float(data.get("rigor", 0)), 1),
                "novelty": round(float(data.get("novelty", 0)), 1),
                "clarity": round(float(data.get("clarity", 0)), 1),
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


async def generate_summary(title: str, full_text: str, abstract: str = "") -> dict:
    content_text = f"Abstract: {abstract}\n\nFull Paper Text:\n{full_text}" if abstract else full_text
    char_limit = len(content_text)
    original_limit = char_limit
    was_truncated = False

    for attempt in range(4):
        if was_truncated:
            trunc = full_text[:char_limit]
            content_text = f"Abstract: {abstract}\n\nFull Paper Text:\n{trunc}" if abstract else trunc

        params = _build_litellm_params(title, content_text)

        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(_llm_pool, lambda p=params: litellm.completion(**p))
            text = raw.choices[0].message.content if raw.choices else ""
            if text and text.strip():
                summary = text.strip()
                if was_truncated:
                    pct = round(100 * char_limit / original_limit)
                    summary += f"\n\n[Note: Summary generated from {pct}% of paper ({char_limit:,}/{original_limit:,} chars) due to context window limits.]"
                tokens = {}
                if raw.usage:
                    tokens["input"] = getattr(raw.usage, "prompt_tokens", 0) or 0
                    tokens["output"] = getattr(raw.usage, "completion_tokens", 0) or 0
                    details = getattr(raw.usage, "completion_tokens_details", None)
                    if details:
                        tokens["thinking"] = getattr(details, "reasoning_tokens", 0) or 0
                return {"summary": summary, "tokens": tokens, "truncated": was_truncated,
                        "truncated_pct": round(100 * char_limit / original_limit) if was_truncated else 100, "error": None}
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("budget", "balance", "insufficient", "credit", "quota")):
                return {"summary": None, "error": f"BUDGET_ERROR: {str(e)[:200]}"}
            elif any(k in err for k in ("refused", "safety", "content_policy", "harmful", "i cannot")):
                return {"summary": None, "error": f"REFUSED: {str(e)[:200]}"}
            elif any(k in err for k in TOKEN_LIMIT_KEYWORDS):
                char_limit = max(char_limit // 2, 20_000)
                was_truncated = True
            else:
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)

    return {"summary": None, "error": "MAX_RETRIES_EXCEEDED"}


# ═══════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════

async def process_paper(row: dict, pdf_sem: asyncio.Semaphore, llm_sem: asyncio.Semaphore) -> dict:
    openreview_id = row["id"]
    title = row["title"]
    t0 = time.time()

    result = {
        "openreview_id": openreview_id,
        "title": title,
        "label": row["labels"],
        "status": row["status"],
        "reviewer_scores": row["scores"],
        "pdf_ok": False,
        "full_text_chars": 0,
        "summary": None,
        "ai_rating": None,
        "tokens": None,
        "truncated": False,
        "error": None,
        "elapsed_s": 0,
    }

    # 1. Download PDF
    async with pdf_sem:
        full_text = await download_pdf_playwright(openreview_id)

    if not full_text or len(full_text) < 500:
        result["error"] = "PDF_DOWNLOAD_FAILED" if not full_text else f"PDF_TOO_SHORT ({len(full_text)} chars)"
        result["elapsed_s"] = round(time.time() - t0, 1)
        return result

    result["pdf_ok"] = True
    result["full_text_chars"] = len(full_text)

    # 2. Anonymize: strip author names to prevent bias
    full_text = anonymize_text(full_text)

    # 3. Generate summary
    async with llm_sem:
        gen = await generate_summary(title, full_text)

    if gen.get("error"):
        result["error"] = gen["error"]
        result["elapsed_s"] = round(time.time() - t0, 1)
        return result

    if gen.get("summary"):
        result["summary"] = gen["summary"]
        result["tokens"] = gen.get("tokens")
        result["truncated"] = gen.get("truncated", False)
        ratings = parse_ratings(gen["summary"])
        result["ai_rating"] = ratings
        if not ratings:
            result["error"] = "RATING_PARSE_FAILED"

    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


async def main():
    parser = argparse.ArgumentParser(description="ICLR 2026 Batch Summary Pipeline")
    parser.add_argument("--input", default="/app/memory/iclr_2026_sample.csv")
    parser.add_argument("--output", default="/app/memory/iclr_2026_summaries.jsonl")
    parser.add_argument("--log", default="/app/memory/iclr_2026_errors.log")
    parser.add_argument("--parallel-llm", type=int, default=15)
    parser.add_argument("--parallel-pdf", type=int, default=3)  # Low: OpenReview rate-limits
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    with open(args.input) as f:
        rows = list(csv.DictReader(f))
    print(f"[{datetime.now(timezone.utc).isoformat()}] Loaded {len(rows)} papers from {args.input}")

    if args.limit > 0:
        rows = rows[:args.limit]
        print(f"  Limited to first {args.limit}")

    # Resume support
    completed = set()
    if os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if rec.get("summary"):
                            completed.add(rec["openreview_id"])
                    except json.JSONDecodeError:
                        pass
    if completed:
        print(f"  Resuming: {len(completed)} done, {len(rows) - len(completed)} remaining")

    pending = [r for r in rows if r["id"] not in completed]
    if not pending:
        print("All papers already processed!")
        return

    pdf_sem = asyncio.Semaphore(args.parallel_pdf)
    llm_sem = asyncio.Semaphore(args.parallel_llm)
    stats = {"ok": 0, "pdf_fail": 0, "llm_fail": 0, "refused": 0, "no_rating": 0, "total": len(pending)}
    t_start = time.time()

    print(f"\nPipeline: {len(pending)} papers | {args.parallel_llm} LLM | {args.parallel_pdf} PDF")
    print(f"Output: {args.output} | Errors: {args.log}")
    print("-" * 80)

    log_fh = open(args.log, "a")
    out_fh = open(args.output, "a")

    # Initialize browser
    await _get_browser()
    print("Playwright browser ready")

    async def _run(row):
        result = await process_paper(row, pdf_sem, llm_sem)
        out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_fh.flush()

        if result.get("summary"):
            stats["ok"] += 1
            if not result.get("ai_rating"):
                stats["no_rating"] += 1
        elif result.get("error", "").startswith("PDF"):
            stats["pdf_fail"] += 1
        elif result.get("error", "").startswith("REFUSED"):
            stats["refused"] += 1
        else:
            stats["llm_fail"] += 1

        if result.get("error"):
            log_fh.write(f"{datetime.now(timezone.utc).isoformat()} | {result['openreview_id']} | {result['title'][:60]} | {result['error']}\n")
            log_fh.flush()

        done = stats["ok"] + stats["pdf_fail"] + stats["llm_fail"] + stats["refused"]
        elapsed = time.time() - t_start
        rate = done / elapsed if elapsed > 0 else 0
        eta_m = ((stats["total"] - done) / rate / 60) if rate > 0 else 0
        if done % 5 == 0 or done == stats["total"]:
            print(f"  [{done}/{stats['total']}] ok={stats['ok']} pdf_fail={stats['pdf_fail']} llm={stats['llm_fail']} refused={stats['refused']} | {rate:.2f}/s | ETA {eta_m:.0f}m | last: {result['elapsed_s']:.0f}s")

    tasks = [_run(row) for row in pending]
    await asyncio.gather(*tasks)

    out_fh.close()
    log_fh.close()
    if _browser:
        await _browser.close()

    elapsed = time.time() - t_start
    print(f"\n{'='*80}")
    print(f"DONE in {elapsed/60:.1f}m ({elapsed/3600:.1f}h)")
    print(f"  OK: {stats['ok']} | PDF fail: {stats['pdf_fail']} | LLM fail: {stats['llm_fail']} | Refused: {stats['refused']} | No rating: {stats['no_rating']}")
    print(f"  Output: {args.output}")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
