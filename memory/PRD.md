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
| ICLR PDEs & Dynamical Systems | 80 | Complete |
| ICLR Protein Science | 46 | Complete |
| ICLR Fairness | 68 | Complete (abstract+summary 500 matches + full_pdf 464 matches) |
| ICLR Molecules | 46 | Complete (abstract+summary 497 matches + full_pdf 482 matches) |
| PeerRead ACL 2017 | 80 | Complete |
| eLife Neuroscience | 100 | Complete |
| F1000Prime Alzheimer's | 54 | Complete |

## Cross-Dataset Content Mode Comparison (ICLR)
| Dataset | abstract+summary ρ | full_pdf ρ | Winner |
|---|---|---|---|
| LLMs | **0.771** | 0.751 | abstract+summary |
| Protein Science | **0.770** | 0.743 | abstract+summary |
| Code Generation | 0.685 | **0.760** | full_pdf (OUTLIER) |
| Optimal Transport | **0.528** | 0.516 | abstract+summary |
| Molecules | 0.513 | **0.544** | full_pdf |
| PDEs | **0.488** | 0.459 | abstract+summary |
| Fairness | 0.432 | **0.448** | full_pdf |

### Key Finding
Three domains favor full_pdf: Code Generation, Molecules, and Fairness. These are experimentally-dense, benchmark-heavy domains where critical quality signals (benchmark tables, ablation studies, molecular structures) live in the paper body rather than the abstract.

## Available ICLR Labels (berenslab 26v1, not yet imported)
- optimization (292 eligible papers — largest available pool)
- diffusion models, RL, graphs, 3D scenes, speech, safety, alignment, autonomous driving, knowledge graph, neuroscience, transformers, generative models, etc.

## Pending/Backlog
- Import optimization dataset if desired
- Run abstract-only baselines for fairness & molecules
- Cross-mode fill for pairwise comparison views
- Multi-model fill for PDEs
- HTTP security headers
- Production deployment sync
- Refactor data processing into backend/services layer

## Recent Changes (Feb 2026)
- Imported ICLR Fairness dataset (68 papers), ran abstract+summary and full_pdf tournaments
- Imported ICLR Molecules dataset (46 papers), ran abstract+summary and full_pdf tournaments
- Rebuilt frontend with correct REACT_APP_BACKEND_URL
- Discovered that Molecules is another full_pdf-favoring domain (joining Code Gen and Fairness)
