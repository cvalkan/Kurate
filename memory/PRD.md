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
  core/auth.py         - Settings management (with 5s TTL cache) + admin auth
  routers/leaderboard.py - Public leaderboard API (with background cache, pre-computed tags/categories)
  routers/admin.py     - Admin panel API + experiment + timeseries endpoints
  routers/auth.py      - User auth (email/password + Google OAuth)
  routers/suggestions.py - User suggestions API
  services/scheduler.py - Background paper fetching & matchmaking (tournament registry-based)
  services/llm.py      - LLM comparison logic
  services/ranking.py  - Bradley-Terry & Elo computation
  services/arxiv.py    - arXiv paper fetcher
frontend/src/
  pages/
    LeaderboardPage.jsx  - Public leaderboard with tag filtering (optimistic switching)
    AdminPage.jsx        - Admin dashboard (7 tabs)
    CorrelationPage.jsx  - Model correlation analysis
    PaperPage.jsx        - Individual paper detail
    MethodologyPage.jsx  - Methodology explanation
    AdminLoginPage.jsx   - Admin login
    AuthCallback.jsx     - Google OAuth callback
    VerifyEmailPage.jsx  - Email verification
  components/
    AdminStatistics.jsx  - Charts & analytics (Recharts, self-contained data fetching)
    AdminOverview.jsx    - Controls: fetch, compare, scheduler status + Tournament Registry
    AdminExperiment.jsx  - Experiment tab
    AdminCategories.jsx  - Category management (add/remove)
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
- [Feb 2026] P1: Tournament registry, min viable tournament threshold, prompt version tracking
- [Feb 2026] Admin Statistics tab with Recharts time-series charts
- [Feb 2026] Pause/resume consistency: scheduler respects tournament-level pause, smart pause/resume routing
- [Feb 2026] Cost-by-model alignment fix
- [Feb 2026] Controls + Tournaments merge
- [Feb 2026] Production robustness for timeseries handling
- [Feb 2026] Top-K Cross-Match (Goal 3)
- [Feb 2026] Round-Robin Model Selection
- [Feb 2026] Methodology page updated, Public Prompts page
- [Feb 2026] Experiment isolation audit (mode field filtering)
- [Feb 2026] Dynamic category management (add/remove)
- [Feb 2026] Leaderboard category overflow (hot picks + More dropdown)
- [Feb 2026] Backend DB query optimization (compound indexes, moved filters to DB level)
- [Feb 2026] **Settings TTL cache** — `get_settings()` cached with 5s TTL, invalidated on admin updates. Eliminates redundant DB hits on every request.
- [Feb 2026] **Pre-computed tags & categories** — `/api/tags` and `/api/categories` now served from background cache (20s TTL), no per-request computation.
- [Feb 2026] **Optimistic frontend category switching** — No loading skeleton flash when switching categories. Old data stays visible until new data arrives.
- [Feb 2026] **New category preset to paused** — Admin-added categories start as "paused". No paper fetching or tournament activity until explicitly resumed.
- [Feb 2026] **Resume triggers immediate fetch** — Resuming a paused category with <10 papers triggers an immediate paper fetch cycle + scheduler wake-up.
- [Feb 2026] **Scheduler respects paused categories for fetching** — Paper fetching only runs for active (non-paused) tournament categories.

## Tournament Goal System (3 Goals)
1. **Goal 1 (Min Matches)**: Every paper must have >= `min_matches_per_paper` comparisons
2. **Goal 2 (CI Convergence)**: Top-K papers must have Wilson CI margin <= `ci_target`%
3. **Goal 3 (Top-K Cross-Match)**: Every pair of top-K papers must have played against each other at least once

## Key API Endpoints
- `GET /api/leaderboard?category=cs.RO` — Cached category leaderboard
- `GET /api/leaderboard?tags=physics.chem-ph&global_stats=true` — Tag-filtered with global stats
- `GET /api/categories` — Dynamic active categories (served from background cache)
- `GET /api/tags` — All unique tags with counts (served from background cache)
- `GET /api/prompts` — Public read-only view of evaluation and summary prompts
- `GET /api/admin/arxiv-categories` — Full arXiv taxonomy (155 categories) for searchable picker
- `POST /api/admin/categories/add` — Add a tournament category (preset to paused)
- `POST /api/admin/categories/remove` — Remove a tournament category (pauses, keeps data)
- `GET /api/admin/category-estimate/{cat_id}` — Estimate weekly papers, matches, costs
- `GET /api/admin/timeseries` — Daily time-series + per-model cost breakdown
- `GET /api/admin/progress?category=...` — Progress with 3 goals + pause status
- `GET /api/admin/tournaments` — Tournament registry
- `POST /api/admin/tournaments/{id}/status` — Pause/resume tournament (resume triggers fetch for new categories)

## Pause/Resume Architecture
- **Global pause** (`settings.paused`): Stops ALL tournament activity
- **Per-tournament pause** (`tournaments.status`): Stops specific category
- **New category workflow**: Add → paused → Resume → immediate fetch + tournament start
- **Scheduler**: Respects both mechanisms. Only fetches papers for active categories.

## Backlog
- P2: Refactor matchmaking with BT uncertainty-based pairing + regularization priors
- P3: Formalize Judge & Cohorts (extend match schema with judge metadata)
- P3: Global Tournaments & UI Clarity (explicit cross-category tournaments)
- P3: LeaderboardPage.jsx decomposition (500+ lines)
- P3: Historical ranking trends
- P3: Paper abstract preview on hover
