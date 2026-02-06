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
├── services/llm.py       # LLM comparison (random model)
├── services/ranking.py   # BT→Elo, Wilson CI
├── services/scheduler.py # Background scheduler + matchmaking + PDF download
├── routers/leaderboard.py # Public API
└── routers/admin.py      # Admin API + progress estimation
```

## Key Features
- Elo-style scores (LMArena format) with 95% CI (±N)
- Full paper PDF deep analysis (auto-download before comparisons)
- Adaptive UCB matchmaking with min-matches, top-K focus, anchor calibration
- Date filtering (Today/Week/Month/All) with global scores
- Admin panel: settings with tooltips, expandable comparison logs, progress indicator
- Custom evaluation prompt stored in DB used as default

## What's Been Implemented
- [Feb 2026] Complete rebuild from PaperSumo → automated leaderboard
- [Feb 2026] Modular backend, background scheduler, adaptive matchmaking
- [Feb 2026] Multi-model random selection (GPT 5.2, Claude Opus 4.5, Gemini 3 Pro)
- [Feb 2026] LMArena-style Elo scores with 95% CI (±N format)
- [Feb 2026] Full PDF deep analysis (auto-download before comparisons)
- [Feb 2026] Global BT scores (consistent across date filter views)
- [Feb 2026] Admin: expandable logs (full text), tooltips, progress indicator
- [Feb 2026] Min matches per paper setting + progress estimation

## Backlog
- P1: Historical ranking trends (paper rank over time)
- P2: Paper abstract preview on hover
- P2: Export leaderboard to CSV/PDF
- P3: RSS feed, public share links
- P3: Cross-category comparisons
