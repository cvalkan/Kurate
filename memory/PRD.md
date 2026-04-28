# PRD — Kurate.org AI Paper Ranking Platform

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. Implement Multiple AI Reviewer Personas, optimized parallel batch pipeline, arXiv revision handling, convergence charts, X outreach, Reddit Pixel, Plausible analytics, and Gmail-based personalized Email Outreach pipeline.

## Core Product
Full-stack AI paper-judging platform (FastAPI + React + MongoDB) using TrueSkill models to rank academic papers via automated pairwise tournaments with Claude Opus, GPT-5.2, and Gemini 3 Pro.

## What's Been Implemented (This Session)

### Email Outreach Pipeline
- **Backend**: `/api/admin/email-outreach/*` — flat medalists list, template CRUD, LLM email extraction with on-demand PDF download, send via Gmail OAuth with inline badge, test-send to roblauko@gmail.com, history tracking
- **Frontend**: `/admin/outreach/email` — flat table layout, auto-extraction on load, badges for email status, period selector, search, template editor, Test button per paper
- **Template**: Subject + body with `{{author_name}}`, `{{paper_title}}`, `{{category}}`, `{{rank}}`, `{{period}}`, `{{total_papers}}`, `{{leaderboard_url}}`, inline badge PNG
- **Admin tab bar**: "Email Outreach" tab added next to "X Outreach"

### Archive Loop Fix
- `create_archive_snapshot` now archives PREVIOUS week/month (not current)
- Startup catch-up: `run_archive_snapshots(catch_up=True)` fills gaps from missed Monday windows
- Fixed double-count bug in monthly archive creation
- Manually triggered W18 on production (needs deletion — premature)

### Production Investigation
- 964 papers missing `pdf_link` — historical issue (Feb-March 2026), not occurring in last 30 days
- 950 papers have abstract-only summaries that entered tournaments
- On-demand PDF download in extraction backfills missing `full_text`

## Known Issues
- P0: Emergent LLM Key budget depleted (blocks email extraction, summarizing, matching)
- P0: Premature W18 archive on production needs deletion after deploy
- P1: 964 legacy papers need `pdf_link` backfill
- P1: Missing GPT/Gemini SI Ratings
- P2: Duplicate medals in archives

## Backlog
- P0: Multiple Reviewer Personas (blocked by LLM budget)
- P1: Sub-topic Matchmaking, Author Verification (ORCID OAuth)
- P1: Architecture Split (KURATE_ROLE env var), circular import refactor
- P2: httpOnly cookie auth, refactor monolithic leaderboard.py

## Key Files
- `/app/backend/routers/email_outreach.py` — email pipeline
- `/app/backend/routers/leaderboard.py` — archive loop fix (lines 425-451, 1648-1700, 1774-1800)
- `/app/backend/routers/admin.py` — delete archive endpoint
- `/app/frontend/src/pages/EmailOutreachPage.jsx` — email outreach UI
- `/app/frontend/src/pages/AdminPage.jsx` — tab bar

## Credentials
- Admin: password `papersumo2025`
- Test send recipient: roblauko@gmail.com
