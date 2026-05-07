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
- 21 active categories (arXiv + ChemRxiv + IACR ePrint) with automated fetch/summarize/match pipeline
- TrueSkill-based ranking with CI convergence goals (10% top-K, 15% general)
- Round-robin judge rotation (Claude, GPT, Gemini)
- Weekly archive snapshots with medal awards
- IACR ePrint fetcher (OAI-PMH + RSS)
- GC optimizations (force_gc between reranks, chunked bulk_write 5000 ops)

### Admin Panel (Real-time)
- `progress` and `status` endpoints serve fresh data (no cache)
- Memory usage chart with restart event markers
- Restart history API (`/api/admin/restart-history`) with signal diagnostics
- Goals computed fresh every scheduler cycle (batch $in queries)

### Validation Hub
- Judge Comparison: average-score GT, split accuracy/ρ methodology
- Summarizer Rating Distributions: 6 models × 5 dimensions
- Multiple summarizer A/B tests

### SEO
- `react-helmet` dynamic `<title>` and canonical tags per category
- `ScholarlyArticle` JSON-LD on paper pages

### Restart Diagnostics (NEW - May 7, 2026)
- Signal handlers capture SIGTERM/SIGINT with uptime and argv
- Shutdown events persisted to MongoDB system_logs
- `--reload` auto-removal with os.execv fallback if config is read-only
- `/api/admin/restart-history` endpoint for admin visibility

### Category UI Grouping (NEW - May 7, 2026)
- Categories API returns `group` field per category
- "More" dropdown groups categories by domain (CS, Physics, Chemistry, etc.)
- Search filter in dropdown for quick category finding

## Known Issues
- P1: Missing GPT/Gemini SI Ratings (GPT-5.2 summaries don't include score block)
- P2: Duplicate medals in archives
- ChemRxiv papers: MOCKED from static JSON seed file (not live API)

## Pending Tasks
- P0: Investigate production server restarts (diagnostics deployed, awaiting data)
- P0: Implement Multiple Reviewer Personas (ReviewerToo)
- P1: Live ChemRxiv Fetcher (replace static JSON with live API)
- P1: Sub-topic Matchmaking (LLM Classifier)
- P1: Author Verification (ORCID OAuth)
- P1: Architecture Split (KURATE_ROLE env var)
- P1: Duplicate paper reconciliation (arxiv_id versioning)
- P1: Circular import resolution (core/auth.py → routers/admin.py → services/precompute.py)

## API Keys (in .env)
- `EMERGENT_LLM_KEY` — Claude 4.6, Gemini 3 Pro
- `OPENAI_API_KEY_GPT54` — GPT-5.5
- `DEEPSEEK_API_KEY` — DeepSeek V4-Pro
- `KIMI_API_KEY` — Kimi K2.6
- `ANTHROPIC_API_KEY` — Claude Opus 4.7 (pending activation)
- `SYNC_PULL_ENABLED=true` — Only on preview, never production
