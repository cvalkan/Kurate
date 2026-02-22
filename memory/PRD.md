# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Completed (Feb 22 2026)

### Public/Admin Split
- Public validation page: Tournament results only (ICLR, eLife, MIDL)
- Admin validation page: Full access (all sections, all datasets, experiments)

### UI/Branding
- "PaperSumo by Kurate.org" branding, "Paper Rankings" titles, "preprints" in descriptions
- Methodology: 10 concise steps, consistent "AI Impact Assessment" terminology
- Claude as default AI summary tab, Opus 4.6 throughout
- "Match" column (was "Mtch"), WIP badge on validation
- Matchmaking bias note at top of Model Analysis
- Clear-cut/Contested replaced with hover tooltips

### Backend
- Opus 4.6 as default in TOURNAMENT_MODELS, scheduler, summary generation
- Pricing table updated for Opus 4.6
- Dynamic Anthropic pricing key lookup (handles both 4.5 and 4.6 models)

### Security
- CORS restricted to kurate.org
- Admin password from env var
- Auth on all POST endpoints
- Rate limits on expensive endpoints
- Tournament max duration (1 hour)
- Security headers (HSTS, CSP, X-Frame-Options)

### Performance
- Convergence: 30s → 0.2s (batch endpoint + bisect + cache)
- Stats: 5-10s → 0.2s (server cache + $facet + smart default)
- MongoDB compound index on (dataset_id, content_mode, completed, failed)
- 7 analysis endpoints exclude full_text (96KB/paper) from projections
- 21 datasets pre-warmed on startup

### Data Integrity
- Opus 4.6 winner_id backfill (7,688 matches)
- Extract filter excludes tagged modes
- Agreement analysis uses majority vote
- Cache invalidation on tournament completion

## Pending
- Deploy to production on kurate.org
- Complete remaining Opus 4.6 ICLR replays (coverage 39-94%)
- Gap-stratified human accuracy UI
- Further split validation.py into modules
