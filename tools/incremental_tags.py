"""
Incremental tag extraction: Claude sees growing vocabulary, reuses existing tags.
"""
import asyncio, os, sys, json, uuid
from collections import Counter
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

CATEGORY = "physics.comp-ph"
SEED = 42
PARTIAL_PATH = "/app/backend/data/precomputed/tags_incremental_physics.json"

PROMPT = """Extract structured tags from this research paper summary.

IMPORTANT: Reuse existing tags from the vocabulary below whenever they are a suitable match. Only create a new tag if no existing tag adequately describes the concept.

Current vocabulary:
{vocabulary}

Summary:
{summary}

Extract:
- topics: 3-5 research topics (specific subfields)
- methods: 2-4 computational methods/algorithms used
- domains: 1-2 application domains
- concepts: 3-5 key scientific concepts

Respond with JSON only:
{{"topics": ["molecular dynamics", "protein folding"], "methods": ["density functional theory", "Monte Carlo simulation"], "domains": ["biophysics"], "concepts": ["free energy", "conformational sampling"]}}"""


async def call_claude(prompt):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    try:
        chat = LlmChat(api_key=os.environ.get("EMERGENT_LLM_KEY"),
                        session_id=f"ti-{uuid.uuid4().hex[:8]}",
                        system_message="Extract structured tags. Reuse existing vocabulary. JSON only."
                        ).with_model("anthropic", "claude-opus-4-6")
        r = await chat.send_message(UserMessage(text=prompt))
        t = r.strip()
        if t.startswith("```"): t = t.split("\n", 1)[-1]
        if t.endswith("```"): t = t[:-3].strip()
        if "{" in t: t = t[t.index("{"):t.rindex("}") + 1]
        return json.loads(t)
    except Exception as e:
        print(f"  Error: {str(e)[:60]}")
        return None


def build_vocabulary(all_tags):
    """Build vocabulary string from all extracted tags so far."""
    vocab = {}
    for key in ["topics", "methods", "domains", "concepts"]:
        tags = set()
        for t in all_tags.values():
            tags.update(t.get(key, []))
        if tags:
            vocab[key] = sorted(tags)
    if not vocab:
        return "(none yet — create new tags as needed)"
    parts = []
    for key in ["topics", "methods", "domains", "concepts"]:
        if key in vocab:
            parts.append(f"{key.capitalize()}: {', '.join(vocab[key])}")
    return "\n".join(parts)


async def run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    CK = "anthropic:claude-opus-4-6:thinking"

    papers = []
    async for doc in db.papers.find(
        {"categories.0": CATEGORY, f"summaries.{CK}": {"$exists": True}},
        {"_id": 0, "id": 1, "title": 1, f"summaries.{CK}": 1},
    ).sort("published", -1):
        s = doc.get("summaries", {}).get(CK, "")
        if isinstance(s, str) and len(s) > 100:
            papers.append({"id": doc["id"], "title": doc["title"], "summary": s[:2000]})
    print(f"{len(papers)} papers")

    # Load partial results
    all_tags = {}
    processed_order = []
    if os.path.exists(PARTIAL_PATH):
        with open(PARTIAL_PATH) as f:
            saved = json.load(f)
        all_tags = saved.get("tags", {})
        processed_order = saved.get("order", [])
        print(f"Resumed: {len(all_tags)} papers tagged")

    # Randomize order (but deterministic) for first run
    import random
    random.seed(SEED)
    if not processed_order:
        order = list(range(len(papers)))
        random.shuffle(order)
    else:
        # Continue from where we left off
        done_ids = set(processed_order)
        order = processed_order + [i for i in range(len(papers)) if papers[i]["id"] not in done_ids]

    for step, idx in enumerate(order):
        p = papers[idx]
        if p["id"] in all_tags:
            continue

        vocab_str = build_vocabulary(all_tags)
        prompt = PROMPT.format(vocabulary=vocab_str, summary=p["summary"][:1500])
        result = await call_claude(prompt)

        if result:
            all_tags[p["id"]] = result
            processed_order.append(p["id"])

        completed = len(all_tags)
        if completed % 10 == 0:
            # Count unique tags
            unique = set()
            for t in all_tags.values():
                for k in ["topics", "methods", "domains", "concepts"]:
                    unique.update(t.get(k, []))
            print(f"  {completed}/{len(papers)} papers, {len(unique)} unique tags")
            # Save checkpoint
            with open(PARTIAL_PATH, "w") as f:
                json.dump({"tags": all_tags, "order": processed_order}, f)

    # Final save
    with open(PARTIAL_PATH, "w") as f:
        json.dump({"tags": all_tags, "order": processed_order}, f)

    # Stats
    unique = {}
    for key in ["topics", "methods", "domains", "concepts"]:
        tags = []
        for t in all_tags.values():
            tags.extend(t.get(key, []))
        c = Counter(tags)
        hapax = sum(1 for v in c.values() if v == 1)
        unique[key] = len(c)
        print(f"\n{key.upper()}: {len(c)} unique ({hapax} hapax, {hapax/len(c)*100:.0f}%)")
        print(f"  Top 10: {c.most_common(10)}")

    # Compare with original
    with open("/app/backend/data/precomputed/tags_physics_comp_ph.json") as f:
        orig = json.load(f)
    for key in ["topics", "methods", "domains", "concepts"]:
        orig_unique = set()
        new_unique = set()
        for t in orig.values():
            orig_unique.update(t.get(key, []))
        for t in all_tags.values():
            new_unique.update(t.get(key, []))
        print(f"\n{key}: original={len(orig_unique)} → incremental={len(new_unique)} ({len(new_unique)/len(orig_unique)*100:.0f}%)")

    print(f"\nDone: {len(all_tags)} papers tagged")


if __name__ == "__main__":
    asyncio.run(run())
