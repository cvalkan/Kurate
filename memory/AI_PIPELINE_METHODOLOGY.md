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

Each comparison is assigned to one model via round-robin (1 judge per pair), ensuring equal contribution from all three.

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

## Stage 3: Ranking Model

### Regularized Win-Rate (not Elo or Bradley-Terry)

Rankings are computed using a **regularized win-rate** with Jeffreys prior: `(wins + 0.5) / (matches + 1)`, mapped through a logistic function to a score centered at 1200. This is NOT Elo (which is a sequential update algorithm for changing skill) and NOT Bradley-Terry MLE (which estimates opponent-adjusted strengths).

**Why not Bradley-Terry?** We systematically tested all three methods across all datasets at 7–218 matches per paper. The regularized win-rate correlates more strongly with human ground truth in **every single case**. Bradley-Terry attempts to account for opponent strength ("a win against a strong paper counts more"), but at 15–30 matches per paper the opponent strength estimates are too noisy and propagate errors throughout the ranking. The win-rate ignores opponent strength entirely, which is the more robust strategy at this data density.

**Why not real Elo?** Sequential Elo is path-dependent — the order in which matches are processed affects the final rating. For papers (whose quality is fixed, unlike chess players whose skill changes), this introduces arbitrary noise. With random match ordering, Elo converges toward win-rate but with additional variance.

**Important caveat:** The win-rate is **more sensitive to matchmaking bias** than Bradley-Terry. If a paper is matched disproportionately against weak opponents, its win-rate is inflated. Bradley-Terry would correct for this. Therefore, uniform random matchmaking (with coverage-based round-robin) is essential for fair win-rate ranking.

### Regularization explained

The "regularization" adds a virtual half-win and half-loss before computing the rate: `(wins + 0.5) / (matches + 1)`. This prevents extreme scores for papers with few matches — a paper with 1 win out of 1 match scores 75% instead of 100%. The effect is negligible for papers with 20+ matches.

## Stage 4: Benchmark Computation

### Datasets
- **8 ICLR topic subsets** (469 papers total): Code Generation, Fairness, LLMs, Molecules, Optimization, Optimal Transport, PDEs, Protein Science
- **PeerRead ACL 2017** (80 papers)

### Ground Truth
Human ground truth is derived from reviewer scores (ICLR: 1–10 scale with 6 distinct values; PeerRead: 1–5 scale). For each pair of papers scored by the same positional reviewer, if the scores differ, the higher-scored paper "wins." Ties (same score) are handled via coin-flip correction.

### Benchmark Pages

The benchmark provides four validation pages:

**Human vs AI Benchmark (Legacy — cross-tier pairs only):**
Both AI and human rankings are built from the same controlled pair set (3,956 pairs). Historically inflated because AI was only tested on cross-tier comparisons (see §Known Limitations, item 1).

**Human vs AI Benchmark (primary — all pairs including within-tier):**
Same controlled methodology but including within-tier pairs (7,032 pairs at ~25–30 M/P). This is the honest benchmark — AI is tested on the full difficulty spectrum. Both AI and human rankings use the same pair set for fair comparison.

**AI Ranking Quality (Legacy — cross-tier pairs only):**
Non-controlled: AI ranking from its cross-tier matches, human ground truth from all expert pairs independently.

**AI Ranking Quality (primary — all pairs including within-tier):**
Non-controlled with within-tier matches included at natural proportions. Each method uses its full available data. Includes gap-sampling analysis and top/bottom-K% overlap metrics.

### Metrics Computed

**Pairwise Agreement:**
- AI vs. Human: does AI agree with each individual reviewer?
- Human vs. Human: do two reviewers agree with each other?
- AI vs. Majority: does AI agree with the majority vote of reviewers?
- Human vs. Majority (LOO): does a held-out reviewer agree with the remaining majority?
- AI/Human vs. Committee: does AI/reviewer agree with the actual ICLR tier decision?

All metrics are computed both with ties excluded and with coin-flip correction (ties resolved randomly at 50%).

**Ranking Correlation:**
- Individual votes from all reviewers are fed as separate matches into the win-rate ranking model to produce a human ranking
- AI pairwise matches produce an AI ranking
- Spearman ρ measures correlation between the two rankings
- Multiple comparison targets: individual aggregate, majority, committee tiers, average score
- Human ceiling: leave-one-out (LOO) — one expert's ranking vs all other experts' ranking

