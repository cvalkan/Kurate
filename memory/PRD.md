# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5/4.6, Gemini 3 Pro (via Emergent LLM key)

## Datasets & Results

### ICLR Tournaments — Opus 4.5 vs 4.6 (Controlled A/B on same pairs)
| Dataset | Papers | Opus 4.5 ρ | Opus 4.6 ρ | Winner |
|---|---|---|---|---|
| Code Generation | 62 | 0.685 | **0.690** | 4.6 |
| Fairness | 68 | 0.432 | **0.562** | 4.6 |
| LLMs | 73 | **0.771** | 0.746 | 4.5 |
| Molecules | 46 | 0.513 | **0.637** | 4.6 |
| Optimization | 42 | **0.742** | 0.738 | ~tie |
| Optimal Transport | 52 | 0.528 | **0.690** | 4.6 |
| PDEs | 80 | 0.488 | **0.552** | 4.6 |
| Protein Science | 46 | 0.770 | **0.785** | 4.6 |

### MIDL Medical Imaging
| 81 papers | abs+sum ρ=0.270 | full_pdf ρ=0.339 | full_pdf wins |

### eLife Dual-Dimension (Significance vs Strength)
| Dataset | Sig ρ | Str ρ | Pattern |
|---|---|---|---|
| Microbiology | 0.418 | **0.477** | Strength > Significance |
| Cancer Biology | 0.302 | **0.438** | Strength > Significance |
| Neuroscience | **0.381** | 0.134 (n.s.) | Significance only |

### Qeios Per-Domain (50 papers each, abs+sum)
| Domain | ρ | Human Experts |
|---|---|---|
| Social Sciences | 0.542 | 1,183 |
| Physical Sciences | 0.443 | 1,181 |
| Life Sciences | 0.441 | 990 |
| Health Sciences | 0.414 | 1,074 |

## Key Importers Built
- ICLR (berenslab parquet)
- MIDL (OpenReview API)
- eLife (eLife API with dual-dimension scoring)
- Qeios (Crossref + page scraping for aggregate ratings)

## Completed (This Session — Feb 21 2026)
- Fixed corrupted ICLR Code Generation opus46 tournament data (root cause: missing `winner_id` field)
- Backfilled `winner_id` for all 7,688 opus46 matches across 8 ICLR datasets
- Fixed bug in replay code (`judge_key` → `judge_model`)
- Fixed replay code to store `winner_id` going forward
- Rebuilt frontend with correct API URL

## Pending/Backlog
- (P1) Complete fair replay of Opus 4.6 tournaments for remaining ICLR datasets (some have fewer matches than source)
- (P2) Add UI visualization for gap-stratified human accuracy in A/B test section
- (P2) Complete data generation for `iclr-llms` dataset
- (P2) Add missing HTTP security headers
- (P2) Production deployment (user action required)
- (P3) Refactor backend logic from routers into services layer
- Run full_pdf tournaments for Qeios domains
- Strip HTML tags from paper titles
- Hide 0% Expert-Expert for single-evaluator datasets
