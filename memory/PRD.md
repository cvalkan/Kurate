# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4.6 (Emergent key), GPT-5.5 (direct OpenAI key), Gemini 3 Pro (Emergent key)
- **Additional models tested**: DeepSeek V4-Pro, Kimi K2.6, Claude Opus 4.7
- **Scoring**: TrueSkill with Wilson CI convergence targets

## What's Been Implemented

### Core System
- 18 active arXiv categories with automated fetch/summarize/match pipeline
- TrueSkill-based ranking with CI convergence goals (10% top-K, 15% general)
- Round-robin judge rotation (Claude, GPT, Gemini)
- Weekly archive snapshots with medal awards

### Admin Panel (Real-time)
- `progress` and `status` endpoints serve fresh data (no cache)
- Only expensive endpoints (`stats`, `timeseries`) retain 5-min cache
- Goals computed fresh every scheduler cycle (batch $in queries)

### Validation Hub
- Judge Comparison: average-score GT, split accuracy/ρ methodology
- Summarizer Rating Distributions: 6 models × 5 dimensions with adjustable histograms
- Multiple summarizer A/B tests

### DeFi Leaderboard
- 138 curated "Blockchain & AI Agents" papers
- Self-contained tournament (2,862 matches, TrueSkill rankings)
- Separate from live system (`defi_matches`, `defi_rankings`)
- Author CSV export with emails

### Sync API
- Export endpoints (read-only, cursor-based pagination)
- Pull endpoint (background, `SYNC_PULL_ENABLED` guard)
- Production data can never be accidentally overwritten

### Paper Fetch Pipeline
- `date_from` based catch-up mode (pages through ALL papers since last fetch)
- 30-day default lookback for new categories
- `_pipeline_active` flag prevents duplicate LLM calls on manual add

## Known Issues
- P1: Missing GPT/Gemini SI Ratings (GPT-5.2 summaries don't include score block)
- P2: Duplicate medals in archives
- Anthropic direct key billing activation pending

## Pending Tasks
- P0: ~~Execute Scoring Simplification Plan (`/app/memory/SCORING_SIMPLIFICATION_PLAN.md`)~~ DONE (May 6, 2026)
- P0: Implement Multiple Reviewer Personas (ReviewerToo)
- P1: Sub-topic Matchmaking (LLM Classifier)
- P1: Author Verification (ORCID OAuth)
- P1: Architecture Split (KURATE_ROLE env var)

## API Keys (in .env)
- `EMERGENT_LLM_KEY` — Claude 4.6, Gemini 3 Pro
- `OPENAI_API_KEY_GPT54` — GPT-5.5
- `DEEPSEEK_API_KEY` — DeepSeek V4-Pro
- `KIMI_API_KEY` — Kimi K2.6
- `ANTHROPIC_API_KEY` — Claude Opus 4.7 (pending activation)
- `SYNC_PULL_ENABLED=true` — Only on preview, never production
