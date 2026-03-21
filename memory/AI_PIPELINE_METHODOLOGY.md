# AI vs. Human Validation Pipeline — Methodology Report

## Overview

The AI vs. Human benchmark evaluates how well AI pairwise judges agree with human peer reviewers on paper quality rankings. The pipeline uses a two-stage architecture: first summarize, then judge. The validation covers 9 datasets (8 ICLR topic subsets + PeerRead ACL 2017, 549 papers total) with ~25–30 pairwise matches per paper.

## Stage 1: AI Impact Assessment (Summarizer)

**Model:** Claude Opus 4.6 with Extended Thinking (budget: 10,000 thinking tokens)

**Input:** Full paper PDF text + abstract, including author names (analogous to single-blind peer review). No truncation unless the text exceeds the model's context window.

**Output:** A structured assessment (~500–1,000 words) covering five dimensions — novelty, rigor, impact, timeliness, and strengths/limitations — plus numerical ratings (1.0–10.0) for overall score, significance, rigor, novelty, and clarity. Stored as `ai_impact_summary_thinking` on the paper document.

## Stage 2: Pairwise Comparison (Judge)

**Models:** Round-robin across GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro Preview (1 judge per pair, ensuring equal contribution from all three).

**Input per paper:** Abstract (≤1,500 chars) + the Opus 4.6 Thinking assessment from Stage 1. The judge does NOT see author names — only the abstract and the AI assessment.

**Output:** Binary winner (`paper1` or `paper2`) with brief reasoning (max 150 words). No ties allowed. Positional bias corrected via random 50/50 presentation order flip.

## Stage 3: Ranking Model — Regularized Win-Rate

Rankings use a **regularized win-rate**: `(wins + 0.5) / (matches + 1)`, mapped through a logistic function to scores centered at 1200. The +0.5 regularization (Jeffreys prior) prevents extreme scores for papers with few matches — a paper with 1 win out of 1 match scores 75%, not 100%. The effect is negligible above ~20 matches.

**Not Elo, not Bradley-Terry.** We systematically tested all three methods across all datasets at 7–218 matches/paper. The regularized win-rate correlates most strongly with human ground truth in every single case:

- **Bradley-Terry** tries to adjust for opponent strength ("beating a strong paper counts more"), but at 15–30 matches/paper the opponent strength estimates are too noisy and propagate errors throughout the ranking. Tested with priors from 0 to 50 — always worse than win-rate.
- **Real sequential Elo** introduces path-dependent variance (the order matches are processed affects final ratings). Papers have fixed quality, unlike chess players, so sequential updating adds noise without benefit.

**Caveat:** Win-rate is more sensitive to matchmaking bias than Bradley-Terry. A paper matched disproportionately against weak opponents gets an inflated score. This makes uniform random matchmaking essential — see §Matchmaking.

## Datasets & Ground Truth

- **8 ICLR topic subsets** (469 papers): Code Generation, Fairness, LLMs, Molecules, Optimization, Optimal Transport, PDEs, Protein Science
- **PeerRead ACL 2017** (80 papers)
- Human ground truth from reviewer scores (ICLR: 1–10 scale with only 6 distinct values used; PeerRead: 1–5 scale)
- Ties (same score for both papers) handled via coin-flip correction: assigned 50% random agreement. This is conservative — AI actually agrees with non-tying experts 73.5% on tied pairs, well above the 50% assumption.

## Key Results

### Primary benchmark (all pairs including within-tier)

This is the honest benchmark — AI is tested on the full difficulty spectrum including within-tier comparisons (e.g., Poster vs. Poster), at ~25–30 matches per paper.

| Metric | AI | Human ceiling (LOO) | AI advantage |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 68.7% | 66.6% (H-H) | +2.1pp |
| ρ vs Individual aggregate | **0.670** | 0.529 | **+0.141** |
| ρ vs Committee (tier decisions) | 0.648 | 0.520 | +0.128 |
| Top 10% overlap (vs Aggregate) | ~23% | — | expected ~43% at this ρ |
| Top 20% overlap (vs Aggregate) | ~40% | — | expected ~54% at this ρ |

AI's top-K% overlap is consistently below what the overall ρ would predict, indicating errors concentrate in the ranking tails — the very best and worst papers are harder to identify than the overall correlation suggests.

### Legacy benchmark (cross-tier pairs only — for reference)

These numbers are **inflated** because AI was only tested on easier cross-tier pairs (see §Known Limitations). Retained for comparison with earlier reports.

| Metric | AI | Human ceiling | AI advantage |
|---|---|---|---|
| ρ vs Individual aggregate | 0.739 | 0.660 | +0.078 |
| ρ vs Committee | 0.762 | 0.681 | +0.081 |

Note: AI's advantage **increases** from +0.078 to +0.141 in the honest benchmark. Within-tier pairs hurt the human ceiling more than AI, because the human ceiling relies on a coarse 6-value rating scale that produces mostly ties on similar-quality papers.

