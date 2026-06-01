# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain an AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments and single-item assessments, with validation experiments and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn/UI + Recharts
- **LLMs**: Claude Opus 4.6/4.8, GPT-5.2/5.4, Gemini 3 Pro, DeepSeek v4-Pro, Kimi K2.6
- **Scoring**: TrueSkill with quality-based matchmaking
- **Dual-Pod**: Leader/follower with MongoDB lock

## Latest Changes (Jun 1, 2026)

### Admin User Behavior Charts Overhaul
- 2x3 chart grid: "All Visitors" + "Registered Users Only" rows
- All Visitors: DAU (line/big stat), Daily Page Views, Category Popularity (horizontal bars)
- Registered: DAU, Visit Frequency (sessions since May 31), Category Popularity (horizontal bars)
- New visitor tracking middleware in server.py (IP hash, fire-and-forget, no PII)
- Leaderboard now tracks auth_views separately in category_views collection
- DAU: big number when <3 data points, line chart when enough data
- Horizontal bar charts show ALL active categories (even 0 views), same order both rows

### Precomputed Model Analysis (May 30)
- /api/model-analysis served from precomputed MongoDB documents (<50ms vs 7-15s)
- Daily background job processes one category at a time (bounded memory)
- Auto-triggers on startup + every 24h; manual trigger via admin endpoint

### Inter-Model Agreement Overhaul (May 30)
- PW Match Agreement: actual pair-level (replaces median-split)
- SI Score Agreement with Full/Controlled/Tiebreak toggle
- Simulation table: SI scores through simulated TrueSkill tournament

### Prompt Stability Experiments (May 30)
- 3 experiments on 88-206 papers (baseline, with-reasons, extended 11 dimensions)
- Extended: difficulty, surprisingness, reproducibility, translational_potential, evidence_strength, generalisability

## Production Stats (May 30, 2026)
- 22K+ papers, 500K+ matches across 34 categories
- $/paper: $0.16 (down from $0.75 at launch)
- PW inter-model agreement: 71-73% (pair-level)
- SI inter-model agreement: 82-84% (controlled), 70-77% (tiebreak)

## DB Collections
- `papers`: {id, arxiv_id, title, abstract, full_text, summaries, ai_ratings_by_model}
- `matches`: {paper1_id, paper2_id, winner_id, model_used, completed}
- `rankings`: {paper_id, category, score (Elo), ts_score, si_ratings}
- `users`: {user_id, email, name, provider, last_active, visit_count, created_at}
- `model_analysis_precomputed`: {key, computed_at, data}
- `daily_visitors`: {date, all_ips[], auth_ips[], total_hits} (NEW)
- `category_views`: {date, category, views, auth_views} (auth_views NEW)

## Known Issues
- TweetAPI returns 401 (external account limitation)
- SI score source: rankings.si_ratings is 33% populated; enrichment from summaries needed

## Pending
- P1: Extended prompt (5 categorical metrics)
- P1: SI source of truth consolidation
- P1: Landing page merge from GitHub branch
- P2: Semantic Search & "Papers Like This"
- P2: All-arXiv category expansion (~$1,400 backfill)
- P2: Multiple Reviewer Personas
- P2: Live ChemRxiv Fetcher
