"""
Extract open research problems from top-ranked papers using Claude Opus 4.7
with adaptive thinking enabled.

Direct Anthropic API call via litellm (mirrors the existing `run_opus47.py`
pattern in /app/backend/scripts/). One-shot extraction per paper, full text
input. Outputs to MongoDB collection `open_problems` with one document per
extracted problem, and `open_problems_meta` with one document per paper
(including no-problem markers so reruns skip them).

Run:
    cd /app/backend && python3 -m tools.extract_open_problems --limit 5    # pilot
    cd /app/backend && python3 -m tools.extract_open_problems --limit 100  # full run
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))

from motor.motor_asyncio import AsyncIOMotorClient
import litellm


SYSTEM_PROMPT = """\
You extract open research problems that the *authors of a paper* have
explicitly identified as unsolved, as limitations of their own work,
or as future directions. You do not invent problems, infer them, or
generalize from what would be interesting to study next. You are
ruthlessly selective and prefer returning zero problems over weak ones.

For each qualifying problem you also rate two things, treating yourself
as a third-party reviewer judging the problem on its own merits, not
as the paper's advocate.
"""

USER_PROMPT_TEMPLATE = """\
Here is a paper.

Title: {title}
Authors: {authors}
Abstract: {abstract}

Full text (excerpt):
{body}

Identify the open research problems the authors themselves have flagged
as unsolved, as future work, or as limitations of the present study.

A problem qualifies ONLY if ALL of these hold:
  1. The authors explicitly state it (you can quote a sentence verbatim).
  2. It is distinct from the paper's own contribution - solving it would
     be additional work, not a restatement of what the paper already does.
  3. It is concrete enough that a different research group could pick it
     up without further clarification - i.e. a third reader can understand
     what would need to be done.
  4. It is intelligible standalone - i.e. the problem makes sense to a
     reader who has not read this paper.

DO NOT extract:
  - Vague aspirations ("more work is needed", "future research will
    benefit from", "we hope to study").
  - Restatements of the paper's contributions framed as future direction.
  - Problems entirely scoped to this paper's specific setup (datasets,
    benchmarks, codebase) unless they generalize.
  - Generic field-level platitudes you could state without reading the
    paper ("understand transformers better", "scale to larger models").

For each qualifying problem, return:

  - title:           5-12 words, plain English, mentions the key technical
                     noun. Aim for something a generalist researcher could
                     read at a glance and decide whether they care.
  - description:     2-3 sentences. Sentence 1: state the problem.
                     Sentence 2: explain why it is open / what is stuck.
                     Optional sentence 3: scope or constraint.
  - evidence_quote:  A direct verbatim sentence (max 40 words) from the
                     paper that supports that the authors flagged this.
                     If you cannot find a verbatim quote, do not include
                     the problem.
  - source_section:  One of {{"Limitations", "Future Work", "Discussion",
                     "Conclusion", "Introduction", "Other"}}.
  - scope:           "paper_specific" if it only applies in this paper's
                     setting, "field_general" if a different group could
                     work on it without using this paper's artifacts.

  - impact:          1-10. What does the field gain if this problem is
                     solved? Judge as a third-party reviewer, not as the
                     paper's advocate.
                     Anchors: 1 = trivial / paper-internal cleanup; 3 = a
                     small but real improvement to the subfield; 5 = solid
                     follow-up that a PhD could publish; 7 = significant
                     advance for the subfield, several papers would build
                     on it; 9 = transformative, gates downstream work in
                     multiple groups; 10 = field-changing.
  - impact_reason:   ONE single rich sentence, ~150 chars, naming the
                     concrete benefit or downstream unlock if solved.
                     Style match: "Demonstrated hardware deployment on
                     one platform; the automated calibration concept
                     could reduce engineering effort for aquatic
                     robotics labs, but proprietary VLM dependency
                     limits adoption."

  - difficulty:      1-10. How hard would it be for a competent research
                     group to solve in 1-2 years?
                     Anchors: 1 = mostly engineering, days-weeks of work;
                     3 = a focused PhD chapter; 5 = a PhD thesis; 7 = a
                     multi-year program; 9 = unsolved despite serious
                     effort; 10 = blocked by a deeper open problem
                     (e.g. interpretability of large LMs).
  - difficulty_reason: ONE single rich sentence, ~150 chars, naming the
                     specific bottleneck: missing method, missing data,
                     compute / scale, theoretical limit, or dependence
                     on another open problem.
                     Style match: "Requires familiarity with sim-to-real
                     transfer, system identification, VLM prompting, and
                     RL, but the method itself is algorithmically
                     straightforward."

