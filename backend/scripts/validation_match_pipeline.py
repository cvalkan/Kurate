#!/usr/bin/env python3
"""
Validation Match Pipeline — Parallelized & Resumable

Runs 58K+ pairwise comparisons from a CSV of (id_1, id_2) pairs using
round-robin model selection (GPT-5.4, Claude Opus 4.6, Gemini 3 Pro).

Uses the SAME prompt, content format, anonymization, and response parsing
as the live tournament system — imported directly, not reimplemented.

Outputs to both JSONL (for analysis) and MongoDB validation_matches (for
consistency with existing ICLR 2024/25 validation datasets).

Usage:
  python3 scripts/validation_match_pipeline.py --dry-run
  python3 scripts/validation_match_pipeline.py --parallel 50
"""

import asyncio
import csv
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False

# ── imports from live system ──
from core.config import DEFAULT_EVALUATION_PROMPT, EMERGENT_LLM_KEY, db
from emergentintegrations.llm.utils import get_integration_proxy_url

PROXY_URL = get_integration_proxy_url() + "/llm"
OPENAI_KEY_DIRECT = os.environ.get("OPENAI_API_KEY_DIRECT")
ANTHROPIC_DIRECT_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ── paths ──
MODELS = [
    {
        "name": "gpt-5.4",
        "provider": "openai",
        "model": "gpt-5.4",
        "litellm_model": "gpt-5.4",
        "api_key": OPENAI_KEY_DIRECT,
        "api_base": None,
        "custom_llm_provider": None,
    },
    {
        "name": "claude-opus-4-6",
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "litellm_model": "anthropic/claude-opus-4-6",
        "api_key": ANTHROPIC_DIRECT_KEY,
        "api_base": None,
        "custom_llm_provider": None,
    },
    {
        "name": "gemini-3-pro-preview",
        "provider": "gemini",
        "model": "gemini-3-pro-preview",
        "litellm_model": "gemini/gemini-3-pro-preview",
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    },
]
CSV_PATH = Path("/app/memory/sampled_matches.csv")
SUMMARIES_PATH = ROOT.parent / "memory" / "iclr_2026_summaries.jsonl"
ABSTRACTS_CACHE = ROOT.parent / "memory" / "iclr_2026_abstracts.jsonl"
OUTPUT_PATH = ROOT.parent / "memory" / "validation_match_results.jsonl"

DATASET_ID = "iclr-2026-validation"

# ── models (round-robin) ──
MODELS = [
    {
        "name": "gpt-5.4",
        "provider": "openai",
        "model": "gpt-5.4",
        "litellm_model": "gpt-5.4",
        "api_key": OPENAI_KEY_DIRECT,
        "api_base": None,
        "custom_llm_provider": None,
    },
    {
        "name": "claude-opus-4-6",
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "litellm_model": "claude-opus-4-6",
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    },
    {
        "name": "gemini-3-pro-preview",
        "provider": "gemini",
        "model": "gemini-3-pro-preview",
        "litellm_model": "gemini/gemini-3-pro-preview",
        "api_key": EMERGENT_LLM_KEY,
        "api_base": PROXY_URL,
        "custom_llm_provider": "openai",
    },
]

_model_counter = 0


def pick_model() -> dict:
    global _model_counter
    m = MODELS[_model_counter % len(MODELS)]
    _model_counter += 1
    return m


# ── content building: IDENTICAL to compare_papers() lines 592-598 ──

def _strip_score_json(text: str) -> str:
    """Remove trailing JSON score block (```json {...} ```) from summaries.
    
    The ICLR 2026 batch summaries include a numeric rating JSON at the end
    (e.g. {"score": 3.5, ...}). This must NOT be fed into pairwise comparisons
    as it would let the judge simply compare numbers instead of reasoning.
    The live system's summaries do not include these scores.
    """
    # Match ```json block (complete or truncated) at end
    stripped = re.sub(r'\s*```json\s*\n\s*\{.*?"score".*$', '', text, flags=re.DOTALL)
    if stripped != text:
        return stripped.rstrip()
    # Match bare { ... } with "score" at end (no code fence, complete or truncated)
    stripped = re.sub(r'\s*\{[^{}]*"score".*$', '', text, flags=re.DOTALL)
    return stripped.rstrip()


