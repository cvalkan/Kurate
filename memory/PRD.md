# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4.6 (Emergent key), GPT-5.2 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup

## What's Been Implemented

### TrueSkill Sigma Convergence
- Convergence uses raw TrueSkill sigma (general σ≤2.5 = ±50pts, top-K σ≤2.0 = ±40pts)
- Match floor: papers with ≥50 comparisons considered converged
- Undefeated urgency: 100%/0% WR papers stay mildly needy until they lose or hit floor
- Leaderboard CI column shows ±Elo points derived from sigma
- Admin settings for sigma targets + floor, displayed as ±Elo

### Quality-Based Matchmaking
- Opponent selection uses `trueskill.quality_1vs1()` (vectorized numpy, <1ms)
- Accounts for both skill difference AND uncertainty
- New papers face stronger opponents naturally; established papers get closest-score
- Calibration ratio preserved — quality operates within established/needy pool

### Archive System
- Single `create_archive_snapshot` function (merged duplicate)
- CI computed from ts_sigma at freeze time
- Backfill migration (v2) for production archives

### Dual-Pod Optimization
- Follower skips leader-only startup tasks
- Follower metadata cache refreshes every 5min
- Periodic GC for follower (every 5min)
- SIGTERM logs include pod_role
- Deploy vs Restart detection via build fingerprint hash

### Similarity Landscape
- cs.AI: 200 papers, 2000 pairwise similarity scores (1-20, Claude Opus 4.6)
- physics.comp-ph: 249 papers, ~2490 pairs (running)
- MDS + UMAP embedding, K-means clustering K=1-10
- LLM-generated cluster titles from abstracts
- Interactive visualization under /validation with configurable K, MDS/UMAP toggle, dot sizing

### Orphan Rankings Analysis
- Root cause: category cleanup deletes papers but not rankings
- 420 orphan rankings on preview (cosmetic), ~10 on production
- insert_ranking_for_paper fix: removed fragile summary check
- Documented at /app/memory/ORPHAN_RANKINGS_PLAN.md

## Known Issues
- ChemRxiv papers: MOCKED from static JSON seed
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- Orphan rankings: cosmetic ghost entries on leaderboard

## Pending Tasks
- P0: Multiple Reviewer Personas (ReviewerToo)
- P1: Live ChemRxiv Fetcher
- P1: Extended summarization/comparison prompts (structured data extraction)
- P1: SSR for Bots/SEO
- P1: Sub-topic matchmaking using similarity data

## Key Documents
- /app/memory/TRUESKILL_CONVERGENCE_PLAN.md
- /app/memory/ORPHAN_RANKINGS_PLAN.md
- /app/memory/EXTENDED_PROMPTS_PLAN.md
- /app/memory/similarity_experiment.json (raw cs.AI similarity scores)
