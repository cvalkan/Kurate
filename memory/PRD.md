# PaperSumo PRD

## Original Problem Statement
Build a robust system for validating AI model performance on scientific papers via a leaderboard tournament where different LLMs act as judges to rank papers.

## Architecture
- **Frontend**: React + Shadcn/UI + Tailwind CSS
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (round-robin judging)
- **Auth**: JWT token-based (localStorage) for users, session token for admin
- **Stopping Criterion**: Wilson Confidence Interval (12% margin default)

## Core Features (Implemented)
- Multi-category paper tournaments (arXiv + ChemRxiv sources)
- AI-powered pairwise paper comparison with 3 LLM judges
- Wilson CI convergence-based stopping criterion
- Leaderboard with ELO scoring and win rates
- Admin dashboard with separate fetch/tournament controls
- Cost tracking and usage statistics
- Paper detail pages with LaTeX rendering and AI summaries
- Model analysis and validation pages
- Prediction experiment (Surprisingly Popular)

## What's Been Implemented (Latest Session - Feb 17, 2026)
- **Fixed Admin Overview Page**: Removed duplicate stats from Paper Ingestion (was showing total papers, now shows fetchable count) and Tournament sections (was showing matches/failed, now shows only convergence goals)
- **Removed Recent Matches**: Removed duplicate "Recent Matches" collapsible section, keeping only "Recent Comparisons" with winner/loser/model display
- **Fixed "Last fetched: never"**: Resolved MongoDB nested key lookup issue for `last_fetch_at` settings; scheduler now hydrates from settings on startup
- **Fixed "Check for new papers" returning 50**: Backend now queries real arXiv API to count new papers instead of crude estimate; each category returns its actual count
- **Added loser_title to recent matches**: Backend enriches match data with both winner and loser titles
- **Fixed toggle-fetch/toggle-compare 404 bug**: MongoDB `find_one` with projection returning empty dict `{}` was treated as falsy (not found). Fixed by checking `is None` and including `tournament_id` in projection.
- **Global pause now disables auto-fetch**: Auto-fetch toggle is disabled when system is globally paused, with "(system paused)" indicator

## Prioritized Backlog

### P0 (Critical)
- None

### P1 (High Priority)
- Complete `iclr-llms` dataset data generation
- Deploy changes to production (preview significantly diverged)

### P2 (Medium)
- Add missing HTTP security headers
- Experiment with different LLMs for summaries (e.g., Gemini 3 Flash)
- Full security scan review

### P3 (Low/Future)
- Refactor data processing logic from routers into `backend/services` layer
