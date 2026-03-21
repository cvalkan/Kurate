# AI vs. Human Validation Pipeline — Methodology Report

## Overview

The AI vs. Human benchmark evaluates how well AI pairwise judges agree with human peer reviewers on paper quality rankings. The pipeline uses a two-stage architecture: first summarize, then judge.

## Stage 1: AI Impact Assessment (Summarizer)

**Model:** Claude Opus 4.6 with Extended Thinking (budget: 10,000 thinking tokens)

**Input:** Full paper PDF text + abstract, including author names (analogous to single-blind peer review).

**Output:** A structured assessment (~500–1,000 words) covering novelty, rigor, impact, timeliness, and strengths/limitations, plus numerical ratings (1.0–10.0) for overall score, significance, rigor, novelty, and clarity.

## Stage 2: Pairwise Comparison (Judge)

**Models:** Round-robin across GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro Preview (1 judge per pair).

**Input per paper:** Abstract (≤1,500 chars) + the Opus 4.6 Thinking assessment from Stage 1.

**Output:** Binary winner (`paper1` or `paper2`) with brief reasoning. No ties. Positional bias corrected via random presentation order.

**Note:** The judge does NOT see author names — only the abstract and AI assessment.

## Stage 3: Ranking Model — Regularized Win-Rate

Rankings use `(wins + 0.5) / (matches + 1)` mapped through a logistic function to scores centered at 1200. The +0.5 regularization (Jeffreys prior) prevents extreme scores for papers with few matches.

**Not Elo, not Bradley-Terry.** We tested all three across all datasets at 7–218 matches/paper. Regularized win-rate correlates most strongly with human ground truth in every case. Bradley-Terry's opponent-strength adjustment adds noise at this data density. Real Elo's sequential updates introduce path-dependent variance.

**Caveat:** Win-rate is sensitive to matchmaking bias — a paper matched disproportionately against weak opponents gets inflated. This makes uniform random matchmaking essential (see §Matchmaking).

## Datasets & Ground Truth

- **8 ICLR topic subsets** (469 papers) + **PeerRead ACL 2017** (80 papers)
- Human ground truth from reviewer scores (ICLR: 1–10 scale, 6 distinct values; PeerRead: 1–5)
- Ties handled via coin-flip correction (50% random agreement)

## Key Results

### Primary benchmark (all pairs including within-tier, ~25–30 M/P)

| Metric | AI | Human ceiling (LOO) | AI advantage |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 68.7% | 66.6% (H-H) | +2.1pp |
| ρ vs Individual aggregate | **0.670** | 0.529 | **+0.141** |
| ρ vs Committee | 0.648 | 0.520 | +0.128 |
| Top 10% overlap (vs Aggregate) | ~23% | — | expected: ~43% |
| Top 20% overlap (vs Aggregate) | ~40% | — | expected: ~54% |

### Legacy benchmark (cross-tier pairs only, inflated — for reference)

| Metric | AI | Human ceiling | AI advantage |
|---|---|---|---|
| ρ vs Individual aggregate | 0.739 | 0.660 | +0.078 |
| ρ vs Committee | 0.762 | 0.681 | +0.081 |

The legacy numbers are inflated because AI was only tested on easier cross-tier pairs.

### PW vs SI (all pairs)

| Metric | Pairwise | Single-Item | PW advantage |
|---|---|---|---|
| ρ vs Individual aggregate | 0.652 | 0.617 | +0.035 |

PW and SI rankings are 86% correlated. Combining them provides negligible improvement (+0.002 at best). We tested gap-based sampling, match weighting, and SI-as-pairwise injection — none beats uniform-weight PW alone.

## Known Limitations

### 1. Cross-Tier Pair Selection Bias (Fixed Mar 2026)

The original matchmaking excluded within-tier comparisons (e.g., Poster vs. Poster). This inflated all legacy metrics. Fixed: within-tier matches generated at natural proportions for all datasets.

### 2. Within-Tier Ground Truth Limitation

Within-tier pairs are invisible to the committee ground truth. AI accuracy on within-tier is ~60%, human ~58% — neither can reliably rank papers the committee considers equivalent. The ρ drop when including within-tier reflects the ground truth ceiling, not a model weakness.

### 3. Win-Rate Sensitivity to Matchmaking

The win-rate ignores opponent strength. Non-uniform matchmaking (e.g., the live tournament's score-proximity targeting) can bias rankings. The validation benchmark uses coverage-based round-robin to ensure fairness.

### 4. Author Visibility in Stage 1

The summarizer reads author names from PDFs. Prestige bias could leak into assessments.

### 5. Coarse Human Rating Scale

ICLR uses only 6 distinct values with 67% of ratings being 5 or 6, producing a ~39% tie rate.

### 6. Self-Referential Architecture

Opus 4.6 both summarizes and judges (as 1 of 3 round-robin models), potentially creating systematic biases.

## Matchmaking

### Live Tournament

Goal-directed adaptive matchmaking with convergence targets: Wilson 95% CI margin ≤15% (general) / ≤10% (top-K), plus top-K cross-matching. Idles when goals are met (event-driven, no polling). Categories processed 2 at a time (configurable `parallel_categories`).

### Validation Benchmark

Simple coverage-based round-robin from all possible pairs (no tier filtering). Minimum ~25–30 matches per paper. Within-tier pairs included at natural proportions.

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

## Ceiling Analysis

The committee's 4-tier system (Oral/Spotlight/Poster/Reject) imposes a theoretical maximum ρ ≈ 0.878. With within-tier pairs included, AI reaches **74%** of this ceiling (0.648), a single expert reaches 59% (0.520). AI outperforms the human ceiling at all difficulty levels, though both are limited by the ground truth's inability to distinguish within-tier papers.
