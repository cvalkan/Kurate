# PaperSumo - Product Requirements Document

## Overview
PaperSumo is a web platform for ranking academic papers using pairwise comparison models. Papers are compared head-to-head by AI models, and rankings are computed using Bradley-Terry scoring.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Motor (async MongoDB driver)
- **Frontend**: React, react-router-dom, shadcn/ui components
- **Database**: MongoDB
- **Scoring**: Bradley-Terry model, Elo-style scores, Wilson confidence intervals
- **Statistics**: scipy, statsmodels, numpy

## Architecture

### Key Files
- `backend/server.py` - FastAPI app entrypoint, rate-limiting middleware, security headers
- `backend/core/auth.py` - Admin authentication (MongoDB-backed sessions)
- `backend/routers/admin.py` - Admin panel endpoints including extraction stats
- `backend/routers/leaderboard.py` - Public leaderboard API
- `backend/routers/validation.py` - Human vs AI validation experiment (siloed, multi-dataset, multi-model)
- `backend/db_utils/leaderboard_cache.py` - Background caching thread
- `backend/services/llm.py` - PDF extraction algorithm, LLM comparison logic (with model_override support)
- `backend/services/ranking.py` - Bradley-Terry, Elo, Wilson CI computations
- `frontend/src/pages/AdminPage.jsx` - Admin panel tabs
- `frontend/src/pages/ValidationPage.jsx` - Human vs AI validation (tabbed, sidebar nav, multi-model)
- `frontend/src/components/AdminExtraction.jsx` - Extraction statistics page

### Key Patterns
1. **Background Caching**: All expensive queries are pre-computed and served from memory
2. **Rate Limiting**: Custom middleware in `server.py`
3. **Admin Sessions**: Stored in MongoDB `admin_sessions` collection
4. **Production Frontend Build**: `yarn build` + `serve` — changes require rebuild + restart

## Implemented Features

### Validation Experiment — Multi-Dataset (Implemented Feb 2026)
- Completely siloed from main leaderboard
- **Three datasets**:
  1. **ICLR LLMs**: 73 papers, 811 matches, ρ≈0.65
  2. **ICLR Protein Science**: 46 papers, 1499 matches (3-model), ρ≈0.60
  3. **PeerRead ACL 2017**: 80 NLP/CL papers, 1000 matches, ρ≈0.41
- Sidebar navigation per dataset with per-dataset stats
- **Standard stats**: Pairwise BT, IRT Score, Agreement Analysis
- **Multi-model analysis** (Protein Science): All 499 pairs evaluated by GPT-5.2, Claude Opus 4.5, Gemini 3 Pro
  - Inter-model pairwise agreement: 80–82%
  - Inter-model rank correlation: ρ=0.86–0.90
  - Majority-vote vs expert majority: 74.7%
  - Majority-vote BT ranking vs human BT: ρ=0.617

### PDF Extraction Algorithm (Implemented Feb 2026)
- Regex-based header detection, field-adaptive markers
- Position-aware extraction, smart truncation

### Performance Optimization (Completed Dec 2025, Updated Feb 2026)
- Backend caching, pre-warming, non-blocking "Warming up" indicators

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
- `validation_papers`: Papers with expert ratings (dataset_id partitioned)
- `validation_matches`: AI tournament matches with model_used info
- `validation_datasets`: Dataset metadata

## Key API Endpoints

### Validation Experiment
- `GET /api/validation/datasets` - List all datasets
- `GET /api/validation/status?dataset_id=X` - Dataset status
- `GET /api/validation/pairwise-results?dataset_id=X` - Pairwise BT correlation
- `GET /api/validation/irt-results?dataset_id=X` - IRT score correlation
- `GET /api/validation/agreement-analysis?dataset_id=X` - Agreement rates
- `GET /api/validation/multimodel-results?dataset_id=X` - Multi-model analysis
- `POST /api/validation/import-iclr` - Import ICLR dataset (admin)
- `POST /api/validation/import-peerread` - Import PeerRead dataset (admin)
- `POST /api/validation/run-tournament` - Run AI tournament (admin, parallel up to 50)
- `POST /api/validation/run-multimodel` - Run missing models for existing pairs (admin)
- `POST /api/validation/reset` - Clear dataset (admin)

## Credentials
- **Admin Password**: `papersumo2025`

## Deployment Notes
- Frontend is PRODUCTION BUILD — changes require `yarn build` + `supervisorctl restart frontend`
- Admin sessions stored in MongoDB (persistent)
- Validation data completely separate from main leaderboard

## Backlog
- P1: Add HTTP security headers for production nginx
- P1: Regenerate old AI impact summaries to add model badge (needs user confirmation)
- P2: Experiment with Gemini 3 Flash as alternative LLM model
- P2: Run multi-model tournament on other datasets
- P2: Full security scan review
- P3: Abstract-only vs full-text comparison experiment
- P3: Adaptive Swiss-tournament-style pairing