Use the full 1-10 range. Avoid clustering everything in 5-7. Be willing
to assign 2 or 9 when warranted.

Return at most 5 problems. Return an EMPTY LIST if the paper does not
contain any problem that meets the bar above - this is the expected
outcome for many papers and is preferable to padding.

Output STRICT JSON only, no prose around it:
{{
  "problems": [
    {{
      "title": "...",
      "description": "...",
      "evidence_quote": "...",
      "source_section": "...",
      "scope": "...",
      "impact": 0,
      "impact_reason": "...",
      "difficulty": 0,
      "difficulty_reason": "..."
    }}
  ]
}}
"""

MODEL = "claude-opus-4-8"
MODEL_FULL = f"anthropic/{MODEL}"
MAX_FULL_TEXT_CHARS = 180_000

JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = JSON_BLOCK_RE.search(text)
    if not m:
        raise ValueError("no JSON object found in response")
    return json.loads(m.group(0))


def _slice_full_text(full_text: str, max_chars: int = MAX_FULL_TEXT_CHARS) -> str:
    if len(full_text) <= max_chars:
        return full_text
    head_chars = int(max_chars * 0.30)
    tail_chars = max_chars - head_chars
    return full_text[:head_chars] + "\n\n[... truncated ...]\n\n" + full_text[-tail_chars:]


async def _extract_one(paper: dict, api_key: str) -> tuple:
    body = _slice_full_text(paper.get("full_text") or "")
    user_msg = USER_PROMPT_TEMPLATE.format(
        title=(paper.get("title") or "").strip(),
        authors=", ".join(paper.get("authors") or [])[:300],
        abstract=(paper.get("abstract") or "").strip()[:3000],
        body=body,
    )
    response = await litellm.acompletion(
        model=MODEL_FULL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        api_key=api_key,
        max_tokens=15000,
    )
    text = response.choices[0].message.content or ""
    usage = response.usage
    tokens = {
        "input": getattr(usage, "prompt_tokens", 0) or 0,
        "output": getattr(usage, "completion_tokens", 0) or 0,
    }
    parsed = _extract_json(text)
    if not isinstance(parsed, dict) or "problems" not in parsed:
        raise ValueError(f"malformed response: {repr(text)[:200]}")
    return parsed, tokens


async def _fetch_top_papers(db, limit: int) -> list:
    cursor = db.papers.find(
        {"full_text": {"$exists": True, "$ne": ""}, "score": {"$exists": True}},
        {"id": 1, "title": 1, "authors": 1, "abstract": 1, "categories": 1,
         "category": 1, "published": 1, "full_text": 1, "score": 1, "comparisons": 1},
    ).sort([("score", -1), ("comparisons", -1)]).limit(limit)
    return [doc async for doc in cursor]


async def _already_processed(db, paper_id: str) -> bool:
    return await db.open_problems_meta.count_documents({"paper_id": paper_id}) > 0


async def _persist_result(db, paper: dict, parsed: dict, model: str, run_id: str,
                          elapsed_s: float, tokens: dict):
    problems = parsed.get("problems") or []
    now = datetime.now(timezone.utc).isoformat()

    if problems:
        docs = []
        for p in problems:
            docs.append({
                "id": str(uuid.uuid4()),
                "paper_id": paper["id"],
                "paper_title": paper.get("title"),
                "paper_score": paper.get("score"),
                "paper_categories": paper.get("categories") or (
                    [paper.get("category")] if paper.get("category") else []
                ),
                "paper_published": paper.get("published"),
                "title": p.get("title"),
                "description": p.get("description"),
                "evidence_quote": p.get("evidence_quote"),
                "source_section": p.get("source_section"),
                "scope": p.get("scope"),
                "impact": p.get("impact"),
                "impact_reason": p.get("impact_reason"),
                "difficulty": p.get("difficulty"),
                "difficulty_reason": p.get("difficulty_reason"),
                "model": model,
                "run_id": run_id,
                "extracted_at": now,
            })
        await db.open_problems.insert_many(docs)

    await db.open_problems_meta.update_one(
        {"paper_id": paper["id"]},
        {"$set": {
            "paper_id": paper["id"],
            "paper_title": paper.get("title"),
            "paper_score": paper.get("score"),
            "no_problems": not problems,
            "n_problems": len(problems),
            "extracted_at": now,
            "model": model,
            "run_id": run_id,
            "elapsed_s": elapsed_s,
            "tokens": tokens,
        }},
        upsert=True,
    )
    return len(problems)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--parallel", type=int, default=3,
                        help="number of papers to process concurrently")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in /app/backend/.env", file=sys.stderr)
        sys.exit(2)

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    run_id = str(uuid.uuid4())[:8]
    print(f"[run_id={run_id}] model={MODEL} limit={args.limit} parallel={args.parallel}")

    papers = await _fetch_top_papers(db, args.limit)
    print(f"[run_id={run_id}] {len(papers)} papers fetched (sort: score desc, comparisons desc)")

    if args.sample_only:
        if papers:
            p = papers[0]
            body = _slice_full_text(p.get("full_text") or "")
            msg = USER_PROMPT_TEMPLATE.format(
                title=p["title"], authors=", ".join(p.get("authors") or []),
                abstract=p.get("abstract") or "", body=body,
            )
            print(f"=== {p['title'][:80]} ===")
            print(f"full_text {len(p.get('full_text') or '')} chars -> sliced {len(body)}")
            print("--- USER MSG (first 600 chars) ---")
            print(msg[:600])
        return

    sem = asyncio.Semaphore(args.parallel)
    counters = {"papers": 0, "problems": 0, "failures": []}
    t_start = time.time()

    async def worker(idx: int, paper: dict):
        if not args.force and await _already_processed(db, paper["id"]):
            print(f"[{idx+1}/{len(papers)}] skip (already): {paper['title'][:70]}")
            return
        async with sem:
            t0 = time.time()
            title_short = (paper.get("title") or "")[:70]
            try:
                parsed, tokens = await _extract_one(paper, api_key)
                elapsed = time.time() - t0
                n = await _persist_result(db, paper, parsed, MODEL_FULL, run_id, elapsed, tokens)
                counters["problems"] += n
                counters["papers"] += 1
                tk = (
                    f"in={tokens.get('input', 0):>5} "
                    f"out={tokens.get('output', 0):>4}"
                )
                print(f"[{idx+1}/{len(papers)}] {n:>1}p · {elapsed:>5.1f}s · {tk} · {title_short}")
            except Exception as e:
                elapsed = time.time() - t0
                counters["failures"].append({
                    "paper_id": paper["id"], "title": paper.get("title"),
                    "error": str(e)[:200], "elapsed_s": elapsed,
                })
                print(f"[{idx+1}/{len(papers)}] FAIL · {elapsed:>5.1f}s · {title_short} · {e!r}")

    await asyncio.gather(*[worker(i, p) for i, p in enumerate(papers)])

    elapsed_total = time.time() - t_start
    print()
    print(f"=== run {run_id} done ===")
    print(f"papers processed: {counters['papers']}")
    print(f"problems extracted: {counters['problems']}")
    print(f"failures: {len(counters['failures'])}")
    print(f"total elapsed: {elapsed_total:.1f}s")
    if counters["failures"]:
        print("first failures:")
        for f in counters["failures"][:3]:
            print(" ", f)


if __name__ == "__main__":
    asyncio.run(main())
