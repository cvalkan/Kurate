# PaperSumo - Robotics Paper Leaderboard

## Original Problem Statement
Build a platform that automatically downloads new Robotics papers from arXiv daily, runs pairwise tournaments using full paper analysis via LLMs, and outputs a dynamically updated ranked leaderboard using Bradley-Terry scores normalized to LMArena-style Elo ratings.

## Tech Stack
- **Frontend:** React, React Router, Axios, Tailwind CSS, Shadcn UI, lucide-react
- **Backend:** FastAPI (modular), Motor (async MongoDB), httpx, PyPDF2
- **Database:** MongoDB (papers, matches, settings collections)
- **LLMs:** OpenAI GPT-5.2, Anthropic Claude Opus 4.5, Google Gemini 3 Pro (via Emergent LLM Key)

## Architecture
```
/app/backend/
├── server.py             # Entry point
├── core/config.py        # DB, models, prompts, defaults
├── core/auth.py          # Admin auth + settings merge
├── services/arxiv.py     # ArXiv API with retry
├── services/llm.py       # LLM comparison (random model, token tracking)
├── services/ranking.py   # BT→Elo, Wilson CI
├── services/scheduler.py # Background scheduler, matchmaking, PDF mgmt
├── routers/leaderboard.py # Public API
└── routers/admin.py      # Admin API, stats, progress
```

## Key Features
- Elo-style scores (LMArena format) with 95% CI (±N)
- Full paper PDF deep analysis (consolidated download pipeline)
- Adaptive UCB matchmaking with min-matches, top-K focus, anchor calibration
- Configurable parallel agents (1-20, default 5)
- Token usage tracking by model + storage stats
- Date filtering (Today/Week/Month/All) with global scores
- Admin panel: settings with tooltips, expandable logs, progress indicator, usage stats

## Settings (configurable via Admin)
- `fetch_interval_hours` (24) - How often to check arXiv
- `max_papers_per_fetch` (50) - Papers per fetch
- `comparisons_per_round` (20) - Comparisons per round
- `parallel_agents` (5) - Concurrent LLM calls (1-20)
- `top_k_focus` (10) - UCB top-K boundary
- `exploration_constant` (1.414) - UCB explore/exploit
- `anchor_comparisons` (4) - Anchors for new papers
- `min_matches_per_paper` (3) - Minimum matches threshold
- `auto_process` (true) - Auto-run comparisons

## What's Been Implemented
- [Feb 2026] Complete rebuild from PaperSumo → automated leaderboard
- [Feb 2026] Modular backend, background scheduler, adaptive matchmaking
- [Feb 2026] Multi-model random selection (GPT 5.2, Claude Opus 4.5, Gemini 3 Pro)
- [Feb 2026] LMArena-style Elo scores with 95% CI (±N format)
- [Feb 2026] Full PDF deep analysis (consolidated download pipeline)
- [Feb 2026] Token usage tracking by model + storage stats in admin
- [Feb 2026] Configurable parallel agents (1-20)
- [Feb 2026] Efficiency: no redundant PDF downloads, deduped DB queries

## Backlog
- P1: Historical ranking trends (paper rank over time)
- P2: Paper abstract preview on hover
- P2: Export leaderboard to CSV/PDF
- P3: RSS feed, public share links
- P3: Cross-category comparisons
