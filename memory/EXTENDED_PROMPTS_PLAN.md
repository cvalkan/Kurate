# Extended Prompts for Structured Research Intelligence

## Context

These prompts extend the existing summarization and comparison pipeline to extract
structured metadata alongside the current impact assessments and pairwise judgments.
The additional fields enable: filtered discovery, similarity graphs, trend detection,
and pair-level research intelligence.

Design principles:
- Backward compatible: existing fields (score, significance, rigor, novelty, clarity) unchanged
- Single API call: structured data extracted in the same call, not a separate request
- JSON at the end: same pattern as current prompts (prose assessment + JSON block)
- Marginal token cost: ~200 extra output tokens per summarization, ~150 per comparison

---

## 1. Extended Summarization Prompt

Current prompt produces: prose assessment + `{score, significance, rigor, novelty, clarity}`
Extended prompt adds: paper-level structured metadata in the same JSON block.

```
SYSTEM PROMPT:

You are a scientific impact analyst. Your task is to write a detailed scientific
impact assessment of a research paper. This assessment will later be used in a
pairwise tournament to compare papers' scientific impact.

Write up to 1000 words (can be shorter if the paper warrants it). Structure your
assessment around:

1. **Core Contribution**: What is the main novelty? What problem does it solve and how?
2. **Methodological Rigor**: How sound is the approach? Are the experiments/proofs convincing?
3. **Potential Impact**: What are the real-world applications? How broadly could this influence the field or adjacent fields?
4. **Timeliness & Relevance**: Does this address a current bottleneck or emerging need?
5. **Strengths & Limitations**: Key strengths that make this paper stand out, and notable weaknesses or gaps.

Feel free to add any other observations you deem important for judging scientific
impact (e.g., scalability, reproducibility, dataset contributions, theoretical
insights, comparison to prior art).

Be specific and analytical — avoid generic praise. Your assessment should give enough
detail for another evaluator to judge this paper's impact without reading the full text.

After your assessment, provide structured metadata as a single JSON block.
Rate dimensions from 1.0 to 10.0 (one decimal place). Choose categories from the
provided options. Be specific with topics and techniques — use the actual terms from
the paper, not generic labels.

```json
{
  "score": 7.5,
  "significance": 8.0,
  "rigor": 7.0,
  "novelty": 7.5,
  "clarity": 8.0,
  "difficulty": 6,
  "math_density": "moderate",
  "paper_type": "experimental",
  "contribution_type": "new_method",
  "reproducibility": "code_available",
  "experiment_scale": "benchmark",
  "topics": ["multi-agent reinforcement learning", "emergent communication"],
  "techniques": ["transformer", "PPO", "self-play"],
  "application_domains": ["robotics", "game AI"],
  "datasets": ["StarCraft II", "custom multi-agent env"],
  "builds_on": ["MAPPO (Yu et al. 2022)", "QMIX (Rashid et al. 2018)"],
  "paradigm_shift": false
}
```

Field definitions:
- difficulty: 1-10, how much background knowledge is needed (1=accessible, 10=deep specialist)
- math_density: "light" | "moderate" | "heavy"
- paper_type: "theoretical" | "experimental" | "computational" | "survey" | "benchmark" | "position" | "dataset"
- contribution_type: "new_method" | "new_dataset" | "improvement" | "negative_result" | "replication" | "framework" | "analysis"
- reproducibility: "code_and_data" | "code_available" | "data_available" | "proof_of_concept" | "not_available"
- experiment_scale: "toy" | "benchmark" | "large_scale" | "production" | "theoretical_only"
- topics: 2-5 specific subtopics (more specific than arXiv categories)
- techniques: key methods/models/algorithms used
- application_domains: real-world areas this applies to (empty if purely theoretical)
- datasets: named datasets used (empty if none)
- builds_on: 1-3 key prior works this extends (author + year format)
- paradigm_shift: true only if this proposes a fundamentally new approach, not an incremental improvement
```

USER PROMPT (unchanged structure):

```
Write a scientific impact assessment for the following paper:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words), then provide your structured
metadata as a JSON block at the end.
```

---

## 2. Extended Comparison Prompt

Current prompt produces: `{winner, reasoning}`
Extended prompt adds: pair-level similarity and comparison structure.

