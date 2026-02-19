# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Core Features Implemented
- Multi-dataset validation tournaments (ICLR, MIDL, PeerRead, eLife, F1000, ResearchHub)
- MIDL importer (fetches papers + reviews from OpenReview API)
- Tier-based validation (Oral/Spotlight/Poster/Reject vs AI rankings)
- Convergence analysis with multi-mode comparison
- Goal-directed matchmaking with Wilson CI stopping criteria
- Dynamic mode discovery, cross-mode fill, stop-tournament
- Semaphore-based parallel LLM pipeline

## Datasets
| Dataset | Papers | Source | abs+sum ρ | full_pdf ρ | Winner |
|---|---|---|---|---|---|
| ICLR LLMs | 73 | ICLR | 0.771 | 0.751 | abs+sum |
| ICLR Protein Science | 46 | ICLR | 0.770 | 0.743 | abs+sum |
| ICLR Optimization | 42 | ICLR | 0.742 | 0.716 | abs+sum |
| ICLR Code Generation | 62 | ICLR | 0.685 | 0.760 | full_pdf |
| ICLR Optimal Transport | 52 | ICLR | 0.528 | 0.516 | abs+sum |
| ICLR Molecules | 46 | ICLR | 0.513 | 0.544 | full_pdf |
| ICLR PDEs & Dyn Systems | 80 | ICLR | 0.488 | 0.459 | abs+sum |
| ICLR Fairness | 68 | ICLR | 0.432 | 0.448 | full_pdf |
| MIDL Medical Imaging | 81 | MIDL/OpenReview | 0.270 | 0.339 | full_pdf |
| PeerRead ACL 2017 | 80 | PeerRead | — | — | — |
| eLife Neuroscience | 100 | eLife | — | — | — |
| F1000Prime Alzheimer's | 54 | F1000 | — | — | — |

## Key Findings
- **abstract+summary wins in 5/9 domains** (LLMs, Protein, Optimization, OT, PDEs)
- **full_pdf wins in 4/9 domains** (Code Gen, Molecules, Fairness, MIDL Medical) — these are experimentally-dense, methodology-heavy domains
- **MIDL Medical Imaging has the largest full_pdf advantage** (Δ=+0.069) and lowest overall ρ (0.339), partly because expert-expert agreement is only 58%
- **eLife Neuroscience** has poor ground truth (4-point consensus scale, no rejected papers) — not suitable for tournament validation

## Pending/Backlog
- Import more eLife or medical datasets
- Run abstract-only baselines for new datasets
- Cross-mode fill for pairwise views
- Multi-model data fill for PDEs, iclr-llms, iclr-ot
- HTTP security headers
- Production deployment sync
- Refactor data processing into backend/services layer

## Recent Changes (Feb 2026)
- Built MIDL importer (OpenReview API → papers + reviews + PDFs)
- Imported MIDL Medical Imaging (81 papers, 2024-2025)
- Imported ICLR Fairness (68), Molecules (46), Optimization (42)
- Ran abstract+summary and full_pdf tournaments for all new datasets
- Fixed frontend build with correct REACT_APP_BACKEND_URL
