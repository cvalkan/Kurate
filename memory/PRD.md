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
- Majority (2/3+): 77.2% — worse than best single model (Opus 4.5: 79.5%)
- Unanimity (3/3): 84.9% — beats single models but on filtered "easy" subset (71% of pairs)
- At equal API cost (~15 calls/paper): extract ρ≈0.684, unanimity ρ≈0.702 — nearly identical

### Intransitive Cycles (NEW)
- GPT-5.2: 3.2% cycle rate (most inconsistent)
- Claude Opus: 0% (perfectly transitive on 3-model pairs)
- Majority/Unanimity: 0% cycles — ensemble eliminates intransitivity
- All pooled (2421 pairs): 1.4% cycle rate

## Completed (Latest Session)
- [Feb 28] P0 fix: Aggregate/Significance BT ranking tables (VERIFIED)
- [Feb 28] Tie-Allowed Experiment: prompt, endpoints, page, 500 matches
- [Feb 28] Ensemble modes: Majority/Unanimity tabs on tournament page + convergence
- [Feb 28] Unanimity on Multi-Model page with BT correlation
- [Feb 28] Intransitive Cycle Analysis on Multi-Model page

## Pending
- (P1) Fix summary provenance for elife-comp-sys-bio
- (P2) HTTP security headers
- (Future) Structured judge prompt experiment
- (Future) Refactor iclr_deep_dive.py
