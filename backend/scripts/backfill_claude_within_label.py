#!/usr/bin/env python3
"""Backfill Claude matches for within-label pairs that only have GPT/Gemini."""

import asyncio
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

from core.config import DEFAULT_EVALUATION_PROMPT, EMERGENT_LLM_KEY, db
from emergentintegrations.llm.utils import get_integration_proxy_url

PROXY_URL = get_integration_proxy_url() + "/llm"

DATASET_ID = "iclr-2026-within-label"
SOURCE_DATASET_ID = "iclr-2026-validation"
SUMMARIES_PATH = ROOT.parent / "memory" / "iclr_2026_summaries.jsonl"
ABSTRACTS_CACHE = ROOT.parent / "memory" / "iclr_2026_abstracts.jsonl"
OUTPUT_PATH = ROOT.parent / "memory" / "within_label_match_results.jsonl"

MODEL = {
    "name": "claude-opus-4-6",
    "provider": "anthropic",
    "model": "claude-opus-4-6",
    "litellm_model": "claude-opus-4-6",
    "api_key": EMERGENT_LLM_KEY,
    "api_base": PROXY_URL,
    "custom_llm_provider": "openai",
}


def _strip_score_json(text):
    stripped = re.sub(r'\s*```json\s*\n\s*\{.*?"score".*$', '', text, flags=re.DOTALL)
    if stripped != text: return stripped.rstrip()
    stripped = re.sub(r'\s*\{[^{}]*"score".*$', '', text, flags=re.DOTALL)
    return stripped.rstrip()


def build_paper_content(paper):
    abstract = paper.get("abstract", "")
    summary = (paper.get("ai_impact_summary_thinking", "")
               or paper.get("ai_impact_summary_opus46", "")
               or paper.get("ai_impact_summary", ""))
    if summary:
        summary = _strip_score_json(summary)
        return f"Abstract: {abstract}\n\nAI Impact Assessment:\n{summary}"
    return f"Abstract: {abstract}"


def parse_comparison_response(response_text):
    text = response_text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"): text = text[4:]
            text = text.strip()
    if not text.startswith("{"):
        json_match = re.search(r'\{[^{}]*"winner"[^{}]*\}', text, re.DOTALL)
        if json_match: text = json_match.group()
        else: raise ValueError(f"No JSON: {text[:200]}")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        repaired = text.rstrip()
        if not repaired.endswith("}"):
            if repaired.count('"') % 2 == 1: repaired += '"'
            repaired += "}"
        result = json.loads(repaired)
    if "winner" not in result or result["winner"] not in ("paper1", "paper2"):
        raise ValueError(f"Invalid: {result}")
    return result


