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

### Homepage (May 2026)
- Full homepage at `/` with 15 sections: Hero, Live Metrics, Positioning Strip, What Kurate Does, Why Discovery Needs Ranking, How It Works, Ranking Signal, Categories, Research Intelligence, Institutional Intelligence, Live Research Pulse, Use Cases, Responsible AI, FAQ, Footer
- Backend `/api/homepage/stats` endpoint aggregates live data (total papers, categories, matches, top papers, etc.)
- Clean `/` → homepage; `/?period=recent` (or any leaderboard param) → leaderboard
- Navbar Leaderboard link updated to `/?period=recent`; logo returns to homepage
- Category label hidden in navbar on homepage
- Custom homepage footer with social links (X, LinkedIn, GitHub, Instagram, Facebook)
- Default app footer hidden on homepage, shown on all other routes
- FAQ section with accordion, responsive layout, dark-blue feature panels
- SEO metadata (OG tags, Twitter cards, canonical URL)

### Embedding A/B Test: Qwen3-0.6B (May 2026)
- Evaluated Qwen/Qwen3-Embedding-0.6B (local CPU via sentence-transformers) for Similarity Landscape
- Computed for both cs.GT (360 papers) and physics.comp-ph (249 papers)
- Added UI button "Embedding: Qwen3-0.6B" to SimilarityLandscapeSection
- Full quality metrics: Trustworthiness, Continuity, Neighborhood preservation, Explainability, Silhouette, Davies-Bouldin
- Results: Qwen3-0.6B ranks competitively — 2nd overall on cs.GT, weaker on physics.comp-ph

### Prediction Experiment Cleanup (May 2026)
- Removed obsolete prediction experiment (Gap Score) — code, endpoints, UI
- Startup migration deletes prediction matches (`mode: "prediction"` / `"prediction-fulltext"`)
- Also unsets `mode: null` on preview matches (artifact from backfill)
- Removed 3 backend endpoints: `/prediction-prompt`, `/run-prediction`, `/experiment-comparison`
- Removed prediction prompt editor from AdminPage.jsx
- AdminExperiment.jsx is now dead code (was already unused)

### Timeseries Endpoint Optimization (May 2026)
- Split `/admin/timeseries` to return totals-only by default (strips per-category fields)
- Added `date_from` / `date_to` query params for date range filtering
- Added `category` param for single-category drill-down
- Added compound index `(completed, failed, mode, primary_category, created_at)` for aggregation
- Response reduced from ~800KB (32 cats) to ~30KB for totals-only view

### Previous Work
- TrueSkill Sigma Convergence, Quality-Based Matchmaking
- Similarity Landscape (cs.AI, physics.comp-ph, cs.GT) with multiple methods
- Sub-tournament experiments (Top-50 quantum physics)
- SciNCL/SPECTER embedding A/B test
- Dual-pod optimization, Archive system, Orphan rankings fix

## Known Issues
- ChemRxiv papers: MOCKED from static JSON seed
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- K8s liveness probe misconfiguration: BLOCKED (infrastructure)

## Pending Tasks
- P0: Semantic Search & "Papers Like This" (cosine NN on embeddings)
- P0: Multiple Reviewer Personas (ReviewerToo paper)
- P0: Gemini embedding evaluation (needs direct Google API key — Emergent proxy doesn't support embeddings)
- P1: Live ChemRxiv Fetcher (replace static JSON)
- P1: SSR for Bots/SEO
- P1: Sub-topic matchmaking (LLM classifier)
- P1: Matryoshka-256 mode (truncate OpenAI 3072D → 256D)
- P1: Sitemap.xml
- P1: Author Verification (ORCID OAuth)
- P2: Circular import cleanup
- P2: Frontend render scaling (PixiJS/deck.gl for n > 2k)

## Cost Analysis (Production, as of May 22 2026)
- 20,891 papers, 492,754 matches
- Match cost: $3,498 (54%) | Summary cost: $3,021 (46%) | Total: $6,519
- $/paper trend: $0.75 (Feb) → $0.32 (Apr) → $0.16 (May) — 5x decline
- Dominant cost: Claude Opus thinking summaries ($3,185 = 40% of total)
- Platform pricing uses Emergent rates (Claude $5/$25, GPT $1.75/$14, Gemini $2/$12 per M tok)

## Scaling Readiness (All-ArXiv audit, May 2026)
- 155 arXiv categories, ~1,600 papers/day, ~60K matches/day
- Critical: Timeseries endpoint restructured (payload reduction, date range filtering)
- Moderate: `_select_pairs` memory (~65MB/category), ArXiv rate limiting (~54min fetch cycle)
- Low risk: Leaderboard serving, category config, frontend selector

## Key Documents
- /app/memory/TRUESKILL_CONVERGENCE_PLAN.md
- /app/memory/ORPHAN_RANKINGS_PLAN.md
- /app/tools/embed_qwen3_to_landscape.py
