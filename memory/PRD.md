# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Key Findings (Feb 28 2026)

### Cross-Tier Filter
- All convergence and tournament computations now filter same-tier matches
- Saved 30-60% LLM budget, improved rho across all datasets

### Deep Dive (2-Pass): NULL RESULT
- Corrected results: 0.0-1.5pp lift across all datasets (none significant)

### Extended Thinking: NULL RESULT
- Opus 4.6 with 10K thinking token budget produces identical accuracy to standard Opus 4.6

### Summarizer A/B: Opus 4.5 vs 4.6 — SIGNIFICANT
- +2.1pp lift (71.8% -> 73.9%), McNemar p=0.0007 on 1582 pairs

### Tie-Allowed Judging: NEAR-NULL RESULT
- Modified prompt allowing "tie" when papers are close
- 500 matches on iclr-llm: 0.4% tie rate (2/500), +0.8pp lift (not significant, p=0.58)
- LLMs almost never declare ties even when given the option

### Ensemble Voting (NEW)
- Built from extract-mode matches where all 3 models (GPT-5.2, Opus 4.5, Gemini 3 Pro) judged the same pair
- **Majority (2/3+)**: 72.1% AI vs Expert on 494 pairs — slightly WORSE than best single model
- **Unanimity (3/3)**: 79.9% AI vs Expert on 357 pairs — beats single models BUT on filtered "easy" subset
- Unanimity filters to pairs where all models agree, cherry-picking easier decisions

## Completed (Latest Session)
- [Feb 28] Fixed identical Aggregate/Significance BT ranking lists on Pairwise page (VERIFIED)
- [Feb 28] Built Tie-Allowed Experiment: new prompt, backend endpoints, frontend page, ran 500 matches on iclr-llm
- [Feb 28] Built Ensemble Voting modes: Majority Vote and Unanimity derived from extract-mode 3-model data, integrated into tournament page as mode tabs with convergence charts. Added per-mode descriptions.

## Pending
- (P1) Fix summary provenance for elife-comp-sys-bio (wipe + regenerate all 80 summaries)
- (P2) HTTP security headers
- (Future) New experiment: "Structured judge prompt"
- (Future) Refactor iclr_deep_dive.py into smaller service files