**Difficulty Stratification:**
- Cross-tier (easy): papers from different ICLR tiers with gap ≥ 2 (e.g., Oral vs. Reject)
- Adjacent-tier (medium): tier gap = 1 (e.g., Spotlight vs. Poster)
- Within-tier (hard): same tier (e.g., Poster vs. Poster)

**Top/Bottom K% Overlap:**
- What fraction of AI's top/bottom K% papers are also in the ground truth's top/bottom K%
- Compared against the expected overlap from a Gaussian noise model at the observed ρ (500 simulation trials)
- AI's actual overlap is consistently below expected, especially at extreme percentiles (top/bottom 5–10%)

## Key Results

### Primary benchmark (all pairs including within-tier)

| Metric | AI | Human ceiling | AI advantage |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 68.7% | 66.6% (H-H) | +2.1pp |
| ρ vs Individual aggregate | **0.670** | 0.529 (LOO) | **+0.141** |
| ρ vs Committee | 0.648 | 0.520 (LOO) | +0.128 |
| Top 10% overlap (vs Aggregate) | ~23% | — | (expected: ~43%) |
| Top 20% overlap (vs Aggregate) | ~40% | — | (expected: ~54%) |

### Legacy benchmark (cross-tier pairs only)

| Metric | AI | Human ceiling | AI advantage |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 74.4% | 73.4% (H-H) | +1.0pp |
| ρ vs Individual aggregate | **0.739** | 0.660 (LOO) | **+0.078** |
| ρ vs Committee | **0.762** | 0.681 (LOO) | **+0.081** |

Note: The legacy numbers are inflated because AI was only tested on easier cross-tier pairs. The primary benchmark is the honest assessment.

### PW vs SI comparison (all pairs)

| Metric | Pairwise (PW) | Single-Item (SI) | PW advantage |
|---|---|---|---|
| Pairwise accuracy | 75.5% | 74.7% | +0.8pp |
| ρ vs Individual aggregate | 0.652 | 0.617 | **+0.035** |
| ρ vs Committee | 0.589 | 0.561 | +0.028 |

PW's advantage over SI shrinks dramatically with within-tier pairs included (was +0.12 legacy). On some individual datasets (e.g., Codegen), SI actually beats PW on ρ. Combining PW and SI provides negligible improvement (+0.002 at best) because they are highly correlated (ρ(PW,SI) ≈ 0.86).

## Known Limitations and Methodological Issues

### 1. Cross-Tier Pair Selection Bias (Fixed Mar 2026)

**Issue discovered:** The validation matchmaking algorithm was filtering pair selection to **cross-tier pairs only** — papers with different human ground truth scores (h1_avg_rating). This meant AI was never tested on within-tier comparisons (e.g., Poster vs. Poster), which account for ~30–40% of all possible pairs.

**Fix applied:** The cross-tier filter has been removed. Within-tier matches have been generated for all 8 ICLR datasets and added to the benchmark at their **natural proportion** (matching the fraction of within-tier pairs in all possible C(n,2) pairs per dataset). Match density was boosted to ~30 matches/paper for the three sparsest datasets.

**Impact:** Adding within-tier pairs lowers all absolute ρ values (the honest numbers are lower) but **AI's advantage over the human ceiling increases** (+0.141 vs +0.078 on the legacy benchmark). This is because within-tier pairs hurt humans more than AI — the committee ground truth has no within-tier signal, and human experts' coarse rating scale produces mostly ties on within-tier pairs.

### 2. Within-Tier Ground Truth Limitation

Within-tier pairs (e.g., Poster vs. Poster) are largely **invisible** to the committee ground truth — both papers are in the same tier by definition. AI pairwise accuracy on within-tier pairs is ~60% (vs ~88% cross-tier), but human agreement on these same pairs is only ~58%. Neither AI nor humans can reliably rank within-tier papers, primarily because the ground truth doesn't distinguish them.

This is not an AI failure — it's an **ill-defined task** for within-tier papers. The ρ drop when including within-tier pairs reflects the ground truth ceiling, not a model weakness.

### 3. Controlled Pairs vs. Non-Controlled (Full Data)

The benchmark provides two methodologies:

**Controlled:** Both AI and human rankings use the same pair set. Fair for head-to-head comparison but restricts the human ranking to AI's sparse pair set.

**Non-controlled:** AI uses its matches, human uses all expert pairs independently. More honest for absolute quality assessment but the yardstick (human ranking) differs between pages.

