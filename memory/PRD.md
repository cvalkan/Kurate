# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro
- **Input format**: Abstract + AI impact assessment summary
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Backend File Structure
```
/app/backend/
  server.py                         # FastAPI app, security headers, rate limiting, startup tasks
  core/config.py                    # DB, LLM key, TOURNAMENT_MODELS, prompts
  core/auth.py                      # Admin auth (timing-safe), settings management
  services/
    scheduler.py                    # Summary generation (_SUMMARY_GENERATION_MODELS), matchmaking
    ranking.py                      # Bradley-Terry, Elo, Wilson CI
    llm.py                          # LLM calls, PDF extraction, section extraction
    task_tracker.py                 # Generic persistent background task tracker
    arxiv.py, chemrxiv.py           # Paper fetchers
  routers/
    leaderboard.py                  # Main leaderboard + paper detail + model correlation
    admin.py                        # Admin dashboard + /background-tasks endpoint
    validation.py                   # ~6450 lines: tournaments, analysis, experiments
    validation_imports.py           # ~920 lines: dataset import endpoints
    validation_utils.py             # Shared utilities for validation
    summary_bias.py                 # Summary bias experiment (tracked)
    pairwise.py, scipost.py, qeios.py
```

## Resilience & Task Tracking
- **Summarizer A/B**: Persistent queue in `summarizer_ab_tasks` collection. Auto-resumes on restart.
- **All experiments**: Tracked via `TaskTracker` → `background_tasks` collection. On startup, interrupted tasks are logged as warnings.
- **Batch endpoint**: `POST /api/validation/summarizer-ab/queue-batch` auto-detects datasets with missing GPT/Gemini summaries.
- **Admin visibility**: `GET /api/admin/background-tasks` shows task history.

## Pending Tasks
- (P1) Anchor selection logic improvement (pending user approval)
- (P2) Further refactor validation.py (extract experiments ~1600 lines)
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict

## Recent Updates (Mar 6 2026)
- Fixed a live-tournament scaling bug in `backend/services/scheduler.py` where large categories could be implicitly truncated at 500 papers.
- `_generate_paper_summaries`, `_check_goals_met`, and `_store_ranking_snapshot` now process full result sets in batches instead of hard-capping at 500 papers.
- Added backend regression tests in `backend/tests/test_scheduler_large_category_regressions.py` covering >500-paper summary generation and convergence evaluation.

## elife-comp-sys-bio Status
Not corrupt. Summaries at top-level (`ai_impact_summary`), not in `summaries` dict. By design — validation datasets are separate from live tournament.
