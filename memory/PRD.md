# PaperSumo - Product Requirements Document

## Overview
PaperSumo is a web platform for ranking academic papers using pairwise comparison models. Papers are compared head-to-head by AI models, and rankings are computed using Bradley-Terry scoring.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Motor (async MongoDB driver)
- **Frontend**: React, react-router-dom, shadcn/ui components
- **Database**: MongoDB
- **Scoring**: Bradley-Terry model, Elo-style scores, Wilson confidence intervals

## Architecture

### Key Files
- `backend/server.py` - FastAPI app entrypoint, rate-limiting middleware, security headers
- `backend/core/auth.py` - Admin authentication (MongoDB-backed sessions)
- `backend/routers/admin.py` - Admin panel endpoints including extraction stats
- `backend/routers/leaderboard.py` - Public leaderboard API
- `backend/routers/validation.py` - Human vs AI validation experiment (siloed)
- `backend/db_utils/leaderboard_cache.py` - Background caching thread
- `backend/services/llm.py` - PDF extraction algorithm, LLM comparison logic
- `backend/services/ranking.py` - Bradley-Terry, Elo, Wilson CI computations
- `frontend/src/pages/AdminPage.jsx` - Admin panel tabs
- `frontend/src/pages/ValidationPage.jsx` - Human vs AI validation experiment page
- `frontend/src/components/AdminExtraction.jsx` - Extraction statistics page

### Key Patterns
1. **Background Caching**: All expensive queries are pre-computed and served from memory
2. **Rate Limiting**: Custom middleware in `server.py`
3. **Admin Sessions**: Stored in MongoDB `admin_sessions` collection
4. **Production Frontend Build**: `yarn build` + `serve` — changes require rebuild + restart

## Implemented Features

### Human vs AI Validation Experiment (Implemented Feb 2026)
- Completely siloed from main leaderboard (`validation_papers`, `validation_matches` collections)
- Imports 47 biomedical papers with ≥5 H1 Connect expert ratings (Good=1, Very Good=2, Exceptional=3)
- Runs independent AI pairwise tournament using round-robin GPT-5.2, Claude Opus, Gemini 3 Pro
- Computes rank correlation: Spearman ρ, Kendall τ, Pearson r
- Public `/validation` page with correlation badges, interpretation, and side-by-side ranking table
- Admin controls for import, tournament execution, and reset
- Data source: `papertrend-viz.preview.emergentagent.com/api/papers`
- Current results: ρ = -0.118 (not significant, p = 0.43) with 170 matches on 47 papers

### PDF Extraction Algorithm (Implemented Feb 2026)
- Regex-based header detection, field-adaptive markers
- Position-aware extraction, smart truncation
- Admin Extraction page with statistics + Sample Papers table

### Performance Optimization (Completed Dec 2025, Updated Feb 2026)
- Backend caching, pre-warming, non-blocking "Warming up" indicators
- Extraction stats cache TTL: 10 minutes

### AI Impact Reports (Updated Feb 2026)
- Impact summaries for papers in completed tournaments
- Round-robin LLM selection, model badge display

### Security Hardening (Completed Feb 2026)
- Rate limiting, session-based admin auth, security headers (API-side)

## Database Schema

### Main Collections
- `papers`: ArXiv papers with full text, categories, scores
- `matches`: Pairwise AI comparisons for main leaderboard
- `tournaments`: Category tournament state
- `admin_sessions`: Admin auth tokens

### Validation Collections (Siloed)
- `validation_papers`: H1 Connect papers with expert ratings
- `validation_matches`: AI tournament matches for validation experiment

## Key API Endpoints

### Main Leaderboard
- `GET /api/leaderboard` - Cached leaderboard
- `GET /api/tags` - Filterable tags
- `POST /api/admin/login` - Admin login
- `GET /api/admin/extraction-stats` - PDF extraction statistics

### Validation Experiment
- `GET /api/validation/status` - Import/tournament status (public)
- `GET /api/validation/results` - Correlation analysis + comparison table (public)
- `POST /api/validation/import` - Import H1 papers (admin)
- `POST /api/validation/run-tournament` - Run AI tournament (admin)
- `POST /api/validation/reset` - Clear all validation data (admin)

## Credentials
- **Admin Password**: `papersumo2025`

## Deployment Notes
- Frontend is PRODUCTION BUILD — changes require `yarn build` + `supervisorctl restart frontend`
- Admin sessions stored in MongoDB (persistent)
- Validation data completely separate from main leaderboard

## Backlog
- P1: Regenerate old AI impact summaries to add model badge (needs user confirmation)
- P1: Implement security headers for production nginx
- P1: Experiment with Gemini 3 Flash as alternative LLM model
- P2: Run more validation tournament matches for better statistical power
- P2: Improve conclusion detection algorithm
- P2: Full security scan review
