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
| Dataset | Papers | Status | abs+sum ρ | full_pdf ρ | Winner |
|---|---|---|---|---|---|
| ICLR LLMs | 73 | Complete | 0.771 | 0.751 | abs+sum |
| ICLR Protein Science | 46 | Complete | 0.770 | 0.743 | abs+sum |
| ICLR Optimization | 42 | Complete | 0.742 | 0.716 | abs+sum |
| ICLR Code Generation | 62 | Complete | 0.685 | 0.760 | full_pdf |
| ICLR Optimal Transport | 52 | Complete | 0.528 | 0.516 | abs+sum |
| ICLR Molecules | 46 | Complete | 0.513 | 0.544 | full_pdf |
| ICLR PDEs & Dynamical Systems | 80 | Complete | 0.488 | 0.459 | abs+sum |
| ICLR Fairness | 68 | Complete | 0.432 | 0.448 | full_pdf |
| PeerRead ACL 2017 | 80 | Complete | — | — | — |
| eLife Neuroscience | 100 | Complete | — | — | — |
| F1000Prime Alzheimer's | 54 | Complete | — | — | — |

## Key Findings
- **abstract+summary wins in 5/8 ICLR domains** (LLMs, Protein, Optimization, OT, PDEs)
- **full_pdf wins in 3/8 domains** (Code Gen, Molecules, Fairness) — these are experimentally-dense, benchmark-heavy domains where critical quality signals live in the paper body
- **Code Generation has the largest full_pdf advantage** (Δ=+0.075), likely because benchmark tables, code snippets, and ablation studies are lost in summarization
- **Optimization has the highest abs+sum correlation** among theory-heavy domains (ρ=0.742), with 82.4% AI vs Expert Majority agreement
- **Tier accuracy** sometimes favors full_pdf even when ρ favors abs+sum (e.g., Optimization: 84.3% vs 82.8%)

## Available ICLR Labels (berenslab 26v1, not yet imported)
- diffusion models, RL, graphs, 3D scenes, speech, safety, alignment, autonomous driving, knowledge graph, neuroscience, transformers, generative models, etc.

## Pending/Backlog
- Run abstract-only baselines for new datasets
- Cross-mode fill for pairwise views
- Import more domains if desired
- Multi-model data fill for PDEs, iclr-llms, iclr-ot
- HTTP security headers
- Production deployment sync
- Refactor data processing into backend/services layer

## Recent Changes (Feb 2026)
- Imported ICLR Fairness (68 papers), Molecules (46 papers), Optimization (42 papers)
- Ran abstract+summary and full_pdf tournaments for all three new datasets
- Rebuilt frontend with correct REACT_APP_BACKEND_URL
- Discovered pattern: experimentally-dense domains (Code Gen, Molecules, Fairness) favor full_pdf
