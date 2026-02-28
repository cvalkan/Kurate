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
- All convergence and tournament computations filter same-tier matches

### Deep Dive (2-Pass): NULL RESULT
### Extended Thinking: NULL RESULT
### Tie-Allowed Judging: NEAR-NULL (0.4% tie rate)
### Summarizer A/B: Opus 4.5 vs 4.6 — SIGNIFICANT (+2.1pp)

### Ensemble Voting
- Majority (2/3+): worse than best single model
- Unanimity (3/3): higher accuracy but on filtered "easy" subset
- At equal API cost: nearly identical performance

### Intransitive Cycles (Aggregate)
- 22 datasets analyzed, 336K+ triples
- Claude Opus: 0.31% cycles (most transitive)
- GPT-5.2: 2.92%, Gemini 3 Pro: 2.50%
- Majority: 0.04% (near-zero), Unanimity: 0% (perfect)
- Close-score triples: ~4% cycles vs far-score: ~2%

## Completed (Latest Session)
- [Feb 28] P0 fix: Aggregate/Significance BT ranking tables (VERIFIED)
- [Feb 28] Tie-Allowed Experiment: prompt, endpoints, page, 500 matches
- [Feb 28] Ensemble modes: Majority/Unanimity tabs on tournament page + convergence
- [Feb 28] Unanimity on Multi-Model page with BT correlation
- [Feb 28] Intransitive Cycle Analysis: per-dataset + aggregate experiment page

## Pending
- (P1) Fix summary provenance for elife-comp-sys-bio
- (P2) HTTP security headers
- (Future) Structured judge prompt experiment
- (Future) Refactor iclr_deep_dive.py