```
SYSTEM PROMPT:

You are a scientific paper evaluator. Your task is to compare two papers and
determine which has higher potential scientific impact.

Consider the following factors:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor
4. Breadth of impact across fields
5. Timeliness and relevance

You MUST respond with valid JSON only, no other text. Format:

{
  "winner": "paper1" or "paper2",
  "reasoning": "Brief explanation of why experts would prefer this paper (max 150 words)",
  "confidence": "high" or "medium" or "low",
  "dimensions": {
    "novelty": "paper1" or "paper2" or "tie",
    "rigor": "paper1" or "paper2" or "tie",
    "impact": "paper1" or "paper2" or "tie",
    "clarity": "paper1" or "paper2" or "tie"
  },
  "loser_strength": "Brief note on where the losing paper is actually stronger (max 30 words, or null)",
  "similarity": {
    "topical": "same_subfield" or "adjacent" or "distant",
    "methodological": "similar" or "different" or "complementary",
    "relationship": "competing" or "complementary" or "independent" or "builds_on" or "contradicts",
    "combinable": true or false
  }
}
```

USER PROMPT (unchanged):

```
Compare these two papers for scientific impact:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper has higher estimated scientific impact? Respond with JSON only.
```

---

## 3. Token Cost Estimate

| Stage | Current output | Extended output | Delta |
|---|---|---|---|
| Summarization | ~1200 tokens (prose + 5 ratings) | ~1400 tokens (+structured JSON) | +200 tokens (~+17%) |
| Comparison | ~80 tokens (winner + reasoning) | ~230 tokens (+dimensions, similarity) | +150 tokens (~+190%) |

At $0.015/comparison average:
- Summarization: ~$0.003 extra per paper (one-time)
- Comparison: ~$0.005 extra per match (ongoing)
- For 500 new papers/day × 30 matches each: ~$1.50 + $75 = ~$76.50/day vs current ~$75/day → +2% cost increase

The comparison token increase looks large in percentage but the absolute cost is tiny
because comparison outputs are already very short.

---

## 4. Storage Schema

### Paper-level (in `papers` collection, under `structured_metadata`):

```json
{
  "structured_metadata": {
    "difficulty": 6,
    "math_density": "moderate",
    "paper_type": "experimental",
    "contribution_type": "new_method",
    "reproducibility": "code_available",
    "experiment_scale": "benchmark",
    "topics": ["multi-agent reinforcement learning", "emergent communication"],
    "techniques": ["transformer", "PPO", "self-play"],
    "application_domains": ["robotics", "game AI"],
    "datasets": ["StarCraft II", "custom multi-agent env"],
    "builds_on": ["MAPPO (Yu et al. 2022)", "QMIX (Rashid et al. 2018)"],
    "paradigm_shift": false,
    "extracted_by": "claude-opus-4-6",
    "extracted_at": "2026-05-17T..."
  }
}
```

### Pair-level (in `matches` collection, under `similarity`):

```json
{
  "similarity": {
    "topical": "same_subfield",
    "methodological": "complementary",
    "relationship": "competing",
    "combinable": false,
    "confidence": "high",
    "dimensions": {
      "novelty": "paper1",
      "rigor": "paper2",
      "impact": "paper1",
      "clarity": "tie"
    },
    "loser_strength": "Better experimental methodology and ablation studies"
  }
}
```

---

## 5. Implementation Phases

### Phase 1: Extended summarization (low risk, high value)
- Update the summarization prompt to request structured JSON
- Parse and store under `papers.structured_metadata`
- New papers get metadata immediately; backfill existing via admin endpoint
- Enables: filtering, topic clustering, difficulty badges, reproducibility indicators

### Phase 2: Extended comparison (medium risk, unique value)
- Update the comparison prompt to request similarity + dimensions
- Parse and store under `matches.similarity`
- Every new match generates pair-level data automatically
- Enables: similarity graph, dimension-level win attribution, contradiction detection

### Phase 3: Embeddings + similarity graph
- Generate embeddings from `topics` + `techniques` vectors (no extra API call — computed from extracted fields)
- Build approximate nearest neighbors index (FAISS or similar)
- Cluster with HDBSCAN, project with UMAP
- Enables: visual landscape, "papers like this one", cluster-level intelligence

### Phase 4: Temporal intelligence
- Weekly snapshots of cluster composition
- Trend detection: growing/shrinking/emerging clusters
- Bridge paper detection: papers connecting distant clusters
- Enables: "what's trending," field evolution animation, research radar

---

## 6. Backward Compatibility

The extended JSON is a strict superset of the current format. The existing parser
extracts `score`, `significance`, `rigor`, `novelty`, `clarity` — additional fields
are simply ignored until the storage code is updated. This means:

- The extended prompt can be deployed immediately with zero code changes
- New fields are captured in the raw summary text
- The parser can be updated separately to extract and store them
- No migration needed for existing data
