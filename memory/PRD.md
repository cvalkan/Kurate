# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Optimal Configuration (as of Mar 1 2026)
- **Summarizer**: Opus 4.6 Thinking (best avg ρ, but margin over Opus 4.5 is small ~+0.02)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro (HIGH confidence this beats any single judge by +0.05-0.15 ρ)
- **Input format**: Abstract + AI impact assessment summary
- **Pair selection**: Cross-tier only (same-tier filtered out)

## Key Findings

### Summarizer Comparison (CORRECTED — same-pair, Mar 1)
Previous analysis was biased by pair selection. Corrected same-pair results (243 pairs, iclr-llm + iclr-codegen):
- Opus 4.6 Thinking: ρ=0.643, acc=81.1%
- Opus 4.5: ρ=0.624, acc=76.5%
- Opus 4.6: ρ=0.584, acc=78.6%
- Gemini 3 Pro: ρ=0.570, acc=75.7%
- GPT-5.2: ρ=0.556, acc=76.1%
- **Gap is only 0.087 ρ** — earlier biased analysis showed 0.336

### Opus 4.6 Thinking vs Opus 4.6 Standard (CORRECTED)
On exact same pairs: ρ=0.732 vs 0.733 — **essentially identical on ranking**. The +0.057 gap in the earlier report was entirely a pair-selection artifact. Thinking helps pairwise accuracy modestly (+0.7pp) but not ranking.

### Round-Robin vs Single Judge
HIGH confidence finding. On every summarizer and every dataset, round-robin beats single judge:
- Diversity benefit: +0.05-0.15 ρ
- Even the worst summarizer (Gemini) + round-robin beats the best summarizer + single judge

### Intransitive Cycles
- Format-normalized (same-pair): Gemini 1.03%, Opus 4.5 1.34%, GPT 1.66%
- Opus 4.6: 0.24% raw, 0.61% format-adjusted (2.51x factor for favorable input mix)
- Self-consistency bias REJECTED: models judging own summaries have MORE cycles, not fewer
- GPT + own summaries: 6.56% (worst); Gemini + own: 4.08%
- Claude summaries reduce cycles for ALL judges — quality signal, not self-alignment

### Consistency Analysis (Same Pairs vs All Pairs pages)
- Cross-format verdict flips: 7-18% (Abstract vs AI Summary highest)
- Cross-model flips: 13-16% (GPT vs Opus 4.5 highest)
- AI Summary format: lowest model disagreement (10.1%) and lowest cycles (1.0%)
- Abstract format: highest disagreement (18.6%) and highest cycles (4.26%)
- Same-pair heatmap ≈ All-pair heatmap (85-100% overlap, filter barely removes data)

### Tie-Allowed Judging: NEAR-NULL
- 500 matches on iclr-llm: 0.4% tie rate (2/500), +0.8pp lift (not significant p=0.58)

### Multi-Aspect Judging: NEGATIVE RESULT
- 5 dimensions (novelty, applications, rigor, breadth, timeliness)
- 2,847 matches across 8 ICLR datasets
- Aggregate (majority of 5): 77.8% vs holistic baseline 82.7% → **-4.9pp, significantly worse** (p<0.001)
- Every individual dimension worse than holistic
- BUT: agreement filter (holistic + Nov+Apps+Rigor agree) → 87.2% accuracy, ρ=0.736 (beats holistic's 0.729)
- Practical use: run both prompts, keep agreements → +4pp accuracy at 84% pair coverage

### Ensemble Voting
- Majority (2/3+): worse than best single model on accuracy
- Unanimity (3/3): higher accuracy but on filtered "easy" subset
- At equal API cost (3x per pair): nearly identical to single model

### Deep Dive (2-Pass): NULL RESULT
### Extended Thinking (summarizer budget): NULL on ranking, +0.7pp accuracy
### Summarizer A/B: Opus 4.5 vs 4.6 — +2.1pp accuracy (significant p=0.0007)

## CRITICAL METHODOLOGY NOTE
**Always compare on exact same pairs.** Multiple findings in this session were initially wrong due to pair-selection bias:
- Opus 4.6 Thinking advantage: 0.057 ρ (biased) → 0.000 ρ (same pairs)
- GPT summarizer: ρ=0.509 (biased) → 0.556 (same pairs)
- Gemini summarizer: ρ=0.396 (biased) → 0.570 (same pairs)

## Experiment Pages (under Experiments nav)
1. **Opus 4.5 vs 4.6** — Summarizer A/B, all datasets
2. **Summary Bias** — Biomolecules, Economics, Comp Physics
3. **Second Pass (Deep Dive)** — 8 datasets, null vs opus46 baseline
4. **Extended Thinking** — Opus 4.6 + thinking budget, null on ranking
5. **Tie-Allowed** — Modified prompt allowing ties, near-null
6. **Multi-Aspect** — 5-dimension judging, negative result but useful agreement filter
7. **Summarizer A/B (Cross-Model)** — GPT/Gemini/Opus same-pair comparison
8. **Consistency > Same Pairs** — Verdict flips, format-adjusted cycles, judge×summarizer breakdown
9. **Consistency > All Pairs** — Per-format cycle heatmap, aggregate bars, per-dataset table

## Completed (This Session — Feb 28 - Mar 1 2026)
- P0 fix: Aggregate/Significance BT ranking tables (VERIFIED)
- Tie-Allowed Experiment: prompt, endpoints, page, 500 matches
- Ensemble modes: Majority/Unanimity tabs on tournament page
- Intransitive Cycle Analysis: per-dataset + aggregate page
- Consistency Deep Dive: split into Same Pairs / All Pairs
- Format-normalized cycle comparison with adjustment factors
- Judge × Summarizer breakdown (self-consistency bias rejected)
- Multi-Aspect Experiment: 2,847 matches, 8 datasets, agreement filter finding
- Summarizer Cross-Model: GPT + Gemini summaries generated for 2 datasets
- Multiple corrections for pair-selection bias across earlier analyses
- Caching for slow endpoints (consistency-analysis, cycle-analysis-all)

## Pending
- (P1) Fix summary provenance for elife-comp-sys-bio (wipe + regenerate summaries)
- (P2) HTTP security headers
- (P3) Run GPT/Gemini summaries on more ICLR datasets for higher statistical power
- (Future) Chain-of-thought variant: multi-aspect reasoning → holistic verdict
- (Future) Refactor iclr_deep_dive.py into smaller service files