async def run_one(pair_uuid, label, paper1, paper2, uuid_1, uuid_2, oid_1, oid_2,
                  sem, output_file, output_lock, stats):
    async with sem:
        system_msg = DEFAULT_EVALUATION_PROMPT["system_prompt"]
        user_template = DEFAULT_EVALUATION_PROMPT["user_prompt"]
        p1_content = build_paper_content(paper1)
        p2_content = build_paper_content(paper2)

        flipped = random.random() < 0.5
        if flipped:
            prompt_p1, prompt_p2 = paper2, paper1
            prompt_c1, prompt_c2 = p2_content, p1_content
        else:
            prompt_p1, prompt_p2 = paper1, paper2
            prompt_c1, prompt_c2 = p1_content, p2_content

        prompt = user_template.format(
            paper1_title=prompt_p1["title"], paper1_content=prompt_c1,
            paper2_title=prompt_p2["title"], paper2_content=prompt_c2,
        )

        params = {
            "model": MODEL["litellm_model"],
            "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
            "api_key": MODEL["api_key"],
            "api_base": MODEL["api_base"],
            "custom_llm_provider": MODEL["custom_llm_provider"],
            "max_tokens": 800,
            "temperature": 0.3,
            "timeout": 60,
        }

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
                winner_oid = oid_2 if flipped else oid_1
            else:
                winner_oid = oid_1 if flipped else oid_2
            winner_uuid = uuid_2 if winner_oid == oid_2 else uuid_1

            elapsed = time.time() - t0
            tokens_in = resp.usage.prompt_tokens if resp.usage else 0
            tokens_out = resp.usage.completion_tokens if resp.usage else 0
            reasoning = parsed.get("reasoning", "")

            jsonl_result = {
                "id_1": oid_1, "id_2": oid_2, "label": label,
                "winner": winner_oid, "model": MODEL["name"],
                "flipped": flipped, "reasoning": reasoning,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "elapsed_s": round(elapsed, 2),
            }
            db_doc = {
                "id": match_id, "dataset_id": DATASET_ID,
                "paper1_id": uuid_1, "paper2_id": uuid_2,
                "winner_id": winner_uuid,
                "model_used": {"provider": MODEL["provider"], "model": MODEL["model"]},
                "reasoning": reasoning, "content_mode": "abstract_plus_summary",
                "label": label, "completed": True, "failed": False,
                "created_at": now, "tokens": {"input_est": tokens_in, "output_est": tokens_out},
                "flipped": flipped,
            }

            async with output_lock:
                output_file.write(json.dumps(jsonl_result) + "\n")
                output_file.flush()
            await db.validation_matches.insert_one(db_doc)
            stats["ok"] += 1

        except Exception as e:
            elapsed = time.time() - t0
            stats["failed"] += 1
            if "rate" in str(e).lower() or "429" in str(e):
                stats["rate_limited"] += 1

        stats["total"] += 1
        if stats["total"] % 50 == 0:
            elapsed_total = time.time() - stats["start_time"]
            rate = stats["total"] / elapsed_total * 3600
            eta = (stats["target"] - stats["total"]) / (rate / 3600) if rate > 0 else 0
            print(f"  [{stats['total']:>6}/{stats['target']}] ok={stats['ok']} fail={stats['failed']} rate={rate:.0f}/hr ETA={eta/60:.0f}m")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    print("Claude Backfill — Within-Label")
    print("=" * 50)

    # Find pairs without Claude
    from collections import defaultdict
    pair_models = defaultdict(set)
    pair_labels = {}
    async for doc in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "model_used": 1, "label": 1},
    ):
        pair = tuple(sorted([doc["paper1_id"], doc["paper2_id"]]))
        m = doc.get("model_used", {})
        pair_models[pair].add(m.get("model", "?") if isinstance(m, dict) else str(m))
        if pair not in pair_labels:
            pair_labels[pair] = doc.get("label", "")

    need_claude = [(p, pair_labels.get(p, "")) for p, models in pair_models.items()
                   if "claude-opus-4-6" not in models]
    print(f"Pairs needing Claude: {len(need_claude)}")

    # Load paper data
    oid_to_uuid = {}
    uuid_to_oid = {}
    async for doc in db.validation_papers.find(
        {"dataset_id": SOURCE_DATASET_ID}, {"_id": 0, "id": 1, "openreview_id": 1}
    ):
        oid_to_uuid[doc["openreview_id"]] = doc["id"]
        uuid_to_oid[doc["id"]] = doc["openreview_id"]

    summaries = {}
    with open(SUMMARIES_PATH) as f:
        for line in f:
            doc = json.loads(line)
            oid = doc.get("openreview_id")
            if oid and doc.get("summary"):
                summaries[oid] = doc

    abstracts = {}
    if ABSTRACTS_CACHE.exists():
        with open(ABSTRACTS_CACHE) as f:
            for line in f:
                try:
                    doc = json.loads(line)
                    if doc.get("status") == "ok" and doc.get("abstract"):
                        abstracts[doc["openreview_id"]] = doc["abstract"]
                except: continue

    # Build runnable list
    runnable = []
    for (uuid_1, uuid_2), label in need_claude:
        oid_1 = uuid_to_oid.get(uuid_1)
        oid_2 = uuid_to_oid.get(uuid_2)
        if oid_1 and oid_2 and oid_1 in summaries and oid_2 in summaries:
            p1 = {"title": summaries[oid_1]["title"], "abstract": abstracts.get(oid_1, ""),
                   "ai_impact_summary_thinking": summaries[oid_1]["summary"]}
            p2 = {"title": summaries[oid_2]["title"], "abstract": abstracts.get(oid_2, ""),
                   "ai_impact_summary_thinking": summaries[oid_2]["summary"]}
            runnable.append((uuid_1, uuid_2, label, p1, p2, oid_1, oid_2))

    if args.limit > 0:
        runnable = runnable[:args.limit]

    print(f"Runnable: {len(runnable)}")
    print(f"Parallelism: {args.parallel}")
    est = len(runnable) / args.parallel * 5 / 3600
    print(f"Est: ~{est:.1f} hours")

    if args.dry_run:
        print("[DRY RUN]")
        return

    sem = asyncio.Semaphore(args.parallel)
    output_lock = asyncio.Lock()
    stats = {"ok": 0, "failed": 0, "total": 0, "target": len(runnable),
             "rate_limited": 0, "start_time": time.time()}

    with open(OUTPUT_PATH, "a") as out_f:
        tasks = [
            run_one(f"{u1}|{u2}", label, p1, p2, u1, u2, o1, o2,
                    sem, out_f, output_lock, stats)
            for u1, u2, label, p1, p2, o1, o2 in runnable
        ]
        await asyncio.gather(*tasks)

    elapsed = time.time() - stats["start_time"]
    print(f"\nDONE in {elapsed/3600:.1f}h — ok={stats['ok']} fail={stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
