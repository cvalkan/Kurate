# PaperSumo - Robotics Paper Leaderboard

## Original Problem Statement
Build a platform that automatically downloads new Robotics papers from arXiv daily, runs pairwise tournaments using full paper analysis via LLMs, and outputs a dynamically updated ranked leaderboard using Bradley-Terry scores normalized to LMArena-style Elo ratings.

## Tech Stack
- **Frontend:** React, React Router, Axios, Tailwind CSS, Shadcn UI, lucide-react
- **Backend:** FastAPI (modular), Motor (async MongoDB), httpx, PyPDF2
- **Database:** MongoDB (papers, matches, settings collections)
- **LLMs:** OpenAI GPT-5.2, Anthropic Claude Opus 4.5, Google Gemini 3 Pro (via Emergent LLM Key)

## Key Behavior
The system runs **continuously until both goals are met**:
1. All papers reach minimum matches threshold
2. All top-K papers achieve CI ≤ target

Can be paused/resumed via admin panel. After goals met, idles until new papers arrive.

## Settings
- `comparisons_per_round` (50) — Matches per round
- `parallel_agents` (5) — Concurrent LLM calls (1-20)
- `min_matches_per_paper` (3) — Goal 1 threshold
- `ci_target` (200) — Goal 2: max CI (±Elo) for top-K
- `top_k_focus` (10) — Focus on top-K papers for CI convergence
- `paused` (false) — Pause/resume system

## API Pricing (per 1M tokens)
- GPT-5.2: $1.75 input / $14.00 output
- Claude Opus 4.5: $5.00 input / $25.00 output
- Gemini 3 Pro: $2.00 input / $12.00 output

## What's Been Implemented
- [Feb 2026] Complete rebuild → automated leaderboard
- [Feb 2026] LMArena-style Elo with 95% CI (±N)
- [Feb 2026] Continuous scheduler: runs until dual goals met, pausable
- [Feb 2026] CI-aware matchmaker: targets widest-CI top-K papers
- [Feb 2026] Token stats: input/output by model + cost estimation
- [Feb 2026] Dual progress bar: min matches + CI convergence

## Backlog
- P1: Historical ranking trends
- P2: Paper abstract preview on hover
- P2: Export leaderboard to CSV/PDF