The controlled ρ is typically 0.005–0.010 higher because the restricted human ranking is less precise (fewer pairs) and therefore easier to correlate with.

### 4. Structural Win-Rate Score Coupling

When both AI and human majority are computed from the same pair set with 1 vote per pair each, papers where both methods agree unanimously produce identical win/loss records → identical scores. This is a mathematical artifact that breaks with individual-level aggregation (multiple expert votes per pair).

### 5. Author Visibility in Stage 1

The summarizer reads author names from the PDF. Prestige bias could leak into the assessment, which then influences the judge.

### 6. Positional Reviewer Labels

All reviewer identities are positional (Reviewer 1, 2, ...) — "Reviewer 1" on different papers is a different person. Concordance between positional reviewers approximates random-pair agreement but cannot capture individual reviewer effects.

### 7. Coarse Human Rating Scale

ICLR uses only 6 distinct values (1, 3, 5, 6, 8, 10) on a 1–10 scale, with 67% of ratings being 5 or 6. This produces a ~39% tie rate, limiting the human signal available for comparison.

### 8. Self-Referential Architecture

The same LLM family (Opus 4.6) both summarizes (Stage 1) and judges (Stage 2, as one of three round-robin models). This could create systematic biases that inflate agreement metrics.

### 9. Conservative Coin-Flip Correction

Treating ties as 50/50 underestimates AI agreement because AI has real signal on tie pairs (73.5% agreement with non-tying experts on the same pairs, vs the 50% coin-flip assumption).

### 10. Win-Rate Sensitivity to Matchmaking

The regularized win-rate ignores opponent strength. This makes it sensitive to non-uniform matchmaking — a paper matched disproportionately against weak opponents gets an inflated win-rate. The validation benchmark mitigates this with coverage-based round-robin (every paper gets ≥N matches, opponents distributed evenly), but the live tournament's adaptive matchmaking (score-proximity targeting) could introduce bias. This is a known trade-off: the tournament's matchmaking is optimal for convergence speed but not for win-rate fairness.

## Matchmaking & Pair Selection

### Live Tournament (Leaderboard)

The live leaderboard tournament uses goal-directed adaptive matchmaking. The system selects which papers to compare next based on convergence targets.

**Convergence Targets (Two-Tier):**

| Tier | Target | Meaning |
|---|---|---|
| **General papers** | Wilson 95% CI margin ≤ 15% | Every paper's win rate should be known within ±15% |
| **Top-K papers** (default K=10) | Wilson 95% CI margin ≤ 10% | The best papers need tighter confidence |
| **Top-K cross-matching** | All C(K,2) pairs compared | Every top paper must have been directly compared against every other top paper |

The tournament runs until all three goals are met, then idles (event-driven, no polling).

**Pair Selection Algorithm:**

Each round selects pairs using a priority system:

*Rule 1 — Match neediest papers first:*
- Compute "urgency" for each paper: `margin - target` (how far from convergence)
- Papers with 0 matches have urgency 999 (highest priority)
- Sort all papers by urgency, descending
- For each needy paper, pick an opponent via calibration split:
  - `calibration_ratio`% of matches (default 50%) pair needy papers against **established** papers (already converged), chosen by **score proximity**
  - The remaining matches pair **needy vs. needy**
  - New papers (0 matches) target the **median score** when selecting an established opponent

*Rule 2 — Top-K cross-matches:*
After Rule 1, remaining slots are filled with missing top-K pairwise comparisons.

*Rule 3 — Repeat matches for validation:*
Only after ALL convergence goals are met: re-compare score-adjacent papers to validate close ranking boundaries.

### Validation Benchmark (AI vs. Human)

The validation benchmark uses a **different, simpler** matchmaking strategy:

1. Generate all possible paper pairs (no tier filtering)
2. Select pairs using a round-robin strategy that ensures minimum coverage per paper
3. Remaining slots are filled with weighted-random selection (biased toward under-matched papers)
4. Within-tier pairs are included at their natural proportion in the dataset

No score-proximity, no CI targets, no calibration split. This ensures the validation matches are an unbiased sample of the comparison space.

**Historical note (pre–Mar 2026):** The original matchmaking code filtered pairs to only cross-tier comparisons, excluding all within-tier pairs. This was an erroneous filter introduced by a previous agent — not a deliberate design choice. It has been removed and within-tier matches have been generated retroactively.

