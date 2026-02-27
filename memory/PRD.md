# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Key Results

### Deep Dive 2-Pass Assessment (Feb 26-27 2026)
- **Finding**: Two-pass assessments (first-pass + focused deep-dive) significantly improve agreement with human peer reviewers
- **ICLR Code Gen**: 74.1% human agreement vs 68.5% single-pass (p=0.001, McNemar's test), Spearman ρ=0.726
- **Method**: Step 1 generates assessment + focus areas JSON, Step 2 generates standalone deep-dive informed by focus areas, Step 3 replays tournament with same pairs + same judge models

## Completed (Feb 26-27 2026)

### Removed LLM Input Char Limit
- Old: 40k chars (truncated 81% of papers). New: no limit, full paper text sent
- Token-limit errors: auto-halve content and retry (floor at 20k chars)
- Production summary regeneration: ~400 truncated summaries being regenerated

### Category Management Bug Fix
- `add_category` now sets both `status: "paused"` AND `compare_paused: true`
- Previously UI showed toggle ON while backend skipped comparisons

### Deep Dive Experiment Infrastructure
- `services/iclr_deep_dive.py`: Parameterized pipeline for any dataset
- 5 parallel LLM workers, budget-aware retries, incremental DB saves, fully resumable
- API: `/api/validation/deep-dive-pipeline/run|status|results`
- Frontend: ICLRDeepDiveSection.jsx with live progress, paper browser, analysis dashboard
- Convergence integration: replays inserted as `content_mode: "deep_dive"`

### SEO
- robots.txt, dynamic sitemap.xml (all paper URLs), Open Graph/Twitter meta tags
- Page title: "PaperSumo by Kurate.org — AI Paper Rankings"

### DB-Persisted Regen Progress
- Summary regeneration progress survives server restarts
- Uses MongoDB instead of in-memory dict

### Summary Creation Dates
- `summary_dates.{model_key}` stored alongside summaries
- Displayed as "Generated [date]" on paper detail pages

## Datasets with Deep Dive Results
- iclr-codegen: 62 papers, 958 replays, ρ=0.726
- iclr-pdes: 80 papers, 869 replays (partial), ρ=0.585
- midl-medical-imaging: 81 papers, 498 replays, ρ=0.304

## Pending
- Resume iclr-pdes replay (869/1785 done)
- Deploy all changes to production
- Run deep-dive on more ICLR datasets
- Complete Opus 4.6 ICLR tournament replays
- Gap-stratified human accuracy UI
- Investigate MIDL low correlation (2-tier ground truth limitation)
