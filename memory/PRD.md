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

### Background Tasks (Feb 22 2026)
- Converted `/api/admin/fetch` endpoint from synchronous to background task
- Returns immediate `202 Accepted` response, eliminating `520 Proxy Timeout`
- Added `/api/admin/fetch-status/{category}` polling endpoint
- Frontend polls every 5s and shows toast on completion/failure
- Duplicate-request guard prevents concurrent fetches per category

### Admin Performance Optimization (Feb 23 2026)
- Pre-computed progress data (Wilson CI, cross-matches, goals) in leaderboard background loop — `/progress` no longer queries DB
- Pre-computed summary stats in leaderboard background loop — `/stats` no longer scans all papers from DB
- Increased admin cache TTL from 10s to 30s (aligned with background refresh cadence)
- Frontend polling aligned: 15s active / 30s idle (was 5s/15s, causing redundant DB hits)
- Result: category switching drops from ~2s to ~90-120ms; cached hits ~85ms

### Fundamental Performance Architecture Fix (Feb 23 2026)
**Root cause**: `compute_leaderboard()` (Bradley-Terry + Wilson CI) is CPU-bound and was running on the async event loop, blocking ALL HTTP requests for 1-10+ seconds.
- **Thread pool executor** for ALL 25+ `compute_leaderboard` calls via `compute_leaderboard_async()`
- **Eliminated redundant "all papers" leaderboard** — derived from per-category results
- **Removed DB query from validation `cache_get()`** — pure TTL + explicit invalidation
- **Pre-computed scipy z-value** — avoids repeated `norm.ppf(0.975)` in hot path
- Benchmarks: 0.8s cache refresh (non-blocking), 90ms p99 for 20 concurrent requests, <5ms category switch

### Paper Deduplication (Feb 23 2026)
- Added title+first-author dedup check during paper fetching (prevents future duplicates)
- Added `/api/admin/dedup-papers` endpoint to merge existing duplicates: keeps paper with most matches, reassigns all matches, cleans up self-matches
- Merged 11 duplicates on preview, 0 remaining across all categories
- Production needs dedup run after deployment (POST /api/admin/dedup-papers)

### LLM Budget Error Resilience (Feb 23 2026)
- Added budget/credit error detection in LLM comparison and impact assessment functions
- When budget error detected: waits 15s for auto-topup before retrying (was 1-4s generic backoff)
- Prevents burst of ~60 failed matches when credits hit zero with 20 parallel agents

## Pending
- Deploy to production on kurate.org
- **Run dedup on production after deploy** (POST /api/admin/dedup-papers)
- Complete remaining Opus 4.6 ICLR replays (coverage 39-94%)
- Gap-stratified human accuracy UI
- Further split validation.py into modules
- Add remaining HTTP security headers (CSP refinement)
- Decouple fetch from compare in scheduler (postponed)
