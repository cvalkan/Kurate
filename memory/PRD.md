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
- Token usage tracking by model (input/output) with cost estimation
- Dual-goal progress: min matches per paper + CI convergence for top-K
- Date filtering (Today/Week/Month/All) with global scores
- Admin panel: settings with tooltips, expandable logs, progress indicator, usage stats

## API Pricing (per 1M tokens)
- GPT-5.2: $1.75 input / $14.00 output
- Claude Opus 4.5: $5.00 input / $25.00 output
- Gemini 3 Pro: $2.00 input / $12.00 output

## What's Been Implemented
- [Feb 2026] Complete rebuild from PaperSumo → automated leaderboard
- [Feb 2026] Modular backend, background scheduler, adaptive matchmaking
- [Feb 2026] Multi-model random selection with token tracking
- [Feb 2026] LMArena-style Elo scores with 95% CI (±N format)
- [Feb 2026] Full PDF deep analysis (consolidated download pipeline)
- [Feb 2026] Token usage stats: input/output by model + estimated cost
- [Feb 2026] Dual-goal progress bar: min matches + CI convergence for top-K
- [Feb 2026] Configurable parallel agents (1-20)

## Backlog
- P1: Historical ranking trends (paper rank over time)
- P2: Paper abstract preview on hover
- P2: Export leaderboard to CSV/PDF
- P3: RSS feed, public share links
- P3: Cross-category comparisons
