# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `npx serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org
- **Preview**: llm-ranker.preview.emergentagent.com

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro
- **Input format**: Abstract + AI impact assessment summary
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Current State (Mar 12 2026)
- 1218 papers, 39022 matches, 10 active categories
- 25 validation datasets, 141963 validation matches, 3158 validation papers
- All validation experiments publicly accessible
- Leaderboard shows Rating and Gap columns (togglable via admin)
- Security headers fully implemented
- All endpoints returning 200, no broken pages
- Archive system fully operational on production (109 snapshots backfilled Mar 12 2026)

## Deployment Readiness (Mar 9 2026)

### Verified
- Frontend rebuilt with correct REACT_APP_BACKEND_URL (llm-ranker)
- All backend test files updated with correct URLs
- All API endpoints tested and returning 200
- Security headers present (HSTS, CSP, X-Frame-Options, etc.)
- MongoDB indexes all created (papers, matches, validation_*, settings)
- Precomputed experiment caches loading on startup (172 caches)
- Admin login working with correct password
- All frontend pages rendering correctly
- Leaderboard Rating/Gap columns visible and sortable
- Validation Hub showing all sections (Pairwise, Single-Item, Tournament, Experiments)

### Performance
- Health: ~200ms, Categories: ~130ms, Leaderboard: ~200ms
- Validation endpoints: 110-280ms (cached)
- Background cache refresh: ~1s every 60s
- Analysis cache refresh: every 5 minutes
- Connection pool: 50 max, 10 min

## Recent Fix (Mar 9 2026)
- **Admin rating-status performance**: Moved per-category rating counts into the background leaderboard cache. The `/api/admin/rating-status` endpoint now accepts a `category` param and reads from pre-computed cache (~16ms) instead of doing 2-4 MongoDB `count_documents` calls (~200ms each). Category switching in admin panel is now instant.

## Pending Tasks
- (P2) Further refactor validation.py (2500+ lines)
- (P2) Improve summary generation failure tracking (partial failures per model)
- (P2) Verify all ICLR datasets fully scored in single-item experiment
- (Future) Consolidate MIDL experiment pipeline into single robust background task
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict

## Key Issue: Budget Exhaustion
The Emergent LLM key budget gets exhausted during large-scale summary generation. User needs to top up via Profile -> Universal Key -> Add Balance.

## Completed Work
- Linkable validation sub-URLs via ?v= search params (Mar 11 2026)
- Higher resolution leaderboard convergence matching validation charts (Mar 11 2026)
- Auto per-model SI rating extraction from summaries in scheduler (Mar 11 2026)
- Precomputed analysis caches for Model Correlation page (Mar 11 2026)
- Log/linear scale toggle on convergence charts (Mar 11 2026)
- Single-Item Rating Analysis section with model toggle on Model Analysis page (Mar 11 2026)
- Pre-computation system for production deployment
- Single-Item Scoring experiment - run on eLife (Cancer + Neuro), ICLR (7 datasets), MIDL, PeerRead, RH-50, Qeios Social
- "Surprisingly Popular" analysis: BT_rank - SI_rank as independent quality predictor
- Controlled PW Thinking Judge experiment on Qeios + RH-50
- Institutional Bias Analysis with controlled same-pair analysis
- AlphaXiv Integration for community popularity data
- HTTP Security Headers middleware
- Convergence chart fix
- Live Leaderboard Metric Integration (Rating + Gap columns)
- Admin controls for leaderboard column visibility
- Non-blocking rating generation for existing papers
- Comprehensive Validation Summary Report page
- Frontend rebuild for llm-ranker fork (Mar 9 2026)
- Deployment readiness verification (Mar 9 2026)
