#!/usr/bin/env python3
"""
Full fairness experiment: domain-specific summaries (Opus 4.6) + domain-specific judge prompt.
1. Generate fairness-focused summaries for all 68 papers
2. Delete old incomplete fairness_v1 matches
3. Run tournament with fairness summaries + fairness judge prompt
"""
import asyncio, os, sys, uuid, time
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from emergentintegrations.llm.chat import LlmChat, UserMessage
from services.llm import compare_papers, _pick_round_robin_model
from core.config import EMERGENT_LLM_KEY, logger
from concurrent.futures import ThreadPoolExecutor

DS = "iclr-fairness"
SUMMARY_FIELD = "ai_impact_summary_fairness_v1"
TARGET_MODE = "abstract_plus_summary:fairness_v1"
PARALLEL = 8

client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client["test_database"]
_executor = ThreadPoolExecutor(max_workers=50)

FAIRNESS_SUMMARY_PROMPT = {
    "system_prompt": """You are a scientific impact analyst specializing in algorithmic fairness, AI safety, and the societal impact of machine learning. Your task is to write a detailed assessment of a research paper that will be used in a pairwise tournament to compare papers.

Write up to 1000 words. Structure your assessment around:

1. **Core Contribution**: What is the main novelty? Is it a new fairness definition, an impossibility result, a practical mitigation method, a benchmark, or a theoretical framework?
2. **Fairness Formalization**: How does the paper define and measure fairness? Does it engage with the tension between competing fairness criteria (individual vs group, equalized odds vs demographic parity, etc.)?
3. **Methodological Rigor**: How sound is the approach? Are experiments on realistic datasets with real protected attributes, or only synthetic/toy settings? Are baselines appropriate?
4. **Practical Impact**: Could this actually change how systems are built or audited? Does it consider deployment constraints, regulatory frameworks, or the gap between theory and practice?
5. **Breadth & Novelty**: Does this advance the field in a meaningful way, or is it an incremental combination of known techniques? Could it influence adjacent areas (NLP, CV, RL, policy)?
6. **Limitations**: What are the key weaknesses — narrow scope, unrealistic assumptions, missing comparisons, or potential for misuse?

Be specific and analytical. Your assessment should give enough detail for another evaluator to judge this paper's quality without reading it.""",

    "user_prompt": """Write a scientific impact assessment for the following paper on fairness/safety in ML:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words):""",
}

FAIRNESS_JUDGE_PROMPT = {
    "system_prompt": """You are a scientific paper evaluator. Your task is to compare two papers and determine which has higher potential scientific impact.

These papers are from the domain of algorithmic fairness, AI safety, and societal impact of ML. Consider:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor — for this domain, pay attention to whether fairness definitions are rigorous, experiments use realistic datasets with real protected attributes, and whether the method could actually be deployed
4. Breadth of impact across fields
5. Timeliness and relevance

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation of why experts would prefer this paper (max 150 words)"}""",

    "user_prompt": """Compare these two papers for scientific impact:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper has higher estimated scientific impact? Respond with JSON only.""",
}


async def phase1_generate_summaries():
    """Generate fairness-specific summaries using Opus 4.6."""
    papers = await db.validation_papers.find({"dataset_id": DS}, {"_id": 0}).to_list(5000)
    missing = [p for p in papers if not p.get(SUMMARY_FIELD)]
    print(f"Phase 1: {len(missing)}/{len(papers)} papers need fairness-specific summaries")

    if not missing:
        print("All papers already have fairness summaries!")
        return

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0

    async def gen_one(paper):
        nonlocal completed, failed
        async with sem:
            full_text = paper.get("full_text", "")
            abstract = paper.get("abstract", "")
            if full_text:
                content = f"Abstract: {abstract[:1500]}\n\nFull Paper Text:\n{full_text[:40000]}"
            elif abstract:
                content = f"Abstract: {abstract[:3000]}"
            else:
                failed += 1
                return

            prompt = FAIRNESS_SUMMARY_PROMPT["user_prompt"].format(
                title=paper.get("title", "Untitled"),
                content=content,
            )

            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"fairness-sum-{uuid.uuid4()}",
                system_message=FAIRNESS_SUMMARY_PROMPT["system_prompt"],
            ).with_model("anthropic", "claude-opus-4-6")

            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    _executor,
                    lambda: asyncio.run(chat.send_message(UserMessage(text=prompt))),
                )
                if response and str(response).strip():
                    summary = str(response).strip()
                    await db.validation_papers.update_one(
                        {"dataset_id": DS, "id": paper["id"]},
                        {"$set": {SUMMARY_FIELD: summary}},
                    )
                    completed += 1
                    print(f"  [{completed}/{len(missing)}] {paper.get('title','')[:60]}")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  FAILED: {e}")

    await asyncio.gather(*[gen_one(p) for p in missing], return_exceptions=True)
    print(f"Phase 1 done: {completed} generated, {failed} failed")


