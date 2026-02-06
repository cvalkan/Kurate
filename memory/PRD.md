# PaperSumo - Robotics Paper Leaderboard

## Original Problem Statement
Build a platform that automatically downloads new Robotics papers from arXiv daily, runs pairwise tournaments using full paper analysis via LLMs, and outputs a dynamically updated ranked leaderboard using Bradley-Terry scores.

## Core Requirements
- Automated daily arXiv fetch (cs.RO category)
- Full paper (PDF) deep analysis for comparisons
- Multi-model random selection (GPT 5.2, Claude Opus 4.5, Gemini 3 Pro)
- Bradley-Terry scoring with Wilson confidence intervals
- Adaptive matchmaking: UCB-based, top-K focused, sample efficient
- New papers calibrated against existing ranked papers
- Public leaderboard with date filtering (Today, Week, Month, All Time)
- Comparison logs accessible per paper
- Admin panel (simple password auth) for settings

## Tech Stack
- **Frontend:** React, React Router, Axios, Tailwind CSS, Shadcn UI, lucide-react
- **Backend:** FastAPI (modular), Motor (async MongoDB), httpx, PyPDF2
- **Database:** MongoDB (papers, matches, settings collections)
- **LLMs:** OpenAI GPT-5.2, Anthropic Claude Opus 4.5, Google Gemini 3 Pro (via Emergent LLM Key)
- **Background:** asyncio scheduler with configurable intervals

## Architecture
```
/app/backend/
├── server.py          # FastAPI entry point, startup, middleware
├── core/
│   ├── config.py      # DB, settings, models, prompts
│   └── auth.py        # Admin password auth (with defaults merge)
├── services/
│   ├── arxiv.py       # ArXiv API client with retry
│   ├── llm.py         # LLM comparison (multi-model random)
│   ├── ranking.py     # Bradley-Terry, Wilson CI, leaderboard
│   └── scheduler.py   # Background scheduler, adaptive matchmaking
├── routers/
│   ├── leaderboard.py # Public API (leaderboard, papers, status)
│   └── admin.py       # Admin API (settings, triggers, prompts)
└── .env

/app/frontend/src/
├── App.js             # Routes: /, /paper/:id, /admin, /admin/dashboard
├── pages/
│   ├── LeaderboardPage.jsx
│   ├── PaperPage.jsx
│   ├── AdminLoginPage.jsx
│   └── AdminPage.jsx
└── components/
    └── Navbar.jsx
```

## Key API Endpoints
- `GET /api/leaderboard?period=all|today|week|month` - Public leaderboard (global BT scores, filtered display)
- `GET /api/papers/{id}` - Paper detail + comparison logs
- `GET /api/status` - System status
- `POST /api/admin/login` - Admin auth
- `GET/PUT /api/admin/settings` - Admin settings
- `POST /api/admin/fetch` - Trigger arXiv fetch
- `POST /api/admin/compare` - Trigger comparison round
- `GET/PUT/DELETE /api/admin/prompt` - Evaluation prompt management

## Database Schema
- **papers:** id, arxiv_id, title, authors, abstract, categories, published, link, pdf_link, full_text, added_at, needs_pdf
- **matches:** id, paper1_id, paper2_id, winner_id, reasoning, model_used, completed, failed, created_at
- **settings:** key, admin_password, fetch_interval_hours, max_papers_per_fetch, comparisons_per_round, top_k_focus, exploration_constant, anchor_comparisons, min_matches_per_paper, auto_process, last_fetch_at

## What's Been Implemented
- [Feb 2026] Complete rebuild from PaperSumo tournament app to automated leaderboard
- [Feb 2026] Modular backend (routers, services, core)
- [Feb 2026] Background scheduler with configurable daily fetch
- [Feb 2026] Adaptive matchmaking with UCB, top-K focus, anchor calibration, min matches
- [Feb 2026] Multi-model random selection (GPT 5.2, Claude Opus 4.5, Gemini 3 Pro)
- [Feb 2026] Public leaderboard with date filtering, confidence intervals
- [Feb 2026] Paper detail page with full comparison history
- [Feb 2026] Admin panel with settings (tooltips), manual triggers, prompt editor
- [Feb 2026] Full PDF deep analysis for paper comparisons
- [Feb 2026] Fixed: BT scores now global (consistent across date filter views)
- [Feb 2026] Fixed: Removed W/L column, show full date with year
- [Feb 2026] Fixed: Admin logs are expandable/collapsible
- [Feb 2026] Fixed: Tooltips on all admin settings
- [Feb 2026] Fixed: Custom saved prompt is used as default for comparisons
- [Feb 2026] Added: Min matches per paper setting

## Backlog
- P1: Pause/resume comparison rounds
- P2: Paper abstract preview on hover in leaderboard
- P2: Export leaderboard to CSV/PDF
- P2: RSS feed for leaderboard updates
- P3: Share individual paper ranking via public link
- P3: Compare papers across multiple arXiv categories
- P3: Historical ranking trends (paper rank over time)
