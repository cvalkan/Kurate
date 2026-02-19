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
- Stop-tournament endpoint for graceful cancellation
- Semaphore-based parallel LLM pipeline (streaming, resilient)
- Tier Convergence chart

## Datasets
| Dataset | Papers | Status |
|---|---|---|
| ICLR LLMs | 73 | Complete |
| ICLR Code Generation | 62 | Complete |
| ICLR Optimal Transport | 52 | Complete |
| ICLR PDEs & Dynamical Systems | 80 | Complete (extract + abstract+summary + pairwise overlap) |
| ICLR Protein Science | 46 | Complete |
| ICLR Fairness | 68 | NEW — abstract+summary done (500 matches, ρ=0.432), full_pdf in progress |
| PeerRead ACL 2017 | 80 | Complete |
| eLife Neuroscience | 100 | Complete |
| F1000Prime Alzheimer's | 54 | Complete |

## Cross-Dataset Content Mode Comparison (ICLR)
| Dataset | abstract+summary ρ | full_pdf ρ | Winner |
|---|---|---|---|
| LLMs | **0.771** | 0.751 | abstract+summary |
| Code Generation | 0.685 | **0.760** | full_pdf (OUTLIER) |
| Optimal Transport | **0.528** | 0.516 | abstract+summary |
| PDEs | **0.488** | 0.459 | abstract+summary |
| Protein Science | **0.770** | 0.743 | abstract+summary |
| Fairness | 0.432 | TBD | TBD |

## Key Technical Decisions
- Matchmaking is goal-directed (CI-based), not match-count-based
- Fetching is independent of tournament match-running status (uses active_categories from settings)
- Custom prompts stored via `prompt_tag` field on matches, queried as `content_mode:prompt_tag`
- Convergence chart auto-discovers modes via `/api/validation/available-modes`
- ICLR dataset uses berenslab/iclr-dataset parquet (v26v1 for newest labels like PDEs, fairness)
- Cross-mode comparison threshold: 20% of largest mode (min 50 pairs)
- Semaphore-based parallel pipeline replaces batch asyncio.gather

## Available ICLR Labels (berenslab 26v1, not yet imported)
- optimization (292 eligible papers)
- molecules (46 eligible papers)
- diffusion models, RL, graphs, 3D scenes, speech, safety, alignment, autonomous driving, knowledge graph, neuroscience, transformers, generative models, etc.

## Pending/Backlog
- Complete full_pdf tournament for fairness dataset
- Run abstract-only baseline for fairness
- Import optimization and/or molecules datasets
- Multi-model fill for PDEs
- HTTP security headers
- Production deployment sync
- Refactor data processing into backend/services layer

## Recent Changes (Feb 2026)
- Imported ICLR Fairness dataset (68 papers) from 26v1 parquet
- Generated impact summaries for all 68 fairness papers
- Completed 500-match abstract+summary tournament (ρ=0.432)
- Started 500-match full_pdf tournament
- Rebuilt frontend with correct REACT_APP_BACKEND_URL
