# PaperSumo - arXiv Paper Ranking Platform

## Original Problem Statement
Build a platform that automatically downloads papers from multiple arXiv categories, runs pairwise tournaments using full paper analysis via LLMs (GPT-5.2, Claude Opus 4.5, Gemini 3 Pro), and outputs dynamically updated ranked leaderboards using Bradley-Terry scores normalized to Elo ratings.

## Tech Stack
- **Frontend:** React (CRA), React Router, Axios, Tailwind CSS, Shadcn UI, lucide-react, Recharts
- **Backend:** FastAPI (modular), Motor (async MongoDB), httpx, PyPDF2
- **Database:** MongoDB (papers, matches, settings, tournaments, users, sessions, suggestions)
- **LLMs:** OpenAI GPT-5.2, Anthropic Claude Opus 4.5, Google Gemini 3 Pro (via Emergent LLM Key)

## Core Architecture
```
backend/
  core/config.py       - DB, LLM keys, categories, default settings
  core/auth.py         - Settings management + admin auth
  routers/leaderboard.py - Public leaderboard API (with background cache)
  routers/admin.py     - Admin panel API + experiment + timeseries endpoints
  routers/auth.py      - User auth (email/password + Google OAuth)
  routers/suggestions.py - User suggestions API
  services/scheduler.py - Background paper fetching & matchmaking (tournament registry-based)
  services/llm.py      - LLM comparison logic
  services/ranking.py  - Bradley-Terry & Elo computation
  services/arxiv.py    - arXiv paper fetcher
frontend/src/
  pages/
    LeaderboardPage.jsx  - Public leaderboard with tag filtering
    AdminPage.jsx        - Admin dashboard (8 tabs)
    CorrelationPage.jsx  - Model correlation analysis
    PaperPage.jsx        - Individual paper detail
    MethodologyPage.jsx  - Methodology explanation
    AdminLoginPage.jsx   - Admin login
    AuthCallback.jsx     - Google OAuth callback
    VerifyEmailPage.jsx  - Email verification
  components/
    AdminStatistics.jsx  - Charts & analytics (Recharts)
    AdminOverview.jsx    - Controls: fetch, compare, scheduler status
    AdminExperiment.jsx  - Experiment tab
    AuthModal.jsx        - Login/register modal
    SuggestionModal.jsx  - Suggestion modal
    ModelBadge.jsx       - LLM model badge
    CorrelationSection.jsx - Correlation cards
    Navbar.jsx           - Navigation + auth
  contexts/
    AuthContext.jsx      - Auth state management
```

## What's Been Implemented
- [Feb 2026] Multi-category tournaments (cs.RO, cs.DC, econ.GN, physics.comp-ph, q-bio.BM)
- [Feb 2026] Adaptive matchmaking with CI-based convergence
- [Feb 2026] Background cache for instant leaderboard responses
- [Feb 2026] Cross-category tag filtering with AND/OR logic
- [Feb 2026] "Surprisingly Popular" experiment feature
- [Feb 2026] Model correlation & agreement analysis
- [Feb 2026] Positional bias fix (random pair order)
- [Feb 2026] Mobile-responsive leaderboard with hamburger menu
- [Feb 2026] Tag mode: "All Papers" view, Global/Local stats toggle, Category column
- [Feb 2026] Infinite scroll via IntersectionObserver
- [Feb 2026] Piggyback cross-category (shared_categories on matches)
- [Feb 2026] User Authentication (Google OAuth + email/password with verification via Resend)
- [Feb 2026] Gated features for non-logged-in users
- [Feb 2026] Suggest Field for logged-in user feedback
- [Feb 2026] P0: Indexed primary_category on matches for O(1) category queries
- [Feb 2026] P1: Tournament registry (tournaments collection), min viable tournament threshold, prompt version tracking
- [Feb 2026] **Admin Statistics tab** — replaced Overview with detailed Statistics page showing:
  - Summary cards (papers, matches, tokens, cost)
  - Cost by Model breakdown with progress bars
  - 4 time-series charts (Papers, Matches, Tokens, Cost) with Cumulative/Daily toggle
  - System-wide vs By Category stacked view toggle
  - Per-Category Totals table
  - New `/api/admin/timeseries` endpoint
- [Feb 2026] **Pause/resume consistency fix** — scheduler now respects tournament-level pause (no fallback override), progress endpoint reports both `global_paused` and `tournament_paused`, UI distinguishes "TOURNAMENT PAUSED" vs global pause

## Key API Endpoints
- `GET /api/leaderboard?category=cs.RO` — Cached category leaderboard
- `GET /api/leaderboard?tags=physics.chem-ph&global_stats=true` — Tag-filtered with global stats
- `GET /api/leaderboard?show_all=true` — All papers from all categories
- `GET /api/tags` — All unique tags with counts
- `GET /api/admin/timeseries` — Daily time-series for papers, matches, tokens, cost (by category)
- `GET /api/admin/stats` — Token usage and cost by model
- `GET /api/admin/progress?category=cs.RO` — Progress with tournament_paused/global_paused
- `GET /api/admin/tournaments` — Tournament registry
- `POST /api/admin/tournaments/{id}/status` — Pause/resume tournament
- `GET /api/model-correlation` — Model analysis

## Backlog
- P2: Refactor matchmaking with BT uncertainty-based pairing + regularization priors
- P3: Formalize Judge & Cohorts (extend match schema with judge metadata)
- P3: Global Tournaments & UI Clarity (explicit cross-category tournaments)
- P3: LeaderboardPage.jsx decomposition (500+ lines)
- P3: Historical ranking trends
- P3: Paper abstract preview on hover
