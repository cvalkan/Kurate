# PaperSumo - Product Requirements Document

## Overview
PaperSumo is a web platform for ranking academic papers using pairwise comparison models. Papers are compared head-to-head by AI models, and rankings are computed using Bradley-Terry scoring.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Motor (async MongoDB driver)
- **Frontend**: React, react-router-dom, shadcn/ui components
- **Database**: MongoDB
- **Scoring**: Bradley-Terry model, Elo-style scores, Wilson confidence intervals
- **Statistics**: scipy, statsmodels, numpy

## Implemented Features

### Validation Experiment — Multi-Dataset, Multi-Model (Feb 2026)
- Completely siloed from main leaderboard
- **Four datasets**:
  1. **ICLR LLMs**: 73 papers, 1805 matches (3-model), ρ≈0.65
  2. **ICLR Protein Science**: 46 papers, 1499 matches (3-model), ρ≈0.60
  3. **PeerRead ACL 2017**: 80 NLP papers, 1999 matches (3-model), ρ≈0.41
  4. **F1000 Biomedical**: 157 papers, 500 matches, ρ≈0.37 (pairwise BT)
- Sidebar navigation per dataset, per-dataset tabs (Ranking Correlation + Multi-Model Analysis)
- **Multi-model analysis**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro — inter-model agreement 80-85%, rank correlation ρ=0.74-0.90
- **Auto-seed on startup**: Bundled JSON seed data auto-loads into empty production DB
- **Pre-warm on startup**: Validation aggregation queries warmed on boot

### Data Sources
- ICLR OpenReview (berenslab/iclr-dataset parquet)
- PeerRead (AllenAI GitHub, ACL 2017 with parsed PDFs)
- F1000Research (extapi XML, structured peer review with approve/reservations/reject)

## Key API Endpoints

### Validation
- `GET /api/validation/datasets` - List all datasets
- `GET /api/validation/status?dataset_id=X`
- `GET /api/validation/pairwise-results?dataset_id=X`
- `GET /api/validation/irt-results?dataset_id=X`
- `GET /api/validation/agreement-analysis?dataset_id=X`
- `GET /api/validation/multimodel-results?dataset_id=X`
- `POST /api/validation/import-iclr` (admin)
- `POST /api/validation/import-peerread` (admin)
- `POST /api/validation/import-f1000` (admin)
- `POST /api/validation/run-tournament` (admin, parallel up to 50)
- `POST /api/validation/run-multimodel` (admin, max_pairs param)
- `POST /api/validation/seed` (admin, loads bundled data)

## Credentials
- **Admin Password**: `papersumo2025`

## Deployment Notes
- Frontend is PRODUCTION BUILD — changes require `yarn build` + `supervisorctl restart frontend`
- `.env` files must be committed (previously blocked by `.gitignore` — fixed)
- Validation seed data bundled in `backend/data/validation_seed/` — auto-loads on startup if DB empty

## Backlog
- P1: Add HTTP security headers for production nginx
- P1: Regenerate old AI impact summaries to add model badge
- P2: Run multi-model tournament on F1000 dataset
- P2: Experiment with Gemini 3 Flash as alternative LLM
- P2: Run more matches for F1000 (currently only 500 for 157 papers)
- P3: Explore Gates Open Research as additional dataset
- P3: Explore Crossref/Copernicus (geoscience) for non-biomedical data
