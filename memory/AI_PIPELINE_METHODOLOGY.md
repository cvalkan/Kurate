# AI vs. Human Validation Pipeline — Methodology Report

## Overview

The AI vs. Human benchmark evaluates how well AI pairwise judges agree with human peer reviewers on paper quality rankings. The pipeline uses a two-stage architecture: first summarize, then judge.

## Stage 1: AI Impact Assessment (Summarizer)

**Model:** Claude Opus 4.6 with Extended Thinking (budget: 10,000 thinking tokens)

**Input:** Full paper PDF text + abstract. The summarizer reads the complete paper including title, author names (from PDF headers), and all sections. No truncation is applied unless the text exceeds the model's context window, in which case it is halved iteratively.

**Prompt:** The summarizer is instructed to write up to 1,000 words structured around five dimensions:
1. Core Contribution — novelty and problem solved
2. Methodological Rigor — soundness of approach and experiments
3. Potential Impact — real-world applications and breadth of influence
4. Timeliness & Relevance — current bottlenecks or emerging needs
5. Strengths & Limitations — standout qualities and gaps

After the narrative assessment, the model provides numerical ratings (1.0–10.0) for: overall score, significance, rigor, novelty, and clarity.

**Output:** A text assessment (~500–1,000 words) stored as `ai_impact_summary_thinking` on the paper document, plus structured ratings parsed from the JSON line.

**Note on author visibility:** The summarizer sees the full PDF which includes author names and affiliations in the header. This means the assessment could be influenced by author reputation — analogous to single-blind peer review.

## Stage 2: Pairwise Comparison (Judge)

**Models:** Round-robin rotation across three models:
- GPT-5.2 (OpenAI)
- Claude Opus 4.6 (Anthropic)
- Gemini 3 Pro Preview (Google)

Each comparison is assigned to one model via round-robin, ensuring equal contribution from all three.

**Input per paper:** Abstract (truncated to 1,500 chars) + the Opus 4.6 Thinking impact assessment from Stage 1. The content mode is `abstract_plus_summary:thinking`.

Specifically, each paper is presented as:
```
Abstract: [first 1,500 chars of abstract]

AI Impact Assessment:
[full Opus 4.6 Thinking assessment from Stage 1]
```

**Prompt:** The judge evaluates which paper has higher potential scientific impact across five criteria:
1. Novelty and innovation
2. Real-world applications
3. Methodological rigor
4. Breadth of impact across fields
5. Timeliness and relevance

**Output:** JSON with a binary winner (`paper1` or `paper2`) and brief reasoning (max 150 words). No ties are allowed in the standard comparison mode.

**Positional bias correction:** The presentation order of each pair is randomly flipped with 50% probability before sending to the judge, preventing the known tendency for models to prefer the first-presented paper.

**Note on author visibility:** The judge does NOT see author names. It receives only the abstract and the AI assessment (which itself doesn't include author names in its text, though it was informed by the full PDF).

## Stage 3: Benchmark Computation

### Datasets
- **8 ICLR topic subsets** (469 papers total): Code Generation, Fairness, LLMs, Molecules, Optimization, Optimal Transport, PDEs, Protein Science
- **PeerRead ACL 2017** (80 papers)

### Ground Truth
Human ground truth is derived from reviewer scores (ICLR: 1–10 scale with 6 distinct values; PeerRead: 1–5 scale). For each pair of papers scored by the same positional reviewer, if the scores differ, the higher-scored paper "wins." Ties (same score) are handled via coin-flip correction.

### Controlled Pairs
Only pairs where BOTH an AI match AND at least one human reviewer comparison exist are analyzed. This yields 3,956 controlled pairs across 9 datasets.

### Metrics Computed

**Pairwise Agreement:**
- AI vs. Human: does AI agree with each individual reviewer?
- Human vs. Human: do two reviewers agree with each other?
- AI vs. Majority: does AI agree with the majority vote of reviewers?
- Human vs. Majority (LOO): does a held-out reviewer agree with the remaining majority?
- AI/Human vs. Committee: does AI/reviewer agree with the actual ICLR tier decision?

All metrics are computed both with ties excluded and with coin-flip correction (ties resolved randomly at 50%).

**Ranking Correlation (Bradley-Terry):**
- Individual votes from all reviewers are fed as separate matches into a BT model to produce a human ranking
- AI pairwise matches produce an AI ranking
- Spearman ρ and Kendall τ measure correlation between the two rankings
- Multiple comparison targets: individual aggregate, majority, committee tiers, average score

**Difficulty Stratification:**
- Cross-tier (easy): papers from different ICLR tiers with gap ≥ 2 (e.g., Oral vs. Reject)
- Adjacent-tier (medium): tier gap = 1 (e.g., Spotlight vs. Poster)
- Within-tier (hard): same tier (e.g., Poster vs. Poster)

## Key Results

| Metric | AI | Human | Notes |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 74.4% | 73.4% | AI matches human-level |
| BT ranking ρ (vs. individual aggregate) | **0.735** | 0.645 (LOO) | AI outperforms single expert |
| BT ranking ρ (vs. committee) | **0.761** | 0.666 | AI outperforms despite human circularity advantage |
| Ceiling utilization (vs. 0.878 max) | **87%** | 76% | AI captures more ranking signal |
| Within-tier ranking | Meaningful signal | Near-random | AI discriminates within tiers; humans can't on a 6-value scale |

## Known Limitations

1. **Author visibility in Stage 1:** The summarizer reads author names from the PDF. Prestige bias could leak into the assessment, which then influences the judge.

2. **Positional reviewer labels:** All reviewer identities are positional (Reviewer 1, 2, ...) — "Reviewer 1" on different papers is a different person. Concordance between positional reviewers approximates random-pair agreement but cannot capture individual reviewer effects.

3. **Coarse human rating scale:** ICLR uses only 6 distinct values (1, 3, 5, 6, 8, 10) on a 1–10 scale, with 67% of ratings being 5 or 6. This produces a ~39% tie rate, limiting the human signal available for comparison.

4. **Self-referential architecture:** The same LLM family (Opus 4.6) both summarizes (Stage 1) and judges (Stage 2, as one of three round-robin models). This could create systematic biases that inflate agreement metrics.

5. **No reject-tier ground truth on some datasets:** PeerRead ACL 2017 has no decision tiers. MIDL has no rejects. This limits the difficulty stratification analysis.

6. **Conservative coin-flip correction:** Treating ties as 50/50 underestimates AI agreement because AI has real signal on tie pairs (73.5% agreement with non-tying experts on the same pairs).
