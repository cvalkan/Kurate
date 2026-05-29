# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4-6 (Emergent key), GPT-5.2 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup
- **Reviewer Personas**: 5 distinct AI reviewer personas (Methodologist, Innovator, Practitioner, Generalist, Skeptic) assigned round-robin per match

## What's Been Implemented

### Multiple Reviewer Personas (May 2026)
- 5 reviewer personas defined in `core/config.py`: Methodologist, Innovator, Practitioner, Generalist, Skeptic
- Each persona has a unique system prompt that weights evaluation criteria differently
- Round-robin assignment via `_pick_persona()` in scheduler
- Persona ID stored on every new match document (`persona` field)
- `compare_papers()` in llm.py accepts optional `persona` parameter
- Public API: `GET /api/homepage/personas` returns persona list
- Admin API: `GET /api/admin/persona-stats` returns per-persona match statistics
- Homepage: "Five reviewer personas" panel with 5 cards
- Methodology page: Step 4 "Diverse Reviewer Personas" with 5 colored badges
- Combined with 3 models = 15 unique (model x persona) judge configurations

### Homepage Messaging Realignment (May 2026)
- Hero: "AI-powered paper rankings" + "Multiple AI judges compare preprints head-to-head..."
- Search: "Search ranked papers by topic..." + "View Rankings" button
- "How Kurate ranks papers": Pairwise AI tournaments, TrueSkill scoring, Transparent validation
- "What the AI judges evaluate": 8 dimension cards (Novelty, Rigor, Impact, Applications, etc.)
- "Rankings by category": Updated copy
- "Who benefits from AI rankings": Updated copy for researchers/readers/institutions
- FAQ: 7 questions focused on AI ranking (including "Which AI models judge?" and "How can I trust?")
- Footer: "AI-powered paper rankings for preprints"
- Trust line: "Ranking preprints with AI. Not a replacement for peer review."

### Homepage (May 2026)
- Full homepage at `/` with clean app-like layout
- Backend `/api/homepage/stats` endpoint aggregates live data
- Clean `/` -> homepage; `/?period=recent` -> leaderboard
- SEO metadata (OG tags, Twitter cards, canonical URL)

### Previous Work
- TrueSkill Sigma Convergence, Quality-Based Matchmaking
- Similarity Landscape (cs.AI, physics.comp-ph, cs.GT)
- Embedding A/B tests (Qwen3, SciNCL, SPECTER)
- Timeseries endpoint optimization
- Backend code quality fixes (circular imports, MD5->SHA256, late-binding closures)

## Known Issues
- ChemRxiv papers: MOCKED from static JSON seed
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- K8s liveness probe misconfiguration: BLOCKED (infrastructure)
- Badge endpoint scraping anomaly: Not yet rate-limited

## Pending Tasks
- P0: Semantic Search & "Papers Like This" (cosine NN on embeddings)
- P0: Gemini embedding evaluation (needs direct Google API key)
- P1: Live ChemRxiv Fetcher (replace static JSON)
- P1: SSR for Bots/SEO
- P1: Sub-topic matchmaking (LLM classifier)
- P1: Matryoshka-256 mode (truncate OpenAI 3072D -> 256D)
- P1: Parametric UMAP (stable projections)
- P1: Sitemap.xml
- P1: Author Verification (ORCID OAuth)
- P1: Badge endpoint rate limiting
- P2: Frontend render scaling (PixiJS/deck.gl for n > 2k)

## Key Files
- `/app/backend/core/config.py` — REVIEWER_PERSONAS, PERSONA_IDS, TOURNAMENT_MODELS
- `/app/backend/services/scheduler.py` — _pick_persona(), match pipeline
- `/app/backend/services/llm.py` — compare_papers(persona=)
- `/app/backend/routers/homepage.py` — /api/homepage/stats, /api/homepage/personas
- `/app/backend/routers/admin.py` — /api/admin/persona-stats
- `/app/frontend/src/pages/HomePage.jsx` — Homepage with personas panel
- `/app/frontend/src/pages/MethodologyPage.jsx` — Step 4: Diverse Reviewer Personas