def build_paper_content(paper: dict) -> str:
    abstract = paper.get("abstract", "")
    summary = (paper.get("ai_impact_summary_thinking", "")
               or paper.get("ai_impact_summary_opus46", "")
               or paper.get("ai_impact_summary", ""))
    if summary:
        summary = _strip_score_json(summary)
        return f"Abstract: {abstract}\n\nAI Impact Assessment:\n{summary}"
    return f"Abstract: {abstract}"


# ── response parsing: IDENTICAL to compare_papers() lines 676-711, with truncation repair ──

def parse_comparison_response(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    if not text.startswith("{"):
        json_match = re.search(r'\{[^{}]*"winner"[^{}]*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group()
        else:
            raise ValueError(f"No JSON found in response: {text[:200]}")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        repaired = text.rstrip()
        if not repaired.endswith("}"):
            quote_count = repaired.count('"') - repaired.count('\\"')
            if quote_count % 2 == 1:
                repaired += '"'
            repaired += "}"
        result = json.loads(repaired)
    if "winner" not in result or result["winner"] not in ("paper1", "paper2"):
        raise ValueError(f"Invalid response format: {result}")
    return result


# ── data loading ──

def load_matches(csv_path: str) -> list:
    with open(csv_path) as f:
        return [(r["id_1"], r["id_2"]) for r in csv.DictReader(f)]


def load_summaries(jsonl_path: str) -> dict:
    papers = {}
    with open(jsonl_path) as f:
        for line in f:
            doc = json.loads(line)
            oid = doc.get("openreview_id")
            if oid and doc.get("summary"):
                papers[oid] = doc
    return papers


def load_completed(output_path: str) -> set:
    completed = set()
    if not os.path.exists(output_path):
        return completed
    with open(output_path) as f:
        for line in f:
            try:
                r = json.loads(line)
                completed.add(f"{r['id_1']}|{r['id_2']}")
            except (json.JSONDecodeError, KeyError):
                continue
    return completed


async def load_completed_from_db(oid_to_uuid: dict) -> set:
    """Load completed pairs from MongoDB as the canonical source of truth.

    Returns a set of "{oid_1}|{oid_2}" keys (unordered: a pair A-B counts as
    completed regardless of which side was paper1). Prevents duplicate LLM
    calls after a crash where the JSONL tail wasn't flushed.
    """
    uuid_to_oid = {v: k for k, v in oid_to_uuid.items()}
    completed = set()
    cursor = db.validation_matches.find(
        {"dataset_id": DATASET_ID, "completed": True, "failed": {"$ne": True}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1},
    )
    async for doc in cursor:
        o1 = uuid_to_oid.get(doc["paper1_id"])
        o2 = uuid_to_oid.get(doc["paper2_id"])
        if not o1 or not o2:
            continue
        # Mark both orderings completed — matching how pairs are generated.
        completed.add(f"{o1}|{o2}")
        completed.add(f"{o2}|{o1}")
    return completed


# ── DB seeding ──

async def seed_validation_papers(summaries: dict, abstracts: dict) -> dict:
    """Seed validation_papers collection. Returns {openreview_id: uuid} mapping."""
    # Check if already seeded
    existing = await db.validation_papers.count_documents({"dataset_id": DATASET_ID})
    if existing > 0:
        # Load existing mapping
        oid_to_uuid = {}
        async for doc in db.validation_papers.find(
            {"dataset_id": DATASET_ID},
            {"_id": 0, "id": 1, "openreview_id": 1},
        ):
            oid_to_uuid[doc["openreview_id"]] = doc["id"]
        print(f"   Already seeded: {len(oid_to_uuid)} papers")
        return oid_to_uuid

    # Seed fresh
    docs = []
    oid_to_uuid = {}
    for oid, summary_doc in summaries.items():
        paper_uuid = str(uuid.uuid4())
        oid_to_uuid[oid] = paper_uuid
        docs.append({
            "id": paper_uuid,
            "dataset_id": DATASET_ID,
            "openreview_id": oid,
            "title": summary_doc.get("title", ""),
            "abstract": abstracts.get(oid, ""),
            "ai_impact_summary_thinking": summary_doc.get("summary", ""),
            "ai_rating": summary_doc.get("ai_rating"),
            "source": "iclr_openreview",
            "year": 2026,
            "label": summary_doc.get("label", ""),
            "status": summary_doc.get("status", ""),
            "reviewer_scores": summary_doc.get("reviewer_scores"),
        })

    if docs:
        await db.validation_papers.insert_many(docs, ordered=False)
    print(f"   Seeded {len(docs)} papers")
    return oid_to_uuid


# ── single comparison ──

async def run_comparison(
    id_1: str, id_2: str,
    paper1: dict, paper2: dict,
    uuid_1: str, uuid_2: str,
    sem: asyncio.Semaphore,
    output_file,
    output_lock: asyncio.Lock,
    stats: dict,
) -> None:
    async with sem:
        model = pick_model()
        system_msg = DEFAULT_EVALUATION_PROMPT["system_prompt"]
        user_template = DEFAULT_EVALUATION_PROMPT["user_prompt"]

        p1_content = build_paper_content(paper1)
        p2_content = build_paper_content(paper2)

        # Random 50% flip for positional bias (same as scheduler.py line 1316)
        flipped = random.random() < 0.5
        if flipped:
            prompt_p1, prompt_p2 = paper2, paper1
            prompt_c1, prompt_c2 = p2_content, p1_content
        else:
            prompt_p1, prompt_p2 = paper1, paper2
            prompt_c1, prompt_c2 = p1_content, p2_content

        prompt = user_template.format(
            paper1_title=prompt_p1["title"],
            paper1_content=prompt_c1,
            paper2_title=prompt_p2["title"],
            paper2_content=prompt_c2,
        )

        params = {
            "model": model["litellm_model"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "api_key": model["api_key"],
            "max_tokens": 800,
        }
        if model["name"] != "gpt-5.4":
            params["temperature"] = 0.3
        if model["api_base"]:
            params["api_base"] = model["api_base"]
        if model["custom_llm_provider"]:
            params["custom_llm_provider"] = model["custom_llm_provider"]

        t0 = time.time()
        match_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: litellm.completion(**params))
            raw = resp.choices[0].message.content

            parsed = parse_comparison_response(raw)

            winner_raw = parsed["winner"]
            if winner_raw == "paper1":
                winner_oid = id_2 if flipped else id_1
            else:
                winner_oid = id_1 if flipped else id_2

            winner_uuid = uuid_2 if winner_oid == id_2 else uuid_1
            elapsed = time.time() - t0
            tokens_in = resp.usage.prompt_tokens if resp.usage else 0
            tokens_out = resp.usage.completion_tokens if resp.usage else 0
            reasoning = parsed.get("reasoning", "")

            # JSONL result (uses openreview_ids)
            jsonl_result = {
                "id_1": id_1,
                "id_2": id_2,
                "winner": winner_oid,
                "model": model["name"],
                "flipped": flipped,
                "reasoning": reasoning,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "elapsed_s": round(elapsed, 2),
            }

            # DB result (uses UUIDs, matches existing validation_matches schema)
            db_doc = {
                "id": match_id,
                "dataset_id": DATASET_ID,
                "paper1_id": uuid_1,
                "paper2_id": uuid_2,
                "winner_id": winner_uuid,
                "model_used": {"provider": model["provider"], "model": model["model"]},
                "reasoning": reasoning,
                "content_mode": "abstract_plus_summary",
                "completed": True,
                "failed": False,
                "created_at": now,
                "tokens": {"input_est": tokens_in, "output_est": tokens_out},
                "flipped": flipped,
            }

            async with output_lock:
                output_file.write(json.dumps(jsonl_result) + "\n")
                output_file.flush()

            await db.validation_matches.insert_one(db_doc)

            stats["ok"] += 1
            stats["tokens_in"] += tokens_in
            stats["tokens_out"] += tokens_out
            stats["by_model"][model["name"]] = stats["by_model"].get(model["name"], 0) + 1

        except Exception as e:
            elapsed = time.time() - t0
            err_str = str(e)[:300]

            jsonl_result = {
                "id_1": id_1,
                "id_2": id_2,
                "winner": None,
                "model": model["name"],
                "flipped": flipped,
                "error": err_str,
                "elapsed_s": round(elapsed, 2),
            }

            db_doc = {
                "id": match_id,
                "dataset_id": DATASET_ID,
                "paper1_id": uuid_1,
                "paper2_id": uuid_2,
                "model_used": {"provider": model["provider"], "model": model["model"]},
                "content_mode": "abstract_plus_summary",
                "completed": False,
                "failed": True,
                "error": err_str,
                "created_at": now,
                "flipped": flipped,
            }

            async with output_lock:
                output_file.write(json.dumps(jsonl_result) + "\n")
                output_file.flush()

            try:
                await db.validation_matches.insert_one(db_doc)
            except Exception:
                pass

            stats["failed"] += 1
            if "rate" in err_str.lower() or "429" in err_str:
                stats["rate_limited"] += 1

        stats["total"] += 1
        if stats["total"] % 50 == 0:
            elapsed_total = time.time() - stats["start_time"]
            rate = stats["total"] / elapsed_total * 3600
            eta = (stats["target"] - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(
                f"  [{stats['total']:>6}/{stats['target']}]"
                f"  ok={stats['ok']} fail={stats['failed']}"
                f"  rate={rate:.0f}/hr"
                f"  ETA={eta/60:.0f}m"
                f"  tokens={stats['tokens_in']+stats['tokens_out']:,}"
                f"  models={stats['by_model']}"
            )


# ── main ──

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validation match pipeline")
    parser.add_argument("--parallel", type=int, default=30, help="Max concurrent LLM calls")
    parser.add_argument("--dry-run", action="store_true", help="Load data and report stats without running")
    parser.add_argument("--limit", type=int, default=0, help="Limit matches (0 = all)")
    parser.add_argument("--csv", type=str, default=str(CSV_PATH), help="Input CSV path")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Output JSONL path")
    args = parser.parse_args()

    print("=" * 60)
    print("Validation Match Pipeline")
    print("=" * 60)

    # 1. Load matches
    print(f"\n1. Loading matches from {args.csv}")
    matches = load_matches(args.csv)
    print(f"   {len(matches):,} pairs loaded")

    # 2. Load summaries
    print(f"\n2. Loading summaries from {SUMMARIES_PATH}")
    summaries = load_summaries(SUMMARIES_PATH)
    print(f"   {len(summaries):,} papers with summaries")

    # 3. Filter runnable matches
    runnable = []
    skipped = 0
    for id_1, id_2 in matches:
        if id_1 in summaries and id_2 in summaries:
            runnable.append((id_1, id_2))
        else:
            skipped += 1
    print(f"\n3. Runnable matches: {len(runnable):,} (skipped {skipped} missing summaries)")

    # 4. Resume check — query MongoDB after seeding (needs oid_to_uuid)
    # (moved below — we need oid_to_uuid first)
    completed_jsonl = load_completed(args.output)
    print(f"\n4. JSONL resume markers: {len(completed_jsonl):,}")

    if args.limit > 0:
        print(f"   (--limit {args.limit} will be applied after DB-based resume check)")

    # 5. Load abstracts
    print(f"\n5. Loading abstracts from {ABSTRACTS_CACHE}")
    abstracts = {}
    if ABSTRACTS_CACHE.exists():
        with open(ABSTRACTS_CACHE) as f:
            for line in f:
                try:
                    doc = json.loads(line)
                    if doc.get("status") == "ok" and doc.get("abstract"):
                        abstracts[doc["openreview_id"]] = doc["abstract"]
                except (json.JSONDecodeError, KeyError):
                    continue
    print(f"   {len(abstracts)} abstracts loaded")

    # 6. Seed validation_papers in DB
    print(f"\n6. Seeding validation_papers (dataset_id={DATASET_ID})")
    oid_to_uuid = await seed_validation_papers(summaries, abstracts)

    # 6b. DB-based resume check (canonical source of truth)
    print("\n6b. DB resume check (canonical)...")
    completed_db = await load_completed_from_db(oid_to_uuid)
    # Union JSONL + DB markers to be safe (JSONL may reference pairs not in DB yet)
    completed_union = completed_jsonl | completed_db
    remaining = [(a, b) for a, b in runnable if f"{a}|{b}" not in completed_union]
    print(f"   DB-completed pairs: {len(completed_db)//2:,} (×2 for both orderings)")
    print(f"   JSONL-only markers: {len(completed_jsonl - completed_db):,}")
    print(f"   Runnable: {len(runnable):,}  Remaining: {len(remaining):,}")

    if args.limit > 0:
        remaining = remaining[:args.limit]
        print(f"   Limited to {args.limit} matches")

    # 7. Build paper dicts
    print(f"\n7. Building paper dicts...")
    paper_dicts = {}
    needed_ids = set()
    for id_1, id_2 in remaining:
        needed_ids.add(id_1)
        needed_ids.add(id_2)
    for oid in needed_ids:
        summary_doc = summaries[oid]
        paper_dicts[oid] = {
            "title": summary_doc["title"],
            "abstract": abstracts.get(oid, ""),
            "ai_impact_summary_thinking": summary_doc["summary"],
        }
    has_abstract = sum(1 for p in paper_dicts.values() if p["abstract"])
    print(f"   {len(paper_dicts):,} papers ({has_abstract} with abstracts)")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Models: {', '.join(m['name'] for m in MODELS)}")
    print(f"Parallelism: {args.parallel}")
    print(f"Matches to run: {len(remaining):,}")
    est_hours = len(remaining) / args.parallel * 5 / 3600
    print(f"Est. time: ~{est_hours:.1f} hours")
    print(f"Output JSONL: {args.output}")
    print(f"Output DB: validation_matches (dataset_id={DATASET_ID})")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n[DRY RUN] Exiting.")
        return

    if not remaining:
        print("\nAll matches already completed!")
        return

    # 8. Run comparisons
    print(f"\n8. Starting {len(remaining):,} comparisons...")
    sem = asyncio.Semaphore(args.parallel)
    output_lock = asyncio.Lock()
    stats = {
        "ok": 0, "failed": 0, "total": 0, "target": len(remaining),
        "tokens_in": 0, "tokens_out": 0, "rate_limited": 0,
        "by_model": {}, "start_time": time.time(),
    }

    with open(args.output, "a") as out_f:
        tasks = [
            run_comparison(
                id_1, id_2,
                paper_dicts[id_1], paper_dicts[id_2],
                oid_to_uuid[id_1], oid_to_uuid[id_2],
                sem, out_f, output_lock, stats,
            )
            for id_1, id_2 in remaining
        ]
        await asyncio.gather(*tasks)

    elapsed = time.time() - stats["start_time"]
    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed / 3600:.1f} hours")
    print(f"  OK: {stats['ok']:,}")
    print(f"  Failed: {stats['failed']:,}")
    print(f"  Rate limited: {stats['rate_limited']}")
    print(f"  Tokens: {stats['tokens_in'] + stats['tokens_out']:,}")
    print(f"  By model: {stats['by_model']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