**Match counts per dataset (including within-tier supplements, as of Mar 2026):**

| Dataset | Papers | Base matches | + Within-tier | + Boost | Total | Avg M/P |
|---|---|---|---|---|---|---|
| ICLR Code Generation | 62 | 625 | 1,010 | 0 | 1,635 | 26.5 |
| ICLR Fairness | 68 | 264 | 264 | 492 | 1,020 | 30.0 |
| ICLR LLMs | 73 | 837 | 590 | 0 | 1,427 | 19.1 |
| ICLR Molecules | 46 | 158 | 158 | 374 | 690 | 30.0 |
| ICLR Optimization | 42 | 162 | 162 | 306 | 630 | 30.0 |
| ICLR Optimal Transport | 52 | 503 | 479 | 0 | 982 | 18.9 |
| ICLR PDEs & Dyn. Systems | 80 | 641 | 641 | 0 | 1,282 | 16.0 |
| ICLR Protein Science | 46 | 259 | 418* | 0 | 677 | 14.7 |
| PeerRead ACL 2017 | 80 | 1,118 | 0 | 0 | 1,118 | 27.9 |

*Protein's experiment used fully random pairs (not exclusively within-tier).

Base matches: original cross-tier + adjacent thinking-mode matches (0% within-tier).
Within-tier: experiment matches generated to supplement within-tier coverage.
Boost: additional matches to bring sparse datasets to ~30 M/P.
The unfiltered benchmark pages use natural-proportion subsampling to ensure within-tier pairs match their natural fraction in the dataset (not overrepresented).

## Ceiling Analysis

### What Limits the Maximum Achievable ρ?

The Spearman rank correlation between any ranking and the ICLR committee decisions is bounded by the **coarseness of the committee's 4-tier system** (Oral/Spotlight/Poster/Reject).

**The ceiling:** A perfect predictor that assigns every paper to the correct tier but randomly orders papers within each tier achieves ρ ≈ 0.878. This is the theoretical maximum — no method can exceed it using committee decisions as ground truth, because the committee provides no within-tier ordering information.

**Derivation:** With the actual tier distribution (20 Oral, 31 Spotlight, 126 Poster, 252 Reject = 429 papers with tiers), Spearman ρ between a perfect tier-sorted ranking and the committee's tied-rank ranking converges to exactly 0.878 regardless of within-tier ordering.

### Results in Context (Legacy — cross-tier only)

| Method | ρ vs Committee | % of ceiling |
|---|---|---|
| Perfect tier predictor | 0.878 | 100% |
| **AI (legacy)** | **0.762** | **87%** |
| Single human expert | 0.681 | 78% |

### Results in Context (Primary — all pairs)

| Method | ρ vs Committee | % of ceiling |
|---|---|---|
| Perfect tier predictor | 0.878 | 100% |
| **AI (all pairs)** | **0.648** | **74%** |
| Single human expert | 0.520 | 59% |

The drop from 87% to 74% ceiling utilization reflects the inclusion of within-tier pairs, where the committee ground truth provides no signal. AI still outperforms the human ceiling at all difficulty levels.

### Selection Bias in Committee Comparison

A subtle bias inflates the Human vs Committee accuracy: when a reviewer ties on a paper pair (gives both the same score), those papers are more likely to be in the same tier — and same-tier pairs are excluded from the Committee comparison. This disproportionately drops "easy-to-agree-on" pairs. AI faces no such selection because it always produces a verdict.

## Appendix: Gap-Based Analysis

The AI Ranking Quality page includes analysis of how the ranking correlation varies with:

**SI-Score gap sampling:** Filtering AI matches by the Single-Item score gap between papers. Removing low-gap matches (keeping only easy pairs) improves AI's ρ but also improves the human ceiling, keeping AI's advantage roughly constant.

**Score-gap match weighting:** Using the weighted win-rate model to give different weights to matches based on predicted difficulty. No weighting scheme beats uniform weighting — the win-rate model already extracts optimal signal from each match. Close-cut overweighting (emphasizing hard pairs) hurts; wide-gap overweighting is neutral.

**PW+SI combination:** Combining pairwise and single-item rankings. The best combination (0.7 PW + 0.3 SI) improves ρ by only +0.001 over PW alone. PW and SI rankings are 86% correlated — they capture the same quality signal through different methods. Converting SI scores to synthetic pairwise matches and feeding them to the ranking model at 1% weight provides +0.002 improvement.
