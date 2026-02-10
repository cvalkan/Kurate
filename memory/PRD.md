# PaperSumo - Product Requirements Document

## Overview
PaperSumo is a web platform for ranking academic papers using pairwise comparison models. Papers are compared head-to-head by AI models, and rankings are computed using Bradley-Terry scoring.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Motor (async MongoDB driver)
- **Frontend**: React, react-router-dom, shadcn/ui components
- **Database**: MongoDB
- **Scoring**: Bradley-Terry model → Elo-style scores, Wilson confidence intervals

## Architecture

### Key Files
- `backend/server.py` - FastAPI app entrypoint, rate-limiting middleware
- `backend/core/auth.py` - Admin authentication (MongoDB-backed sessions)
- `backend/routers/admin.py` - Admin panel endpoints
- `backend/routers/leaderboard.py` - Public leaderboard API
- `backend/db_utils/leaderboard_cache.py` - Background caching thread
- `frontend/src/pages/LeaderboardPage.jsx` - Main leaderboard orchestrator
- `frontend/src/components/leaderboard/` - Decomposed leaderboard components

### Key Patterns
1. **Background Caching**: All expensive queries are pre-computed by `leaderboard_cache.py` and served from memory
2. **Single Source of Truth**: Match counts come from scheduler state, not multiple DB queries
3. **Rate Limiting**: Custom middleware in `main.py` with stricter limits on sensitive endpoints
4. **Admin Sessions**: Stored in MongoDB `admin_sessions` collection (persistent across restarts/pods)

## Implemented Features

### Performance Optimization (Completed Dec 2025)
- ✅ Backend caching for "All Papers" and tag-filtered leaderboards
- ✅ Server-side search for large datasets
- ✅ Optimized admin polling endpoints (read from cache, no DB queries on hot path)
- ✅ Removed 500-paper limit on tag-filtered views

### UI/UX Enhancements (Completed Dec 2025)
- ✅ Leaderboard state preservation via URL parameters
- ✅ Natural infinite scroll (no fixed container/scrollbar)
- ✅ Sortable columns (Title, Score, Win%, CI, Matches, Published)
- ✅ Frontend re-ranking on Global/Local toggle
- ✅ Detailed tooltips on column headers

### Security Hardening (Completed Dec 2025)
- ✅ Rate limiting middleware on all endpoints
- ✅ Session token-based admin auth (MongoDB-backed)
- ✅ Parameter capping (limit, search length)

### Code Quality (Completed Dec 2025)
- ✅ Decomposed LeaderboardPage.jsx into 6 smaller components
- ✅ Consolidated duplicated wilson_margin calculation
- ✅ Removed dead code and unused imports

### Bug Fixes (Completed Feb 2026)
- ✅ Fixed "Back to Leaderboard" link state preservation
- ✅ Fixed Global Stats calculation (Bradley-Terry model)
- ✅ **Fixed admin login not working on deployed version** - Changed from in-memory to MongoDB session storage

## Database Schema

### Collections
- `papers`: `{ arxiv_id, title, primary_category, categories, published_date, ... }`
- `matches`: `{ paper1_id, paper2_id, winner_id, primary_category, shared_categories, ... }`
- `tournaments`: `{ category, is_active, last_run, status, ... }`
- `admin_settings`: `{ admin_password, openai_api_key, ... }`
- `admin_sessions`: `{ key: "sessions", tokens: [...] }` - Persistent admin session tokens

## Key API Endpoints
- `GET /api/leaderboard` - Main leaderboard (cached)
- `GET /api/tags` - Filterable tags
- `POST /api/admin/login` - Admin login → returns session token
- `GET /api/admin/status`, `/progress`, `/stats` - Admin polling (cached)

## Credentials
- **Admin Password**: `papersumo2025`

## Deployment Notes
- Admin sessions are stored in MongoDB, so they persist across:
  - Backend restarts
  - Multiple pod instances in Kubernetes
  - Deployments

## Backlog
No outstanding tasks.
