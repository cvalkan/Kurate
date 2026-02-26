"""
Experiment: Test "deeper dive recommended" meta-evaluation on 50 random papers.
Adds a structured JSON block to the impact assessment prompt asking the model
whether extended analysis would reveal important missed insights.
"""
import asyncio
import random
import json
import uuid
import sys
import os
sys.path.insert(0, '/app/backend')

from collections import defaultdict
from emergentintegrations.llm.chat import LlmChat, UserMessage

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY') or open('/app/backend/.env').read().split('EMERGENT_LLM_KEY=')[1].split('\n')[0].strip()

# Use Claude Opus 4.6 for consistency
MODEL = {"provider": "anthropic", "model": "claude-opus-4-6"}

SYSTEM_PROMPT = """You are a scientific impact analyst. Your task is to write a detailed scientific impact assessment of a research paper. This assessment will later be used in a pairwise tournament to compare papers' scientific impact.

Write up to 1000 words (can be shorter if the paper warrants it). Structure your assessment around:

1. **Core Contribution**: What is the main novelty? What problem does it solve and how?
2. **Methodological Rigor**: How sound is the approach? Are the experiments/proofs convincing?
3. **Potential Impact**: What are the real-world applications? How broadly could this influence the field or adjacent fields?
4. **Timeliness & Relevance**: Does this address a current bottleneck or emerging need?
5. **Strengths & Limitations**: Key strengths that make this paper stand out, and notable weaknesses or gaps.

Be specific and analytical — avoid generic praise.

After your assessment, on a new line, output EXACTLY one JSON block (and nothing else after it) with your meta-evaluation of whether a deeper analysis pass would be valuable:

```json
{"deeper_dive_recommended": true/false, "confidence": "high/medium/low", "focus_areas": ["area1", "area2"]}
```

Set `deeper_dive_recommended` to `true` ONLY if you believe extended analysis (e.g., step-by-step proof verification, detailed methodology audit, cross-referencing claims against cited results) could plausibly reveal important strengths, weaknesses, or nuances that your first-pass assessment is likely to miss. Common reasons include:
- Complex mathematical proofs that need step-by-step verification
- Subtle methodological issues that require careful reasoning
- Claims that seem strong but lack sufficient evidence in the paper
- Interdisciplinary work where domain expertise gaps may cause blind spots
- Dense experimental sections where result validity needs careful checking

Set `confidence` to how confident you are in the completeness of YOUR assessment (not the paper's quality).
List `focus_areas` as the specific aspects a deeper dive should examine."""

USER_PROMPT = """Write a scientific impact assessment for the following paper:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words), then the meta-evaluation JSON block:"""


