# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4.6 (Emergent key), GPT-5.5 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence targets
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup

## What's Been Implemented

### Core System
- 21 active categories (arXiv + ChemRxiv + IACR ePrint) with automated fetch/summarize/match pipeline
- TrueSkill-based ranking with sigma convergence goals (general σ≤2.5, top-K σ≤2.0)
- Round-robin judge rotation (Claude, GPT, Gemini)
- Weekly archive snapshots with medal awards
- Dual-pod leader election with follower memory optimization

### TrueSkill Sigma Convergence (NEW - May 16, 2026)
- Convergence check uses raw TrueSkill sigma instead of Wilson CI
- Pair selection urgency based on sigma excess above target
- Admin progress shows ±Elo point labels (sigma × 20)
- Leaderboard 95% CI column displays ±Elo points
- Admin settings for sigma thresholds displayed as ±Elo

### Dual-Pod Optimization (NEW - May 14, 2026)
- Follower skips leader-only startup tasks (retry summaries, dedup, backfill, archive)
- Follower runs periodic GC every 5 minutes
- Promoted follower starts archive loop
- SIGTERM shutdown logs include pod_role
- Memory chart SIGTERM markers bolder (2.5px), colored per pod

### Admin Panel
- Memory chart with per-pod coloring (Leader=red, Follower=blue)
- Progress endpoint with sigma-based convergence goals
- Settings panel with ±Elo sigma threshold controls

### Validation Hub
- Judge Comparison: average-score GT, split accuracy/ρ methodology
- Summarizer Rating Distributions: 6 models × 5 dimensions
- ICLR 2024+2025 datasets from berenslab/iclr-dataset (iclr26v1.parquet)

### SEO
- `react-helmet` dynamic `<title>` and canonical tags per category
- `ScholarlyArticle` JSON-LD on paper pages

## Known Issues
- P1: Missing GPT/Gemini SI Ratings
- ChemRxiv papers: MOCKED from static JSON seed file (not live API)
- Twitter/X mobile unfurling: BLOCKED (awaiting Cloudflare WAF skip rule)

## Pending Tasks
- P0: Implement Multiple Reviewer Personas (ReviewerToo)
- P1: Live ChemRxiv Fetcher (replace static JSON with live API)
- P1: SSR for Bots/SEO (pre-rendered HTML for paper endpoints)
- P1: Sub-topic Matchmaking (Option A: arxiv secondary categories)
- P1: Author Verification (ORCID OAuth)
- P1: sitemap.xml with paper URLs
- P2: Circular import resolution

## API Keys (in .env)
- `EMERGENT_LLM_KEY` — Claude 4.6, Gemini 3.1 Pro
- `OPENAI_API_KEY_GPT54` — GPT-5.5
- `DEEPSEEK_API_KEY` — DeepSeek V4-Pro
- `KIMI_API_KEY` — Kimi K2.6