### PW vs SI comparison (all pairs)

Pairwise (PW) and Single-Item (SI) scoring are compared on the same datasets:

| Metric | Pairwise | Single-Item | PW advantage |
|---|---|---|---|
| Pairwise accuracy (same pairs) | 75.5% | 74.7% | +0.8pp |
| ρ vs Individual aggregate | 0.652 | 0.617 | +0.035 |

PW's advantage over SI shrinks dramatically with within-tier pairs included (was +0.12 in the legacy benchmark). On individual datasets like Codegen, SI actually beats PW. The two rankings are 86% correlated — combining them via weighted averaging, SI-as-pairwise injection, or gap-based methods provides at most +0.002 improvement over PW alone.

## Known Limitations

### 1. Cross-Tier Pair Selection Bias (Fixed Mar 2026)

The original matchmaking algorithm excluded within-tier comparisons entirely. All legacy metrics are computed on this biased pair set. Fixed: the filter has been removed and within-tier matches have been generated at their natural proportions for all 8 ICLR datasets. The primary benchmark pages now include within-tier pairs; the legacy pages are retained for reference.

### 2. Within-Tier Ground Truth Limitation

Within-tier pairs (e.g., Poster vs. Poster) are largely invisible to the committee ground truth — both papers are in the same tier by definition. AI pairwise accuracy on within-tier pairs is ~60%, human ~58%. Neither can reliably rank papers the committee considers equivalent.

This is not an AI failure — it's an ill-defined task. The ρ drop when including within-tier pairs reflects the **ground truth ceiling**, not a model weakness. Adding more within-tier matches does not improve ρ (verified: monotonically decreasing with more within-tier data against committee GT).

### 3. Win-Rate Sensitivity to Matchmaking

The win-rate ignores opponent strength. Non-uniform matchmaking can bias rankings — the live tournament's score-proximity targeting could introduce systematic bias. The validation benchmark mitigates this with coverage-based round-robin.

### 4. Author Visibility in Stage 1

The summarizer reads author names from PDFs. Prestige bias could leak into assessments that then influence the judge.

### 5. Coarse Human Rating Scale

ICLR uses only 6 distinct values (1, 3, 5, 6, 8, 10) with 67% of ratings being 5 or 6, producing a ~39% tie rate. This limits the human signal available for comparison, especially for within-tier discrimination.

### 6. Self-Referential Architecture

Opus 4.6 both summarizes (Stage 1) and judges (Stage 2, as 1 of 3 round-robin models). This could create systematic biases that inflate agreement metrics.

## Matchmaking

### Live Tournament

Goal-directed adaptive matchmaking targeting convergence: Wilson 95% CI margin ≤15% (general papers) / ≤10% (top-K papers), plus direct comparison of all top-K paper pairs. The system idles when goals are met (event-driven, no polling). Categories processed 2 at a time (configurable via `parallel_categories` admin setting). Fetch interval configurable (default 6 hours).

### Validation Benchmark

Coverage-based round-robin from **all possible pairs** (no tier filtering, no score-proximity). Every paper gets at least ~25–30 matches. Within-tier pairs are included at their natural proportion in the dataset. For datasets that initially had fewer matches, additional rounds were run to bring density to ~30 M/P.

| Dataset | Papers | Total matches | Avg M/P |
|---|---|---|---|
| ICLR Code Generation | 62 | 1,635 | 26.5 |
| ICLR Fairness | 68 | 1,020 | 30.0 |
| ICLR LLMs | 73 | 1,427 | 19.1 |
| ICLR Molecules | 46 | 690 | 30.0 |
| ICLR Optimization | 42 | 630 | 30.0 |
| ICLR Optimal Transport | 52 | 982 | 18.9 |
| ICLR PDEs & Dyn. Systems | 80 | 1,282 | 16.0 |
| ICLR Protein Science | 46 | 677 | 14.7 |
| PeerRead ACL 2017 | 80 | 1,118 | 27.9 |

Convergence testing shows ρ gains are marginal beyond 25 M/P — the curve has largely flattened for cross-tier signal. Within-tier ρ (vs Committee) is essentially flat regardless of match density, confirming the ground truth limitation.

## Ceiling Analysis

The committee's 4-tier system (Oral/Spotlight/Poster/Reject) imposes a theoretical maximum ρ ≈ 0.878 — a perfect predictor that assigns every paper to the correct tier but randomly orders within tiers cannot exceed this.

With within-tier pairs included, AI reaches **74%** of this ceiling (ρ = 0.648), while a single human expert reaches 59% (ρ = 0.520). On the legacy cross-tier-only benchmark, AI reached 87% (0.762) vs human 78% (0.681) — but these numbers overstate performance because the pair set excluded the within-tier comparisons where both methods are weakest.

AI's advantage over the human ceiling is consistent across all ground truth methods and increases when within-tier pairs are included (+0.141 vs +0.078 on the legacy benchmark). This is because human experts are more affected by the coarse rating scale on within-tier pairs than AI is.