async def phase2_delete_old():
    """Delete old incomplete fairness_v1 matches."""
    result = await db.validation_matches.delete_many({
        "dataset_id": DS, "content_mode": TARGET_MODE
    })
    print(f"\nPhase 2: Deleted {result.deleted_count} old fairness_v1 matches")


async def phase3_run_tournament():
    """Run tournament with fairness summaries + fairness judge prompt."""
    papers = await db.validation_papers.find({"dataset_id": DS}, {"_id": 0}).to_list(5000)
    lookup = {p["id"]: p for p in papers}
    pids = list(lookup.keys())

    # Use same pair selection as regular tournament
    from collections import Counter
    match_counts = Counter()
    compared = set()

    pairs = []
    min_per_paper = 8
    max_pairs = 500

    for _ in range(max_pairs):
        if len(pairs) >= max_pairs:
            break
        neediest = sorted(pids, key=lambda p: match_counts[p])
        placed = False
        for p1 in neediest:
            if match_counts[p1] >= min_per_paper and all(match_counts[p] >= min_per_paper for p in pids):
                break
            candidates = [p for p in pids if p != p1 and tuple(sorted([p1, p])) not in compared]
            if not candidates:
                continue
            candidates.sort(key=lambda p: match_counts[p])
            p2 = candidates[0]
            key = tuple(sorted([p1, p2]))
            pairs.append((p1, p2))
            compared.add(key)
            match_counts[p1] += 1
            match_counts[p2] += 1
            placed = True
            break
        if not placed:
            break

    import random
    attempts = 0
    while len(pairs) < max_pairs and attempts < max_pairs * 3:
        attempts += 1
        weights = [1.0 / (match_counts[p] + 1) for p in pids]
        p1 = random.choices(pids, weights=weights, k=1)[0]
        candidates = [p for p in pids if p != p1 and tuple(sorted([p1, p])) not in compared]
        if not candidates:
            continue
        p2 = random.choice(candidates)
        key = tuple(sorted([p1, p2]))
        pairs.append((p1, p2))
        compared.add(key)
        match_counts[p1] += 1
        match_counts[p2] += 1

    print(f"\nPhase 3: Running {len(pairs)} matches with fairness summaries + fairness judge")

    sem = asyncio.Semaphore(PARALLEL)
    completed = 0
    failed = 0
    start = time.time()

    async def run_one(p1_id, p2_id):
        nonlocal completed, failed
        # Random presentation order
        if random.random() < 0.5:
            p1_id, p2_id = p2_id, p1_id

        async with sem:
            p1 = lookup[p1_id]
            p2 = lookup[p2_id]

            # Swap in fairness-specific summaries
            s1 = p1.get(SUMMARY_FIELD, "")
            s2 = p2.get(SUMMARY_FIELD, "")
            if not s1 or not s2:
                failed += 1
                return

            p1_copy = {**p1, "ai_impact_summary": s1}
            p2_copy = {**p2, "ai_impact_summary": s2}

            try:
                result = await compare_papers(
                    p1_copy, p2_copy,
                    FAIRNESS_JUDGE_PROMPT,
                    content_mode="abstract_plus_summary",
                )
                if result and not result.get("failed"):
                    winner_key = result.get("winner", "paper1")
                    doc = {
                        "id": str(uuid.uuid4()),
                        "dataset_id": DS,
                        "content_mode": TARGET_MODE,
                        "paper1_id": p1_id,
                        "paper2_id": p2_id,
                        "winner_id": p1_id if winner_key == "paper1" else p2_id,
                        "reasoning": result.get("reasoning", ""),
                        "model_used": result.get("model_used", {}),
                        "tokens": result.get("tokens", {}),
                        "completed": True,
                        "failed": False,
                        "prompt_tag": "fairness_v1",
                        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    }
                    doc.pop("_id", None)
                    await db.validation_matches.insert_one(doc)
                    completed += 1
                    if completed % 50 == 0:
                        el = time.time() - start
                        print(f"  Progress: {completed}/{len(pairs)} ({completed/el*60:.0f}/min)")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"  Match error: {e}")

    await asyncio.gather(*[run_one(p1, p2) for p1, p2 in pairs], return_exceptions=True)
    elapsed = time.time() - start
    print(f"Phase 3 done: {completed}/{len(pairs)} ({failed} failed) in {elapsed:.0f}s")


async def main():
    print("=== Full Fairness Experiment: Domain Summaries + Domain Judge ===\n")
    await phase1_generate_summaries()
    await phase2_delete_old()
    await phase3_run_tournament()
    client.close()

asyncio.run(main())
