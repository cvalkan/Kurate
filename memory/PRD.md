# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Core Features Implemented
- Multi-dataset validation tournaments (ICLR, PeerRead, eLife, F1000, ResearchHub)
- Tier-based validation (Oral/Spotlight/Poster/Reject vs AI rankings)
- Convergence analysis with multi-mode comparison
- Goal-directed matchmaking with Wilson CI stopping criteria
- Connectivity-aware pair selection (ensures well-connected tournament graphs)
- Custom prompt tournaments with prompt tagging (tested; editorial prompt showed lower ρ due to "flashiness bias")
- Dynamic mode discovery (auto-discovers prompt-tagged variants in UI)
- Cross-mode fill endpoint for creating pair overlap between modes
- Auto-fetch scheduler (fetches papers for all active_categories, independent of tournament status)
- Graph connectivity metrics in status endpoint

## Datasets
| Dataset | Papers | Status |
|---|---|---|
| ICLR LLMs | 73 | Complete |
| ICLR Code Generation | 62 | Complete |
| ICLR Optimal Transport | 52 | Complete |
| ICLR PDEs & Dynamical Systems | 80 | Complete (extract + abstract+summary + pairwise overlap) |
| ICLR Protein Science | 46 | Complete |
| PeerRead ACL 2017 | 80 | Complete |
| eLife Neuroscience | 100 | Complete |
| F1000Prime Alzheimer's | 54 | Complete |

## Key Technical Decisions
- Matchmaking is goal-directed (CI-based), not match-count-based
- Fetching is independent of tournament match-running status (uses active_categories from settings)
- Custom prompts stored via `prompt_tag` field on matches, queried as `content_mode:prompt_tag`
- Convergence chart auto-discovers modes via `/api/validation/available-modes`
- ICLR dataset uses berenslab/iclr-dataset parquet (v26v1 for newest labels like PDEs)
- Cross-mode comparison threshold: 20% of largest mode (min 50 pairs)

## Recent Changes (Feb 2026)
- Imported PDEs dataset from 26v1 parquet (80 papers, new label)
- Fixed auto-fetch bug: scheduler now uses active_categories from settings, not tournament status
- Added custom prompt tournament support with prompt_tag (tested editorial prompt; removed due to weaker ρ)
- Added connectivity-aware pair selection for well-connected graphs
- Added graph connectivity metrics to status endpoint
- Fixed convergence chart missing "extract" mode
- Added cross-mode fill endpoint for creating pair overlap
- Completed PDEs cross-mode fill: 497 overlapping pairs between extract and abstract+summary
- Lowered cross-mode core threshold from 50% to 20% for asymmetric datasets

## Pending/Backlog
- Import more datasets (Diffusion Models, RL, Graphs)
- Multi-model fill for PDEs
- HTTP security headers
- Production deployment sync
- Refactor data processing into backend/services layer
