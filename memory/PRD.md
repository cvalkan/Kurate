# PaperSumo - arXiv Paper Ranking Platform

## Original Problem Statement
Build a platform that automatically downloads papers from multiple arXiv categories, runs pairwise tournaments using full paper analysis via LLMs (GPT-5.2, Claude Opus 4.5, Gemini 3 Pro), and outputs dynamically updated ranked leaderboards using Bradley-Terry scores normalized to Elo ratings.

## Tech Stack
- **Frontend:** React, React Router, Axios, Tailwind CSS, Shadcn UI, lucide-react
- **Backend:** FastAPI (modular), Motor (async MongoDB), httpx, PyPDF2
- **Database:** MongoDB (papers, matches, settings collections)
- **LLMs:** OpenAI GPT-5.2, Anthropic Claude Opus 4.5, Google Gemini 3 Pro (via Emergent LLM Key)

## Core Architecture
```
backend/
  core/config.py       - DB, LLM keys, categories, default settings
  core/auth.py         - Settings management
  routers/leaderboard.py - Public leaderboard API (with background cache)
  routers/admin.py     - Admin panel API + experiment endpoints
  services/scheduler.py - Background paper fetching & matchmaking
  services/llm.py      - LLM comparison logic
  services/ranking.py  - Bradley-Terry & Elo computation
  services/arxiv.py    - arXiv paper fetcher
frontend/src/pages/
  LeaderboardPage.jsx  - Public leaderboard with tag filtering
  AdminPage.jsx        - Admin dashboard
  CorrelationPage.jsx  - Model correlation analysis
  PaperPage.jsx        - Individual paper detail
  MethodologyPage.jsx  - Methodology explanation
```

## What's Been Implemented
- [Feb 2026] Multi-category tournaments (cs.RO, cs.DC, econ.GN, physics.comp-ph, q-bio.BM)
- [Feb 2026] Adaptive matchmaking with CI-based convergence
- [Feb 2026] Background cache for instant leaderboard responses
- [Feb 2026] Cross-category tag filtering with AND/OR logic
- [Feb 2026] "Surprisingly Popular" experiment feature
- [Feb 2026] Model correlation & agreement analysis
- [Feb 2026] Positional bias fix (random pair order)
- [Feb 2026] Mobile-responsive leaderboard
- [Feb 2026] **Tag mode: "All Papers" view** — clicking "Filter by tags" shows all 250 papers across all categories, category tabs grey out
- [Feb 2026] **Global/Local stats toggle** — when tags selected, toggle between within-set stats (Local) and full tournament stats (Global)
- [Feb 2026] **Category column** — "Cat" column shows primary category badges in tag mode
- [Feb 2026] **Cross-category tournament exploration** — analysis document at /app/CROSS_CATEGORY_TOURNAMENTS.md

## Key API Endpoints
- `GET /api/leaderboard?category=cs.RO` — Cached category leaderboard
- `GET /api/leaderboard?tags=physics.chem-ph&global_stats=true` — Tag-filtered with global stats
- `GET /api/leaderboard?show_all=true` — All papers from all categories
- `GET /api/tags` — All unique tags with counts
- `GET /api/admin/status/{category}` — Admin status
- `POST /api/admin/prediction/run` — Run experiment
- `GET /api/model-correlation` — Model analysis

## Backlog
- P1: Cross-category tournament participation (see CROSS_CATEGORY_TOURNAMENTS.md)
- P2: Enable reasoning_effort="high" for GPT models
- P2: Explore direct API integration for extended thinking
- P3: Component refactoring (AdminPage.tsx, LeaderboardPage.jsx)
- P3: Historical ranking trends
- P3: Paper abstract preview on hover
