# PRD — Kurate.org AI Paper Ranking Platform

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. Implement Multiple AI Reviewer Personas, optimized parallel batch pipeline, arXiv revision handling, convergence charts, X outreach, Reddit Pixel, Plausible analytics, and Gmail-based personalized Email Outreach pipeline.

## Core Product
Full-stack AI paper-judging platform (FastAPI + React + MongoDB) using TrueSkill models to rank academic papers via automated pairwise tournaments with Claude Opus, GPT-5.2, and Gemini 3 Pro.

## What's Been Implemented

### Email Outreach Pipeline (NEW — April 28, 2026)
- **Backend**: `/api/admin/email-outreach/*` routes — flat medalists list, template CRUD, email extraction (LLM + manual), send via Gmail OAuth, history tracking
- **Frontend**: `/admin/outreach/email` — flat table layout matching Activity page style, auto-extraction on load, blue/amber/green badges for email status, period selector, search, template editor
- **Admin tab bar**: "Email Outreach" tab added next to "X Outreach" in admin dashboard
- **DB collections**: `author_emails`, `email_sends`, templates in `settings`

### Previously Completed
- Reddit Pixel + Plausible Analytics integration
- SignupCTA component for homepage conversions
- X/Twitter Outreach pipeline (handle discovery, like, follow, quote tweet)
- Gmail OAuth for email sending (congrats.py)
- Leaderboard archives (weekly + monthly) with archive_frequency config
- TrueSkill ranking, convergence charts, validation hub
- Multiple LLM integration (Claude Opus 4.6, GPT-5.2, Gemini 3 Pro)

## Known Issues
- P0: Emergent LLM Key budget may be depleted (stalls summarizing/matching)
- P1: Missing GPT/Gemini SI Ratings
- P2: Duplicate medals in archives
- Recurring: Mobile Twitter/X unfurling blocked by Cloudflare

## Backlog (Prioritized)
- P0: Multiple Reviewer Personas (blocked by LLM budget)
- P1: Sub-topic Matchmaking (LLM Classifier)
- P1: Author Verification (ORCID OAuth)
- P1: Architecture Split (KURATE_ROLE env var)
- P1: Circular import refactor
- P2: httpOnly cookie auth migration
- P2: Refactor monolithic leaderboard.py

## Key Files
- `/app/backend/routers/email_outreach.py`
- `/app/frontend/src/pages/EmailOutreachPage.jsx`
- `/app/frontend/src/pages/AdminPage.jsx` (tab bar)
- `/app/backend/routers/congrats.py` (Gmail OAuth)
- `/app/backend/routers/outreach.py` (X outreach)

## Credentials
- Admin: password `papersumo2025`
