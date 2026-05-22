# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4-6 (Emergent key), GPT-5.2 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup

## What's Been Implemented

### Featured Categories System (May 2026)
- Separated "featured" (homepage tabs) from "active" (tournament participation)
- New `featured_categories` setting with backward-compatible fallback to first 5 of `active_categories`
- Backend endpoints: `set-featured`, `toggle-featured`, `reorder-featured`
- `/api/categories` returns `featured` list; `CategoryTabs.jsx` uses it
- AdminCategories rewritten: drag-reorderable featured section + unified dropdown with active/featured toggles
- AdminOverview: button ribbon replaced with dropdown selector (scales to 155+ categories)

### Prediction Experiment Cleanup (May 2026)
- Removed obsolete prediction experiment — code, endpoints, UI
- Startup migration deletes prediction matches + unsets `mode: null` artifacts
- Removed 3 backend endpoints, prediction prompt editor from AdminPage

### Timeseries Endpoint Optimization (May 2026)
- Split `/admin/timeseries` to return totals-only by default
- Added `date_from`/`date_to` and `category` params
- Added compound index for aggregation performance
- Response reduced from ~800KB → ~30KB for default view

### Qwen3-0.6B Embedding Evaluation (May 2026)
- Evaluated for Similarity Landscape (cs.GT + physics.comp-ph)
- Added UI button and full quality metrics
- Competitive on cs.GT, weaker on physics.comp-ph vs OpenAI/SciNCL

### Previous Work
- TrueSkill Sigma Convergence, Quality-Based Matchmaking
- Similarity Landscape with multiple embedding methods (OpenAI, SciNCL, SPECTER, Qwen3)
- Sub-tournament experiments, Dual-pod optimization
- Archive system, Orphan rankings fix

## Production Stats (May 22, 2026)
- 20,891 papers, 492K matches across 32 categories
- Match cost: $3,498 | Summary cost: $3,021 | Total: $6,519
- $/paper: $0.75 (Feb) → $0.16 (May) — 5x decline
- Dominant cost: Claude Opus thinking summaries (40% of total)

## Known Issues
- ChemRxiv papers: MOCKED from static JSON seed
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- K8s liveness probe misconfiguration: BLOCKED (infrastructure)
- TweetAPI interaction endpoints: 504 timeouts (TweetAPI-side issue)

## Pending Tasks
- P0: Semantic Search & "Papers Like This"
- P0: Multiple Reviewer Personas (ReviewerToo paper)
- P0: Gemini embedding evaluation (needs direct Google API key)
- P1: Live ChemRxiv Fetcher
- P1: SSR for Bots/SEO
- P1: AdminStatistics top-N category filter for charts
- P1: Sub-topic matchmaking, Matryoshka-256 mode
- P1: Sitemap.xml
- P2: Author Verification (ORCID OAuth)
- P2: Circular import cleanup
- P2: Frontend render scaling (PixiJS/deck.gl)

## Scaling Readiness
- Backend: all-arXiv ready (155 categories, ~1600 papers/day)
- Featured categories decoupled from active — homepage tabs independent of tournament scope
- Estimated backfill for all arXiv: ~9,600 papers (capped at 100/category), ~$1,400
- Timeseries optimized for 155 categories (totals-only default, per-category on demand)

## Key Documents
- /app/memory/TRUESKILL_CONVERGENCE_PLAN.md
- /app/memory/ORPHAN_RANKINGS_PLAN.md
- /app/tools/embed_qwen3_to_landscape.py
