#!/usr/bin/env python3
"""Run single-item scoring for multiple datasets. Execute directly, not via web server."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

PROMPT_SYS = """You are a world-class scientific reviewer. You will be given a research paper's abstract and an AI-generated impact assessment. Rate this paper on a scale of 1.0 to 10.0 (one decimal place) based on: Significance, Rigor, Novelty, Clarity. Respond with ONLY a JSON object: {"score": 7.5, "significance": 8, "rigor": 7, "novelty": 7, "clarity": 8, "reasoning": "Brief 1-2 sentence justification"}"""

async def score_dataset(dataset_id):
    from core.config import db, EMERGENT_LLM_KEY
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id, "single_item_score": {"$exists": False}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1,
         "ai_impact_summary_thinking": 1, "ai_impact_summary_opus46": 1, "ai_impact_summary": 1}
    ).to_list(5000)
    papers = [p for p in papers if p.get("abstract")]
    print(f"[{dataset_id}] {len(papers)} papers to score", flush=True)
    if not papers:
        return

    sem = asyncio.Semaphore(3)
    done = 0

    async def score_one(paper):
        nonlocal done
        summary = (paper.get("ai_impact_summary_thinking") or
                   paper.get("ai_impact_summary_opus46") or
                   paper.get("ai_impact_summary", ""))
        prompt = f"""Rate this paper:

**Title:** {paper.get("title", "")}

**Abstract:** {paper.get("abstract", "")[:3000]}

**AI Impact Assessment:** {summary[:4000]}"""

        async with sem:
            try:
                chat = LlmChat(
                    api_key=EMERGENT_LLM_KEY,
                    session_id=f"si-{paper['id'][:8]}",
                    system_message=PROMPT_SYS,
                ).with_model("anthropic", "claude-opus-4-6").with_params(
                    extra_body={"thinking": {"type": "enabled", "budget_tokens": 8000}}
                )
                resp = await chat.send_message(UserMessage(text=prompt))
                text = str(resp).strip()
                s = text.find("{")
                e = text.rfind("}") + 1
                if s >= 0 and e > s:
                    data = json.loads(text[s:e])
                    score = float(data.get("score", 0))
                    if 1.0 <= score <= 10.0:
                        await db.validation_papers.update_one(
                            {"id": paper["id"], "dataset_id": dataset_id},
                            {"$set": {"single_item_score": score, "single_item_details": data}}
                        )
                        done += 1
                        if done % 5 == 0:
                            print(f"  [{dataset_id}] {done}/{len(papers)}", flush=True)
                        return
                print(f"  [{dataset_id}] Bad response for {paper['id'][:8]}", flush=True)
            except Exception as ex:
                print(f"  [{dataset_id}] Error: {str(ex)[:80]}", flush=True)

    await asyncio.gather(*[score_one(p) for p in papers], return_exceptions=True)
    print(f"[{dataset_id}] Complete: {done}/{len(papers)}", flush=True)

async def main():
    datasets = sys.argv[1:] if len(sys.argv) > 1 else [
        "iclr-llm", "iclr-fairness", "iclr-protein", "iclr-pdes", "iclr-molecules", "iclr-optimization"
    ]
    for ds in datasets:
        await score_dataset(ds)
    print("ALL DONE", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
