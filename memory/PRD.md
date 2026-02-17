# PaperSumo PRD

## Original Problem Statement
Build a robust system for validating AI model performance on scientific papers via a leaderboard tournament where different LLMs act as judges to rank papers.

## Architecture
- **Frontend**: React + Shadcn/UI + Tailwind CSS
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (round-robin judging)
- **Auth**: JWT token-based (localStorage) for users, session token for admin
- **Convergence**: Two-tier Wilson CI (10% top-K, 15% general)

## Core Features (Implemented)
- Multi-category paper tournaments (arXiv + ChemRxiv sources)
- AI-powered pairwise paper comparison with 3 LLM judges
- **Two-tier Wilson CI convergence** (tight for top-K, loose for general)
- **Goal-directed matchmaking** (neediest papers first, then top-K cross-matches)
- Leaderboard with ELO scoring and win rates
- Admin dashboard with separate fetch/tournament controls
- Cost tracking and usage statistics
- Paper detail pages with LaTeX rendering and AI summaries

## Convergence Model (Current)
- **Goal 1**: General papers CI ≤ 15% (configurable via `ci_target_general`)
- **Goal 2**: Top-K papers CI ≤ 10% (configurable via `ci_target`)
- **Goal 3**: All top-K pairs cross-matched
- No min/max match caps — papers get matched until CI converges

## Matchmaking (Current)
1. Match neediest papers first (widest CI margin vs their tier's target)
2. Top-K cross-matches after rankings stabilize
3. Repeat pairs only after all goals met

## Prioritized Backlog

### P1 (High Priority)
- Deploy to production (preview significantly diverged)

### P2 (Medium)
- Add HTTP security headers
- Experiment with different LLMs for summaries

### P3 (Low/Future)
- Refactor data processing logic from routers into services layer
