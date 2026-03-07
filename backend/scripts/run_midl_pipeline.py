#!/usr/bin/env python3
"""Run the full MIDL pipeline: thinking summaries → pairwise matches → single-item scoring."""
import asyncio, json, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

DATASET_ID = "midl-medical-imaging"
NUM_PAIRS = 607  # ~15 matches per paper for 81 papers

async def step1_generate_thinking_summaries():
    """Generate Opus 4.6 Thinking summaries for papers that don't have them."""
    from core.config import db, EMERGENT_LLM_KEY
    from services.llm import generate_precomparison_impact_summary
    
    THINKING_MODEL = {"provider": "anthropic", "model": "claude-opus-4-6",
                      "extra_params": {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 10000}}}}
    
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID, "ai_impact_summary_thinking": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "full_text": 1}
    ).to_list(500)
    papers = [p for p in papers if p.get("abstract") or p.get("full_text")]
    
    print(f"[Step 1] Generating thinking summaries for {len(papers)} papers...", flush=True)
    if not papers:
        print("[Step 1] All summaries already exist", flush=True)
        return
    
    sem = asyncio.Semaphore(3)
    done = 0
    
    async def gen_one(paper):
        nonlocal done
        async with sem:
            try:
                result = await generate_precomparison_impact_summary(paper, model_override=THINKING_MODEL)
                if result and result.get("summary"):
                    await db.validation_papers.update_one(
                        {"id": paper["id"], "dataset_id": DATASET_ID},
                        {"$set": {"ai_impact_summary_thinking": result["summary"]}}
                    )
                    done += 1
                    if done % 5 == 0:
                        print(f"  [Step 1] {done}/{len(papers)}", flush=True)
            except Exception as e:
                print(f"  [Step 1] Error: {str(e)[:60]}", flush=True)
    
    await asyncio.gather(*[gen_one(p) for p in papers], return_exceptions=True)
    print(f"[Step 1] Complete: {done}/{len(papers)} summaries generated", flush=True)


