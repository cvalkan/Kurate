# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Completed (Feb 22 2026)

### Data & Experiments
- Opus 4.6 tournaments for all ICLR, eLife, MIDL datasets
- Fairness domain-specific prompt experiment (summary + judge)
- PDE domain-specific prompt experiment (judge only)

### Bug Fixes
- Opus 4.6 `winner_id` backfill (7,688 matches)
- Extract filter excluding tagged content modes
- cross-mode-agreement dynamic mode discovery
- agreement-analysis majority vote for multi-judge
- Tournament dedup filter fix
- `judge_key` → `judge_model` in replay code

### Performance
- Convergence: 30s → 0.2s (bisect + batch endpoint + cache)
- Stats tabs: 5-10s → 0.2s (server cache + smart default)
- Status endpoint: 6 serial queries → 2 parallel $facet
- Added MongoDB compound index (dataset_id, content_mode, completed, failed)
- Pre-warm ALL 21 datasets on startup
- Excluded full_text (96KB/paper) from 7 analysis endpoint projections

### Security
- CORS restricted to kurate.org (was wildcard *)
- Admin password moved to env var
- Missing auth added to summarizer-comparison/stop
- Rate limits on expensive endpoints (convergence, cross-mode)
- Tournament max duration (1 hour)
- Security headers (HSTS, CSP, X-Frame-Options, etc.)

### Cleanup
- Extracted validation_utils.py (shared utilities)
- Removed dead aliases, unused variables
- Consistent chart colors, legend labels
- Stable color map for content modes

### UI/Branding
- "PaperSumo by Kurate.org" branding
- "Preprint Rankings" (was "Paper Rankings")
- Claude as default AI summary tab
- Opus 4.5 → 4.6 throughout
- Validation "Work in Progress" badge
- Methodology updated for preprints + Opus 4.6

## Pending
- (P1) Complete remaining Opus 4.6 ICLR replays (coverage 39-94%)
- (P2) Gap-stratified human accuracy UI
- (P2) Deploy to production on kurate.org
- (P3) Further split validation.py into modules
- Run full_pdf tournaments for Qeios domains
