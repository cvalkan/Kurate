# Kurate.org — Product Requirements (Living Doc)

## Original Problem Statement
Build Kurate.org as a live scientific paper rankings and research discovery platform. Homepage modeled structurally after papermatch.me but with a refined, academic, white-only design. Must immediately show useful research discovery controls (search, category/year/time-period/ranking dropdowns) and live data: rankings, leaderboard, categories, metrics, signals. 13 panels in total + footer.

User explicit preference (only one given): **"All page has to be white, clean, academic style"** — overrode the brief's light-blue panels in favor of pure white with hairline borders and small blue accents.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor). 120 seeded scientific preprints across 12 arXiv-style categories. In-memory + Mongo snapshot. Endpoints under `/api`.
- **Frontend**: React 19 + react-router-dom + shadcn/ui + Tailwind. EB Garamond (headings) + IBM Plex Sans (body) via Google Fonts.
- **Routes**: `/` (homepage with 13 panels), `/leaderboard` (full table with URL-param filters).

## Implemented Endpoints
- `GET /api/categories` — 12 categories with paper_count + latest_update
- `GET /api/years` — sorted available ranking years
- `GET /api/metrics` — papers_ranked, active_categories, total_comparisons, ai_judges, latest_update, avg_model_agreement
- `GET /api/papers?category=&year=&period=&rank_type=&q=&limit=` — filtered + sorted ranked papers
- `GET /api/recent` — 8 recent ranking cards + recent_papers
- `GET /api/activity` — platform activity feed

## Implemented Sections (Frontend)
1. Top Nav (sticky, logo, 6 links, social icons LinkedIn/X/Medium, Explore Rankings CTA)
2. Hero Paper Rankings panel (H1 + search/filter card + 4 dropdowns + chips + leaderboard table + 6-tile metrics strip)
3. Recent Rankings (8 cards)
4. Browse Categories (search + field filter + grid + show-more)
5. Latest Platform Activity (feed list)
6. Research Intelligence Signals (8 cards)
7. How Kurate Rankings Work (5-step workflow)
8. Why Category-Based Rankings Matter
9. Platform Capabilities (6 cards)
10. What Makes Kurate Different (4-row comparison)
11. Who Kurate Is For (6 personas)
12. Trust, Transparency, Limitations
13. FAQ (13-item accordion)
14. Footer (5 columns, dark slate, social links visible)

## Test Status (Feb 2026)
- Backend: 12/12 pytest tests pass (100%)
- Frontend: All testids verified, hero filters live-update leaderboard, /leaderboard preserves URL params, FAQ accordion works (100%)

## Backlog (P1 / next phases)
- P1: Real arXiv/Kurate live API ingestion (currently seeded data)
- P1: Wire emergent LLM key for actual AI-assisted paper comparison
- P1: Paper detail page (currently "View" links are stubs)
- P2: User accounts + saved rankings / reading lists
- P2: Methodology, Validation, About sub-pages
- P2: Migrate FastAPI startup events to lifespan context manager
- P2: Email digest of newly ranked papers in subscribed categories
