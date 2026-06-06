"""Fast parallel pairwise experiment: Opus 4.6 Thinking as sole judge.
Run with: python3 scripts/run_thinking_pairwise.py qeios-social 10
"""
import asyncio
import sys
import os
import random
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    dataset_id = sys.argv[1] if len(sys.argv) > 1 else "qeios-social"
    matches_per_paper = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    from core.config import db
    from services.llm import compare_papers

    TAG = "thinking_judge"
    CONTENT_MODE = f"abstract_plus_summary:{TAG}"
    MODEL = {"provider": "anthropic", "model": "claude-opus-4-6"}

    papers = await db.validation_papers.find(
        {"dataset_id": dataset_id, "abstract": {"$exists": True, "$ne": None, "$ne": ""}},
        {"_id": 0, "id": 1, "title": 1, "abstract": 1, "ai_impact_summary": 1}
    ).to_list(5000)

    print(f"Dataset: {dataset_id}, {len(papers)} papers, target: {matches_per_paper}/paper, concurrency: {concurrency}")

    # Check existing matches with this tag
    existing = await db.validation_matches.count_documents({"dataset_id": dataset_id, "content_mode": CONTENT_MODE})
    print(f"Existing {TAG} matches: {existing}")

    # Generate matchups: each paper gets ~matches_per_paper opponents
    paper_ids = [p["id"] for p in papers]
    paper_map = {p["id"]: p for p in papers}
    matchups = []
    for pid in paper_ids:
        opponents = [o for o in paper_ids if o != pid]
        random.shuffle(opponents)
        for opp in opponents[:matches_per_paper]:
            pair = tuple(sorted([pid, opp]))
            matchups.append(pair)

    # Deduplicate
    matchups = list(set(matchups))
    random.shuffle(matchups)
    print(f"Generated {len(matchups)} unique matchups")

    # Filter out already-completed pairs
    existing_pairs = set()
    async for m in db.validation_matches.find(
        {"dataset_id": dataset_id, "content_mode": CONTENT_MODE, "completed": True},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1}
    ):
        existing_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))

    matchups = [m for m in matchups if m not in existing_pairs]
    print(f"After dedup: {len(matchups)} new matchups to run")

    if not matchups:
        print("Nothing to do!")
        return

    sem = asyncio.Semaphore(concurrency)
    done = 0
    failed = 0

    async def run_one(p1_id, p2_id):
        nonlocal done, failed
        async with sem:
            # Random swap to avoid position bias
            if random.random() < 0.5:
                p1_id, p2_id = p2_id, p1_id

            p1 = paper_map[p1_id]
            p2 = paper_map[p2_id]

            try:
                result = await compare_papers(
                    p1, p2,
                    content_mode="abstract_plus_summary",
                    model_override=MODEL,
                )
                winner_key = result.get("winner")
                winner_id = p1["id"] if winner_key == "paper1" else p2["id"] if winner_key == "paper2" else None

                match_doc = {
                    "id": str(uuid.uuid4()),
                    "dataset_id": dataset_id,
                    "paper1_id": p1["id"],
                    "paper2_id": p2["id"],
                    "content_mode": CONTENT_MODE,
                    "winner_id": winner_id,
                    "reasoning": result.get("reasoning", ""),
                    "model_used": result.get("model_used", MODEL),
                    "tokens": result.get("tokens", {}),
                    "completed": True,
                    "failed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.validation_matches.insert_one(match_doc)
                done += 1
                if done % 10 == 0:
                    print(f"  {done}/{len(matchups)} done, {failed} failed")
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  FAILED: {str(e)[:80]}")

    await asyncio.gather(*[run_one(p1, p2) for p1, p2 in matchups], return_exceptions=True)
    print(f"\nComplete: {done}/{len(matchups)} matches, {failed} failures")
    print(f"Content mode tag: {CONTENT_MODE}")

if __name__ == "__main__":
    asyncio.run(main())
