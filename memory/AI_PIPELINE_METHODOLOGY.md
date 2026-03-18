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


## Matchmaking & Pair Selection

The tournament uses goal-directed adaptive matchmaking rather than random or round-robin pairing. The system selects which papers to compare next based on convergence targets.

### Convergence Targets (Two-Tier)

| Tier | Target | Meaning |
|---|---|---|
| **General papers** | Wilson 95% CI margin ≤ 15% | Every paper's win rate should be known within ±15% |
| **Top-K papers** (default K=10) | Wilson 95% CI margin ≤ 10% | The best papers need tighter confidence |
| **Top-K cross-matching** | All C(K,2) pairs compared | Every top paper must have been directly compared against every other top paper |

The tournament runs until all three goals are met, then idles.

### Pair Selection Algorithm

Each round selects pairs using a priority system:

**Rule 1 — Match neediest papers first:**
- Compute "urgency" for each paper: `margin - target` (how far from convergence)
- Papers with 0 matches have urgency 999 (highest priority)
- Sort all papers by urgency, descending
- For each needy paper, pick an opponent:

**Opponent selection (calibration split):**
- `calibration_ratio`% of matches (default 50%) pair needy papers against **established** papers (those already converged). The established opponent is chosen by **Elo proximity** — matching papers of similar strength produces more informative comparisons than matching extremes.
- The remaining matches pair **needy vs. needy** — both papers benefit from the same match.
- New papers (0 matches) target the **median Elo** when selecting an established opponent, providing a calibration anchor.

**Rule 2 — Top-K cross-matches:**
After Rule 1 pairs are selected, any remaining slots are filled with missing top-K pairwise comparisons (ensuring all top papers have been directly compared).

**Rule 3 — Repeat matches for validation:**
Only after ALL convergence goals are met: re-compare Elo-adjacent papers to validate close ranking boundaries with additional data points from potentially different judge models.

### Implications for the Benchmark

The adaptive matchmaking means:
- Papers with uncertain rankings get more matches → faster convergence
- Top papers are exhaustively cross-compared → reliable top-K ordering
- Elo-proximity opponent selection means most matches are **close calls** — the tournament preferentially tests the hardest comparisons, not the obvious ones
- This biases raw pairwise agreement statistics downward (harder comparisons = lower agreement), which is why the benchmark reports this as a caveat

## Ceiling Analysis

### What Limits the Maximum Achievable ρ?

The Spearman rank correlation between any ranking and the ICLR committee decisions is bounded by the **coarseness of the committee's 4-tier system** (Oral/Spotlight/Poster/Reject).

**The ceiling:** A perfect predictor that assigns every paper to the correct tier but randomly orders papers within each tier achieves ρ ≈ 0.878. This is the theoretical maximum — no method can exceed it using committee decisions as ground truth, because the committee provides no within-tier ordering information.

**Derivation:** With the actual tier distribution (20 Oral, 31 Spotlight, 126 Poster, 252 Reject = 429 papers with tiers), Spearman ρ between a perfect tier-sorted ranking and the committee's tied-rank ranking converges to exactly 0.878 regardless of within-tier ordering. This was verified empirically across 1,000 random within-tier permutations — the value is deterministic because Spearman handles ties by averaging ranks.

### Results in Context

| Method | ρ vs Committee | % of ceiling | What it means |
|---|---|---|---|
| Perfect tier predictor | 0.878 | 100% | Knows every paper's exact tier |
| **AI (actual)** | **0.761** | **87%** | Captures most of the tier signal + meaningful within-tier ordering |
| Random at 83% accuracy | 0.584 | 66% | Same cross-tier accuracy as AI but random within-tier |
| Single human expert | 0.666 | 76% | Limited by coarse 6-value scale producing noisy within-tier ordering |

### Key Finding: AI Has Within-Tier Signal

AI's ρ (0.761) significantly exceeds what its 82.9% cross-tier accuracy alone would predict (ρ ≈ 0.584 for random within-tier ordering at that accuracy). The gap (0.761 - 0.584 = 0.177) demonstrates that AI produces **meaningful within-tier ranking** — not just correct tier classification.

This is a **conservative win for AI** over single human experts (0.761 vs 0.666):
- The human's higher pairwise accuracy (87.9% vs 82.9%) comes from **circularity** (their scores influenced the committee decisions)
- AI's ranking advantage is earned **without circularity** — it never saw the committee decisions or reviewer scores
- The human's within-tier ordering is near-random (constrained by the 6-value rating scale), while AI reads full papers and can make finer distinctions

### Selection Bias in Committee Comparison

A subtle bias inflates the Human vs Committee accuracy: when a reviewer ties on a paper pair (gives both the same score), those papers are more likely to be in the same tier — and same-tier pairs are excluded from the Committee comparison. This disproportionately drops "easy-to-agree-on" pairs (where both reviewer and committee would agree the papers are similar), enriching the remaining pairs with cases where the reviewer saw a difference. AI faces no such selection because it always produces a verdict. The effect is small relative to the circularity advantage but works in the same direction (favoring the human metric).
