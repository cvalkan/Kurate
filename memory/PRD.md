# PRD — Kurate.org AI Paper Ranking Platform

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. Implement Multiple AI Reviewer Personas, optimized parallel batch pipeline, arXiv revision handling, convergence charts, X outreach, Reddit Pixel, Plausible analytics, and Gmail-based personalized Email Outreach pipeline.

## Core Product
Full-stack AI paper-judging platform (FastAPI + React + MongoDB) using TrueSkill models to rank academic papers via automated pairwise tournaments with Claude Opus, GPT-5.2, and Gemini 3 Pro.

## What's Been Implemented

### Archive Loop Fix (April 28, 2026)
- **Fixed**: `_bg_archive_loop` now runs with `catch_up=True` on startup — creates current week/month archives regardless of day-of-week
- **Fixed**: Double-count bug in monthly archive creation (`created += 1` was duplicated)
- **Root cause**: Server restarts after Monday 00:05 UTC caused the weekly archive window to be permanently missed
- Manually triggered W18 archive creation on production (13 cats, 240 papers)

### Production Investigation (April 28, 2026)
- **964 papers** missing `pdf_link` — arXiv API didn't return PDF link element; all have `arxiv_id` so fixable
- **950 papers** have abstract-only summaries that entered tournaments (historical, Feb-March 2026)
- **Not a current issue**: last 30 days show 0 papers missing full_text
- Email extraction: 59% success rate via regex on 100 sampled top-3 papers

### Email Outreach Pipeline (April 28, 2026)
- Backend: `/api/admin/email-outreach/*` routes — flat medalists list, template CRUD, email extraction (LLM + manual), send via Gmail OAuth, history tracking
- Frontend: `/admin/outreach/email` — flat table layout, auto-extraction on load, blue/amber/green badges for email status
- Admin tab bar: "Email Outreach" tab added next to "X Outreach"

### Previously Completed
- Reddit Pixel + Plausible Analytics integration
- SignupCTA component for homepage conversions
- X/Twitter Outreach pipeline (handle discovery, like, follow, quote tweet)
- Gmail OAuth for email sending (congrats.py)
- Leaderboard archives (weekly + monthly) with archive_frequency config
- TrueSkill ranking, convergence charts, validation hub

## Known Issues
- P0: Emergent LLM Key budget may be depleted (stalls summarizing/matching)
- P1: 964 papers missing pdf_link need backfill + 950 need re-summarization from full text
- P1: Missing GPT/Gemini SI Ratings
- P2: Duplicate medals in archives
- Recurring: Mobile Twitter/X unfurling blocked by Cloudflare

## Backlog (Prioritized)
- P0: Backfill pdf_link for 964 papers, re-summarize 950 abstract-only papers
- P0: Multiple Reviewer Personas (blocked by LLM budget)
- P1: Regex-first email extraction (free) with LLM fallback
- P1: Sub-topic Matchmaking (LLM Classifier)
- P1: Author Verification (ORCID OAuth)
- P1: Architecture Split (KURATE_ROLE env var)
- P1: Circular import refactor
- P2: httpOnly cookie auth migration
- P2: Refactor monolithic leaderboard.py

## Key Files
- `/app/backend/routers/leaderboard.py` (archive loop fix: lines 425-451, 1767-1797)
- `/app/backend/routers/email_outreach.py`
- `/app/frontend/src/pages/EmailOutreachPage.jsx`
- `/app/frontend/src/pages/AdminPage.jsx` (tab bar)
- `/app/backend/services/scheduler.py` (PDF download pipeline)

## Credentials
- Admin: password `papersumo2025`