async def step2_run_pairwise_matches():
    """Run pairwise tournament matches using thinking summaries."""
    from core.config import db
    from services.llm import compare_papers
    from routers.validation_utils import build_paper_gt_scores
    
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "ai_impact_summary_thinking": 1,
         "h1_avg_rating": 1, "evaluations": 1}
    ).to_list(500)
    
    gt = build_paper_gt_scores(papers)
    eligible = [p for p in papers if p.get("ai_impact_summary_thinking")]
    
    # Find existing thinking matches
    existing = set()
    async for m in db.validation_matches.find(
        {"dataset_id": DATASET_ID, "content_mode": "abstract_plus_summary:thinking", "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        existing.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
    
    # Generate cross-tier pairs
    pairs = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            p1, p2 = eligible[i]["id"], eligible[j]["id"]
            pk = tuple(sorted([p1, p2]))
            if pk in existing:
                continue
            g1, g2 = gt.get(p1), gt.get(p2)
            if g1 is not None and g2 is not None and g1 != g2:
                pairs.append((p1, p2))
    
    random.shuffle(pairs)
    to_run = pairs[:max(0, NUM_PAIRS - len(existing))]
    
    print(f"[Step 2] Running {len(to_run)} pairwise matches (existing: {len(existing)}, eligible: {len(eligible)})...", flush=True)
    if not to_run:
        print("[Step 2] Enough matches already exist", flush=True)
        return
    
    lookup = {p["id"]: p for p in eligible}
    sem = asyncio.Semaphore(10)
    done = 0
    judges = [
        {"provider": "anthropic", "model": "claude-opus-4-6"},
        {"provider": "openai", "model": "gpt-5.2"},
        {"provider": "gemini", "model": "gemini-3-pro-preview"},
    ]
    
    async def run_one(p1_id, p2_id, idx):
        nonlocal done
        async with sem:
            p1, p2 = lookup[p1_id], lookup[p2_id]
            judge = judges[idx % len(judges)]
            try:
                result = await compare_papers(
                    {**p1, "ai_impact_summary": p1.get("ai_impact_summary_thinking", "")},
                    {**p2, "ai_impact_summary": p2.get("ai_impact_summary_thinking", "")},
                    content_mode="abstract_plus_summary",
                    model_override=judge,
                )
                if result and result.get("winner"):
                    import uuid
                    wk = result["winner"]
                    await db.validation_matches.insert_one({
                        "id": str(uuid.uuid4()),
                        "dataset_id": DATASET_ID,
                        "paper1_id": p1_id,
                        "paper2_id": p2_id,
                        "winner_id": p1_id if wk == "paper1" else p2_id,
                        "model_used": judge,
                        "content_mode": "abstract_plus_summary:thinking",
                        "completed": True,
                        "failed": False,
                        "reasoning": result.get("reasoning", ""),
                        "tokens": result.get("tokens", {}),
                    })
                    done += 1
                    if done % 20 == 0:
                        print(f"  [Step 2] {done}/{len(to_run)}", flush=True)
            except Exception as e:
                print(f"  [Step 2] Match error: {str(e)[:60]}", flush=True)
    
    await asyncio.gather(*[run_one(p1, p2, i) for i, (p1, p2) in enumerate(to_run)], return_exceptions=True)
    print(f"[Step 2] Complete: {done}/{len(to_run)} matches", flush=True)


async def step3_single_item_scoring():
    """Run single-item scoring on all MIDL papers."""
    from core.config import db, EMERGENT_LLM_KEY
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    
    PROMPT_SYS = """You are a world-class scientific reviewer. You will be given a research paper's abstract and an AI-generated impact assessment. Rate this paper on a scale of 1.0 to 10.0 (one decimal place) based on: Significance, Rigor, Novelty, Clarity. Respond with ONLY a JSON object: {"score": 7.5, "significance": 8, "rigor": 7, "novelty": 7, "clarity": 8, "reasoning": "Brief 1-2 sentence justification"}"""
    
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID, "single_item_score": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1,
         "ai_impact_summary_thinking": 1, "ai_impact_summary_opus46": 1, "ai_impact_summary": 1}
    ).to_list(500)
    papers = [p for p in papers if p.get("abstract")]
    
    print(f"[Step 3] Single-item scoring {len(papers)} papers...", flush=True)
    if not papers:
        print("[Step 3] All papers already scored", flush=True)
        return
    
    sem = asyncio.Semaphore(3)
    done = 0
    
    async def score_one(paper):
        nonlocal done
        summary = (paper.get("ai_impact_summary_thinking") or
                   paper.get("ai_impact_summary_opus46") or
                   paper.get("ai_impact_summary", ""))
        async with sem:
            try:
                chat = LlmChat(
                    api_key=EMERGENT_LLM_KEY,
                    session_id=f"si-{paper['id'][:8]}",
                    system_message=PROMPT_SYS,
                ).with_model("anthropic", "claude-opus-4-6").with_params(
                    extra_body={"thinking": {"type": "enabled", "budget_tokens": 8000}}
                )
                prompt = f"Rate this paper:\n\n**Title:** {paper.get('title', '')}\n\n**Abstract:** {paper.get('abstract', '')[:3000]}\n\n**AI Impact Assessment:** {summary[:4000]}"
                resp = await chat.send_message(UserMessage(text=prompt))
                text = str(resp).strip()
                s = text.find("{"); e = text.rfind("}") + 1
                if s >= 0 and e > s:
                    data = json.loads(text[s:e])
                    score = float(data.get("score", 0))
                    if 1.0 <= score <= 10.0:
                        await db.validation_papers.update_one(
                            {"id": paper["id"], "dataset_id": DATASET_ID},
                            {"$set": {"single_item_score": score, "single_item_details": data}}
                        )
                        done += 1
                        if done % 5 == 0:
                            print(f"  [Step 3] {done}/{len(papers)}", flush=True)
                        return
                print(f"  [Step 3] Bad response for {paper['id'][:8]}", flush=True)
            except Exception as e:
                print(f"  [Step 3] Error: {str(e)[:60]}", flush=True)
    
    await asyncio.gather(*[score_one(p) for p in papers], return_exceptions=True)
    print(f"[Step 3] Complete: {done}/{len(papers)} scored", flush=True)


async def main():
    print(f"=== MIDL Pipeline ({DATASET_ID}) ===", flush=True)
    await step1_generate_thinking_summaries()
    await step2_run_pairwise_matches()
    await step3_single_item_scoring()
    print("=== ALL DONE ===", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
