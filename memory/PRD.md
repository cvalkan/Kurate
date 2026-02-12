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
- `backend/server.py` - FastAPI app entrypoint, rate-limiting middleware, security headers
- `backend/core/auth.py` - Admin authentication (MongoDB-backed sessions)
- `backend/routers/admin.py` - Admin panel endpoints including extraction stats
- `backend/routers/leaderboard.py` - Public leaderboard API
- `backend/db_utils/leaderboard_cache.py` - Background caching thread
- `backend/services/llm.py` - PDF extraction algorithm, LLM comparison logic
- `frontend/src/pages/AdminPage.jsx` - Admin panel tabs
- `frontend/src/components/AdminExtraction.jsx` - Extraction statistics page

### Key Patterns
1. **Background Caching**: All expensive queries are pre-computed by `leaderboard_cache.py` and served from memory
2. **Single Source of Truth**: Match counts come from scheduler state, not multiple DB queries
3. **Rate Limiting**: Custom middleware in `server.py` with stricter limits on sensitive endpoints
4. **Admin Sessions**: Stored in MongoDB `admin_sessions` collection (persistent across restarts/pods)
5. **Extraction Stats Cache**: 10-minute TTL cache for extraction statistics
6. **Production Frontend Build**: Frontend runs as a production build (`yarn build` + `serve`), NOT dev mode. Changes require `yarn build` + `supervisorctl restart frontend`.

## Implemented Features

### PDF Extraction Algorithm (Implemented Feb 2026)
- Regex-based header detection (numbered sections, all-caps headers)
- Field-adaptive markers (Economics, Physics, Biology, CS specific terms)
- Position-aware extraction (Introduction in first 30%, Conclusion in last 40%)
- Admin Extraction page with statistics
- Sample Papers table showing 50 papers with per-section character counts

### Performance Optimization (Completed Dec 2025, Updated Feb 2026)
- Backend caching for "All Papers" and tag-filtered leaderboards
- Server-side search for large datasets
- Optimized admin polling endpoints (read from cache, no DB queries on hot path)
- Removed 500-paper limit on tag-filtered views
- Pre-fetched settings for batch operations (Feb 2026) - Fixed performance regression in admin panel
- Pre-warming extraction stats cache on startup (Feb 2026)
- Leaderboard cache warm on startup with 60s TTL (increased from 20s)
- Admin cache TTL increased to 30s (from 5s)
- Extraction stats cache TTL increased to 10 minutes (from 5 min)
- Non-blocking "Warming up" indicators for cold cache scenarios
- Background computation for extraction stats (never blocks requests)

### AI Impact Reports (Updated Feb 2026)
- Impact summaries generated for ALL papers when tournament goals are met (not individual paper convergence)
- Round-robin LLM selection: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro
- Manual trigger endpoint: POST /api/admin/generate-summaries (requires category, checks tournament status)
- Summary stats endpoint: GET /api/admin/summary-stats (includes tournament_status)
- LLM model badge displayed on AI Impact Assessment section (shows which model generated the summary)
- Model info stored in `summary_model_used` field on papers collection
- Increased batch size from 100 to 500 papers per cycle

### UI/UX Enhancements (Completed Dec 2025)
- Leaderboard state preservation via URL parameters
- Natural infinite scroll (no fixed container/scrollbar)
- Sortable columns (Title, Score, Win%, CI, Matches, Published)
- Frontend re-ranking on Global/Local toggle
- Detailed tooltips on column headers

### Security Hardening (Completed Feb 2026)
- Rate limiting middleware on all endpoints
- Session token-based admin auth (MongoDB-backed)
- Parameter capping (limit, search length)
- Security headers (HSTS, CSP, X-Frame-Options, etc.) for API endpoints
- Security headers for frontend static files (needs nginx config on production)

### Bug Fixes (Completed Feb 2026)
- Fixed "Back to Leaderboard" link state preservation
- Fixed Global Stats calculation (Bradley-Terry model)
- Fixed admin login not working on deployed version (MongoDB sessions)
- Fixed missing Sample Papers table on Admin Extraction page (sample_papers dropped during performance refactoring)

## Database Schema

### Collections
- `papers`: `{ arxiv_id, title, primary_category, categories, published_date, full_text, summary, summary_model_used, ... }`
- `matches`: `{ paper1_id, paper2_id, winner_id, primary_category, shared_categories, ... }`
- `tournaments`: `{ category, is_active, last_run, status, ... }`
- `admin_settings`: `{ admin_password, openai_api_key, ... }`
- `admin_sessions`: `{ key: "sessions", tokens: [...] }` - Persistent admin session tokens

## Key API Endpoints
- `GET /api/leaderboard` - Main leaderboard (cached)
- `GET /api/tags` - Filterable tags
- `POST /api/admin/login` - Admin login → returns session token
- `GET /api/admin/status`, `/progress`, `/stats` - Admin polling (cached)
- `GET /api/admin/extraction-stats` - PDF extraction statistics (10-min cache, includes sample_papers)
- `POST /api/admin/generate-summaries` - Trigger AI impact summary generation
- `GET /api/admin/summary-stats` - AI impact summary coverage statistics

## Credentials
- **Admin Password**: `papersumo2025`

## Deployment Notes
- Admin sessions stored in MongoDB (persistent across restarts/pods)
- Security headers work on API endpoints, need nginx config for frontend static files on production
- Extraction stats endpoint has 10-minute cache for performance
- Frontend is a PRODUCTION BUILD - changes require `yarn build` + `supervisorctl restart frontend`

## Known Issues
- Security headers for frontend static files require nginx configuration on production (contact Emergent support)
- Conclusion extraction rate (~81%) is lower than other sections

## Backlog
- P1: Implement security headers for production frontend via nginx configuration
- P1: Regenerate old AI impact summaries to add model badge (needs user confirmation)
- P1: Experiment with Gemini 3 Flash as alternative LLM model
- P2: Consider using full PDFs for top-K high-value paper comparisons
- P2: Improve conclusion detection algorithm
- P2: Review full security scan report for other vulnerabilities
