# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `npx serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro
- **Input format**: Abstract + AI impact assessment summary
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Recent Updates (Mar 7 2026)

### Ground Truth Scoring Fix (Critical)
- **Root cause**: `build_paper_gt_scores()` prioritized coarse tier decisions (Oral=4, Poster=2) over granular human evaluation ratings (21+ unique values)
- **Impact**: For MIDL (only 2 tiers), 60% of matches were filtered as "same-tier", truncating convergence curves to ~4 avg matches/paper
- **Fix**: Changed priority order: `h1_avg_rating` > `composite_score` > evaluation avg > tier decision
- **Result**: All 607 MIDL thinking matches now included; convergence extends to 15 avg matches/paper
- **Spearman rho consistency**: Convergence (0.348) now aligns with Single-Item scoring (0.3177) — both use evaluation-based GT
- **Side effect**: All datasets benefit from more granular GT; precomputed data updated

### Frontend Build URL Fix
- Frontend was serving a stale production build with old backend URL (`llm-tournament-debug.preview.emergentagent.com`)
- Rebuilt with correct `REACT_APP_BACKEND_URL=https://paper-judge-arena-1.preview.emergentagent.com`

### Matchmaking Improvement (Elo-Aware Opponent Selection)
- Established opponent selection now picks the paper closest to the new paper's estimated Elo
- Top-K identification now uses regularized Elo scores instead of raw win-rate
- Post-convergence repeat logic now re-matches Elo-adjacent papers
- Simulation showed +3.4% ranking correlation improvement

### GPT 5.4 Summarizer Experiment
- Added GPT 5.4 as experimental summarizer using user's own OpenAI key
- Results: GPT-5.4 accuracy=76.6%, tied with Opus 4.5, below Opus 4.6 Thinking (85.4%)

### Pipeline Fixes (Mar 6 2026)
- Fixed summary filter lost after PDF re-fetch
- Fixed failed PDF downloads permanently excluding papers
- PDF download cap increased from 200 to 500
- Pause now stops summary generation instantly
- Real-time summary generation progress tracking

## Pending Tasks
- (P1) Refactor MIDL experiment pipeline into robust background task
- (P2) Further refactor validation.py (2500+ lines)
- (P2) Improve summary generation failure tracking (partial failures per model)
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict

## Key Issue: Budget Exhaustion
The Emergent LLM key budget gets exhausted during large-scale summary generation. User needs to top up via Profile → Universal Key → Add Balance.

## Completed Work
- Pre-computation system for production deployment
- Single-Item Scoring experiment (competitive with pairwise)
- Institutional Bias Analysis with controlled same-pair analysis
- AlphaXiv Integration for community popularity data
- HTTP Security Headers middleware
- Ground truth scoring fix for convergence consistency