async def run_experiment():
    from pymongo import MongoClient
    db = MongoClient('mongodb://localhost:27017')['test_database']

    # Pick ~6 random papers per category
    papers_by_cat = defaultdict(list)
    for p in db.papers.find(
        {'full_text': {'$exists': True, '$ne': None}, 'summaries': {'$exists': True, '$ne': {}}},
        {'_id': 0, 'id': 1, 'title': 1, 'abstract': 1, 'full_text': 1, 'categories': 1}
    ):
        cat = (p.get('categories') or ['unknown'])[0]
        papers_by_cat[cat].append(p)

    selected = []
    for cat, papers in sorted(papers_by_cat.items()):
        sample = random.sample(papers, min(6, len(papers)))
        selected.extend([(cat, p) for p in sample])

    random.shuffle(selected)
    selected = selected[:50]

    print(f"Selected {len(selected)} papers across {len(set(c for c,_ in selected))} categories")
    print(f"Distribution: {dict(sorted(defaultdict(int, {c: sum(1 for x,_ in selected if x==c) for c in set(c for c,_ in selected)}).items()))}")
    print()

    results = []
    for i, (cat, paper) in enumerate(selected):
        title = paper['title']
        abstract = paper.get('abstract', '')
        full_text = paper.get('full_text', '')
        content = f"Abstract: {abstract[:1500]}\n\nFull Paper Text:\n{full_text}" if full_text else f"Abstract: {abstract[:3000]}"

        prompt = USER_PROMPT.format(title=title, content=content)

        print(f"[{i+1}/{len(selected)}] {cat} | {title[:60]}...", end=" ", flush=True)

        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"deepdive-exp-{uuid.uuid4()}",
                system_message=SYSTEM_PROMPT,
            ).with_model(MODEL["provider"], MODEL["model"])

            response = await chat.send_message(UserMessage(text=prompt))
            response_text = response.strip() if isinstance(response, str) else str(response)

            # Extract JSON block
            meta = None
            # Try to find JSON block after ```json or just a raw JSON line
            json_match = None
            import re
            # Look for ```json ... ``` block
            m = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if m:
                json_match = m.group(1)
            else:
                # Look for last JSON object in text
                for line in reversed(response_text.split('\n')):
                    line = line.strip()
                    if line.startswith('{') and 'deeper_dive' in line:
                        json_match = line
                        break

            if json_match:
                try:
                    meta = json.loads(json_match)
                except json.JSONDecodeError:
                    # Try fixing common issues
                    fixed = json_match.replace("true", "True").replace("false", "False")
                    try:
                        meta = eval(fixed)
                    except:
                        meta = None

            rec = meta.get('deeper_dive_recommended', None) if meta else None
            conf = meta.get('confidence', None) if meta else None
            areas = meta.get('focus_areas', []) if meta else []

            symbol = "🔍" if rec else ("✓" if rec is False else "?")
            print(f"{symbol} dive={rec} conf={conf} areas={areas}")

            results.append({
                'category': cat,
                'title': title,
                'full_text_len': len(full_text),
                'deeper_dive_recommended': rec,
                'confidence': conf,
                'focus_areas': areas,
                'meta_raw': meta,
                'parse_ok': meta is not None,
            })

        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                'category': cat,
                'title': title,
                'full_text_len': len(full_text),
                'deeper_dive_recommended': None,
                'confidence': None,
                'focus_areas': [],
                'meta_raw': None,
                'parse_ok': False,
                'error': str(e),
            })

    # Summary
    print("\n" + "="*80)
    print("EXPERIMENT RESULTS")
    print("="*80)

    parsed = [r for r in results if r['parse_ok']]
    recommended = [r for r in parsed if r['deeper_dive_recommended']]
    not_recommended = [r for r in parsed if r['deeper_dive_recommended'] is False]

    print(f"\nTotal papers: {len(results)}")
    print(f"Successfully parsed: {len(parsed)}/{len(results)}")
    print(f"Deeper dive recommended: {len(recommended)}/{len(parsed)} ({len(recommended)/len(parsed)*100:.0f}%)")
    print(f"Not recommended: {len(not_recommended)}/{len(parsed)}")
    print()

    # By confidence
    from collections import Counter
    conf_dist = Counter(r['confidence'] for r in parsed)
    print(f"Confidence distribution: {dict(conf_dist.most_common())}")

    # By category
    print("\nBy category:")
    cat_stats = defaultdict(lambda: {'total': 0, 'recommended': 0})
    for r in parsed:
        cat_stats[r['category']]['total'] += 1
        if r['deeper_dive_recommended']:
            cat_stats[r['category']]['recommended'] += 1
    for cat in sorted(cat_stats):
        s = cat_stats[cat]
        print(f"  {cat}: {s['recommended']}/{s['total']} recommended")

    # Focus areas frequency
    all_areas = []
    for r in recommended:
        all_areas.extend(r['focus_areas'])
    area_counts = Counter(a.lower().strip() for a in all_areas)
    if area_counts:
        print(f"\nTop focus areas for recommended papers:")
        for area, count in area_counts.most_common(15):
            print(f"  {area}: {count}")

    # List recommended papers
    if recommended:
        print(f"\n{'='*80}")
        print("PAPERS RECOMMENDED FOR DEEPER DIVE")
        print(f"{'='*80}")
        for r in recommended:
            print(f"\n  [{r['category']}] {r['title'][:80]}")
            print(f"    confidence={r['confidence']}, ft_len={r['full_text_len']:,}")
            print(f"    focus_areas={r['focus_areas']}")

    # Save full results
    with open('/app/test_reports/deeper_dive_experiment.json', 'w') as f:
        json.dump({
            'summary': {
                'total': len(results),
                'parsed': len(parsed),
                'recommended': len(recommended),
                'not_recommended': len(not_recommended),
                'recommend_rate': f"{len(recommended)/max(len(parsed),1)*100:.1f}%",
                'confidence_distribution': dict(conf_dist),
                'focus_area_frequency': dict(area_counts.most_common(20)),
            },
            'results': results,
        }, f, indent=2, default=str)
    print(f"\nFull results saved to /app/test_reports/deeper_dive_experiment.json")


if __name__ == "__main__":
    asyncio.run(run_experiment())
