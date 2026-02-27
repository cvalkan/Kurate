# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Key Findings (Feb 27 2026)

### Cross-Tier Filter
- All convergence and tournament computations now filter same-tier matches
- Saved 30-60% LLM budget, improved ρ across all datasets
- Tournament pair selection only generates cross-tier pairs

### Deep Dive (2-Pass): NULL RESULT
- BUG FIXED: `compute_analysis()` was comparing against Opus 4.5 baseline instead of Opus 4.6
- Corrected results: 0.0-1.5pp lift across all datasets (none significant)
- The model upgrade (4.5→4.6) was doing all the work, not the 2-pass methodology

### Extended Thinking: NULL RESULT
- Opus 4.6 with 10K thinking token budget produces identical accuracy to standard Opus 4.6
- iclr-codegen: 62.7% vs 62.7%, McNemar p=0.79, discordant 7:7

### Summarizer A/B: Opus 4.5 vs 4.6 — SIGNIFICANT
- +2.1pp lift (71.8% → 73.9%), McNemar p=0.0007 on 1582 pairs

### Dataset Convergence Analysis
- GT resolution = sample efficiency factor, not fundamental barrier
- All datasets distinguishable from chance on non-tie pairwise accuracy
- elife-microbiology: 78.0% [75.8%, 80.0%] after 500 additional opus46 matches

## UI Structure
### Experiments (Admin)
- **Opus 4.5 vs 4.6**: Summarizer A/B test
- **Summary Bias**: Biomolecules, Economics, Comp Physics
- **Second Pass (Deep Dive)**: 8 datasets (all null vs opus46 baseline)
- **Extended Thinking**: Opus 4.6 + thinking budget (null result)

## Pending
- Run extended thinking on more datasets to confirm null
- Run more matches on iclr-optimization (ρ=0.859, widest CI)
- Gap-stratified human accuracy visualization
- HTTP security headers
