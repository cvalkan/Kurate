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
    AuthModal.jsx        - Login/register modal
    SuggestionModal.jsx  - Suggestion modal
    ModelBadge.jsx       - LLM model badge
    CorrelationSection.jsx - Correlation cards
    Navbar.jsx           - Navigation + auth
  contexts/
    AuthContext.jsx      - Auth state management
```

## Admin Panel Tabs (7)
1. **Statistics** (default) — Summary cards, cost-by-model breakdown, 4 time-series charts (Papers/Matches/Tokens/Cost), cumulative/daily + system/category toggles, per-category totals table
2. **Controls** — Per-category stats, ranking progress with smart pause/resume, fetch/compare buttons, scheduler status, Tournament Registry with per-tournament pause/resume
3. **Settings** — System parameters (fetch interval, parallel agents, CI target, etc.)
4. **Prompt** — Comparison/summary/prediction prompt editors
5. **Experiment** — Surprisingly Popular prediction tournament
6. **Suggestions** — User feedback review
7. **Users** — User management (deactivate/reactivate)

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
- [Feb 2026] **Cost-by-model alignment fix** — model stats now from system-wide timeseries endpoint (not per-category), percentages sum to 100%
- [Feb 2026] **Controls + Tournaments merge** — Tournament Registry embedded in Controls tab, Tournaments tab removed
- [Feb 2026] **Production robustness** — timeseries handles missing `tokens`, `created_at`, `added_at`, `primary_category`, unknown models; falls back to `published` date for papers without `added_at`

## Key API Endpoints
- `GET /api/leaderboard?category=cs.RO` — Cached category leaderboard
- `GET /api/leaderboard?tags=physics.chem-ph&global_stats=true` — Tag-filtered with global stats
- `GET /api/admin/timeseries` — Daily time-series + per-model cost breakdown (system-wide)
- `GET /api/admin/stats?category=...` — Per-category token usage by model
- `GET /api/admin/progress?category=...` — Progress with tournament_paused/global_paused
- `GET /api/admin/tournaments` — Tournament registry
- `POST /api/admin/tournaments/{id}/status` — Pause/resume tournament

## Pause/Resume Architecture
- **Global pause** (`settings.paused`): Stops ALL tournament activity. Toggled via Settings or toggle-pause endpoint.
- **Per-tournament pause** (`tournaments.status`): Stops specific category. Toggled via tournament status endpoint.
- **Smart routing**: Controls tab Pause/Resume button targets tournament-level when tournament is paused and global isn't, otherwise targets global.
- **Scheduler**: Respects both mechanisms. No fallback override when all tournaments are paused.

## Backlog
- P2: Refactor matchmaking with BT uncertainty-based pairing + regularization priors
- P3: Formalize Judge & Cohorts (extend match schema with judge metadata)
- P3: Global Tournaments & UI Clarity (explicit cross-category tournaments)
- P3: LeaderboardPage.jsx decomposition (500+ lines)
- P3: Historical ranking trends
- P3: Paper abstract preview on hover
