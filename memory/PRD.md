# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Tailwind CSS
- **LLMs**: Claude Opus 4.6 (Emergent key), GPT-5.2 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup
- **Reviewer Personas**: 5 distinct AI reviewer personas assigned round-robin per match

## What's Been Implemented

### Homepage Redesign — Scientific App Interface (May 2026)
- Complete rewrite of HomePage.jsx as a centered, app-like scientific ranking platform
- Design: Chivo headings, IBM Plex Mono data labels, academic blue (#1E3A8A), teal (#0F766E), green (#059669)
- Hero: "AI-powered scientific paper rankings" with "Explore rankings" (primary) + "Methodology" (secondary) CTAs
- Top Ranked Papers: Live leaderboard card showing rank, title, category, authors, TrueSkill score from API
- Research Intelligence sidebar: Model agreement, Validation signals, Methodology links
- AI Judge Panel: GPT-5.2 / Claude Opus 4.6 / Gemini 3.1 Pro model badges
- Live Platform Metrics: Dashboard-style grid (10.7k papers, 21 categories, 280.2k comparisons, etc.)
- Rankings by Category: Top 5 with counts + full 21-category grid
- How it works: 3-card section (Pairwise tournaments, TrueSkill, Validation)
- Trust badges: Monospaced uppercase strip
- Clean footer with Explore/Follow columns
- Testing: iteration_66 — 100% backend, 100% frontend

### Multiple Reviewer Personas (May 2026)
- 5 personas: Methodologist, Innovator, Practitioner, Generalist, Skeptic
- Unique system prompts per persona, round-robin assignment per match
- Persona stored on match documents (`persona` field)
- APIs: GET /api/homepage/personas (public), GET /api/admin/persona-stats (admin)
- Methodology page Step 4: "Diverse Reviewer Personas"
- Testing: iteration_65 — 100% pass

### Previous Work
- TrueSkill Sigma Convergence, Quality-Based Matchmaking
- Similarity Landscape, Embedding A/B tests
- Timeseries endpoint optimization
- Backend code quality fixes

## Known Issues
- ChemRxiv papers: MOCKED from static JSON seed
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- K8s liveness probe misconfiguration: BLOCKED (infrastructure)
- Badge endpoint scraping anomaly: Not yet rate-limited
- Pipeline stale: Latest update 111d ago (ingestion not running in preview)

## Pending Tasks
- P0: Semantic Search & "Papers Like This" (cosine NN on embeddings)
- P0: Gemini embedding evaluation (needs direct Google API key)
- P1: Live ChemRxiv Fetcher, SSR for Bots/SEO, sitemap.xml
- P1: Sub-topic matchmaking, Matryoshka-256, Parametric UMAP
- P1: Author Verification (ORCID OAuth), Badge rate limiting
- P2: Frontend render scaling (PixiJS/deck.gl for n > 2k)

## Key Files
- `/app/frontend/src/pages/HomePage.jsx` — Homepage (app-like design)
- `/app/backend/routers/homepage.py` — /api/homepage/stats, /api/homepage/personas
- `/app/backend/core/config.py` — REVIEWER_PERSONAS, TOURNAMENT_MODELS
- `/app/backend/services/scheduler.py` — _pick_persona(), match pipeline
- `/app/backend/services/llm.py` — compare_papers(persona=)
- `/app/frontend/src/pages/MethodologyPage.jsx` — Includes persona step
