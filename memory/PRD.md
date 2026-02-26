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
- Pre-computed progress data (Wilson CI, cross-matches, goals) in leaderboard background loop
- Pre-computed summary stats in leaderboard background loop
- Increased admin cache TTL from 10s to 30s
- Frontend polling aligned: 15s active / 30s idle
- Result: category switching drops from ~2s to ~90-120ms

### Fundamental Performance Architecture Fix (Feb 23 2026)
- Thread pool executor for ALL 25+ `compute_leaderboard` calls
- Eliminated redundant "all papers" leaderboard
- Removed DB query from validation `cache_get()`
- Pre-computed scipy z-value
- Benchmarks: 0.8s cache refresh (non-blocking), 90ms p99

### Paper Deduplication (Feb 23 2026)
- Title+first-author dedup check during paper fetching
- `/api/admin/dedup-papers` endpoint to merge existing duplicates
- Merged 11 duplicates on preview

### LLM Budget Error Resilience (Feb 23 2026)
- Budget/credit error detection in LLM comparison and impact assessment
- 15s wait for auto-topup before retrying

### Scheduler Decoupling (Feb 23 2026)
- Independent `_fetch_loop` (60s) and `_compare_loop` (30s/wake)
- Fetching no longer blocks tournament comparisons

## Completed (Feb 26 2026)

### Category Add Bug Fix
- Fixed `add_category` endpoint: now sets both `status: "paused"` AND `compare_paused: true`
- Previously only set `status: "paused"`, causing frontend to show toggle ON while backend skipped comparisons
- Activated cs.CR tournament on production

### Raised LLM Input Char Limit (40k → No Limit)
- **Problem**: 81.3% of papers exceeded the 40k char limit; median paper lost ~34% of content; 24.8% of summaries had truncation complaints
- Removed the hard 40k character limit entirely — full paper text is now sent to LLMs
- **Token-limit error handling**: On context-length errors, automatically halves content and retries (floor at 20k chars)
- Updated `_build_full_pdf_content`, `generate_precomparison_impact_summary`, and `compare_papers` (full_pdf mode)
- Cost impact: ~+54% per summary ($0.04 → $0.06 avg)

### One-Time Summary Regeneration (auto on deploy)
- Added `_startup_regen_truncated_summaries` to server.py startup — runs once on first production deploy
- Scans all summaries for truncation complaints (excluding false positives like "truncated normal distribution")
- Regenerates each affected summary with the same model that produced the original
- Gated by DB flag `regen_truncated_summaries_v1` — won't re-run after completion
- Past match results are unaffected (matches store their own winner/reasoning at comparison time)
- Admin endpoints: `POST /api/admin/regen-summaries` (manual trigger, supports dry_run) + `GET /api/admin/regen-summaries/status`
- Estimated cost: ~$26 for 278 summaries across 208 papers

## Pending
- Deploy to production on kurate.org
- **Run dedup on production after deploy** (POST /api/admin/dedup-papers)
- Complete remaining Opus 4.6 ICLR replays (coverage 39-94%)
- Verify frontend convergence chart fix (client-side caching in CorrelationPage.jsx)
- Gap-stratified human accuracy UI
- Further split validation.py into modules
- Add remaining HTTP security headers (CSP refinement)
