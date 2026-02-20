# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Core Features Implemented
- Multi-dataset validation tournaments (ICLR, MIDL, eLife, PeerRead, F1000, ResearchHub)
- MIDL importer (OpenReview API → papers + reviews + PDFs)
- eLife importer (eLife API → reviewed preprints with significance + strength assessments)
- Dual-dimension correlation endpoint (AI ranking vs significance AND strength separately)
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
| eLife Microbiology | 80 | eLife API | sig=0.418, str=0.477 | TBD | — |

## Key Findings
- **abstract+summary wins in 5/9 ICLR+MIDL domains** — theory/conceptual domains
- **full_pdf wins in 4/9 domains** — experimentally-dense, methodology-heavy domains
- **NEW: AI correlates more with strength of evidence (ρ=0.477) than significance (ρ=0.418)** in eLife Microbiology — LLMs are better at judging "how well" than "how important"

## Pending/Backlog
- Run full_pdf tournament on eLife Microbiology
- Import more eLife subjects (Cancer Biology, Immunology)
- Add dual-dimension visualization to frontend
- Multi-model data fill for existing datasets
- HTTP security headers
- Production deployment sync
