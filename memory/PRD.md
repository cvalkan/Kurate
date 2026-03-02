# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro (HIGH confidence this beats any single judge by +0.05-0.15 rho)
- **Input format**: Abstract + AI impact assessment summary
- **Pair selection**: Cross-tier only (same-tier filtered out)
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Backend File Structure
```
/app/backend/
  server.py                         # FastAPI app, security headers, rate limiting, startup
  core/config.py                    # DB, LLM key, TOURNAMENT_MODELS, prompts, DEFAULT_SETTINGS
  core/auth.py                      # Admin auth (timing-safe), settings management
  services/
    scheduler.py                    # Summary generation (Opus 4.6 Thinking), tournament matchmaking
    ranking.py                      # Bradley-Terry, Elo, Wilson CI
    llm.py                          # LLM calls, PDF extraction, section extraction
    arxiv.py, chemrxiv.py           # Paper fetchers
  routers/
    leaderboard.py                  # Main leaderboard + paper detail + model correlation + convergence
    admin.py                        # Admin dashboard, category management, cost estimation
    validation.py                   # ~6300 lines: validation tournaments, analysis, experiments
    validation_imports.py           # ~920 lines: extracted dataset import endpoints (ICLR, eLife, MIDL, PeerRead, F1000)
    validation_utils.py             # Shared utilities for validation
    summary_bias.py, pairwise.py, scipost.py, qeios.py  # Specialized routers
```

## Key Findings (from validation experiments)
- Opus 4.6 Thinking: rho=0.643, acc=81.1% (best summarizer)
- Round-robin judging beats any single judge by +0.05-0.15 rho
- Multi-aspect judging is WORSE than holistic (-4.9pp)
- Always compare on exact same pairs to avoid selection bias

## elife-comp-sys-bio Status (Mar 2 2026)
Not corrupt. Summaries exist at top-level (`ai_impact_summary`) but not in `summaries` dict.
Validation datasets are separate from live tournament — this is by design.

## Changes Made (Mar 2 2026)
1. Opus 4.6 Thinking for live tournament summarization (scheduler.py)
2. eLife datasets added to Summarizer Cross-Model experiment (frontend)
3. HTTP Security headers verified serving (already implemented)
4. Refactored: extracted validation import endpoints into validation_imports.py
5. Code review fixes:
   - asyncio.gather with return_exceptions in summary generation
   - Timing-safe password comparison (hmac.compare_digest)
   - Papers filtered by required summary key before tournament participation
   - Ranking snapshot seeding bug fixed
   - Lint cleanup

## Pending Tasks
- (P1) Improved anchor selection logic for tournament scheduler
- (P2) Complete GPT/Gemini summaries for remaining ICLR datasets
- (P2) Refactor validation.py further (extract experiments ~1600 lines)
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict
