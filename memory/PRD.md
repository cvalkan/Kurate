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

### eLife — Opus 4.5 vs 4.6
| Dataset | Opus 4.5 ρ | Opus 4.6 ρ | Winner |
|---|---|---|---|
| Microbiology | 0.394 | **0.472** | 4.6 |
| Cancer Biology | **0.269** | 0.253 | 4.5 |
| Neuroscience | **0.398** | 0.394 | ~tie |

### eLife Dual-Dimension (Opus 4.6)
| Dataset | Sig ρ | Str ρ |
|---|---|---|
| Microbiology | **0.512** | 0.460 |
| Cancer Biology | 0.299 | **0.441** |
| Neuroscience | **0.352** | 0.137 |

### MIDL Medical Imaging — Opus 4.5 vs 4.6
| Opus 4.5 ρ=0.270 | Opus 4.6 ρ=0.314 | 4.6 wins |

### Qeios Per-Domain (50 papers each, abs+sum)
| Domain | ρ |
|---|---|
| Social Sciences | 0.542 |
| Physical Sciences | 0.443 |
| Life Sciences | 0.441 |
| Health Sciences | 0.414 |

## Key Importers Built
- ICLR (berenslab parquet)
- MIDL (OpenReview API)
- eLife (eLife API with dual-dimension scoring)
- Qeios (Crossref + page scraping)

## Completed (Feb 21 2026)
- **P0 Fix**: Opus 4.6 matches missing `winner_id` — backfilled 7,688 matches across 8 datasets
- **Bug fix**: `judge_key` → `judge_model` in replay code; replay now stores `winner_id`
- **Bug fix**: Extract filter was including tagged variants — added `$not: {$regex: ":"}`
- **Bug fix**: `cross-mode-agreement` hardcoded 5 modes — now dynamically discovers all modes
- **Bug fix**: `agreement-analysis` last-writer-wins — now uses majority vote for multi-judge pairs
- **Bug fix**: `run-tournament` dedup filter included tagged modes in extract — now excludes them
- **Perf**: Convergence endpoint optimized from 10-30s → ~1s (replaced binary search with pre-computed cumulative stats)
- **Perf**: `available-modes` reduced from 2 aggregate pipelines to 1
- Rebuilt frontend with correct API URL
- Ran Opus 4.6 tournaments for elife-cancer, elife-microbiology, elife-neuro-100, midl-medical-imaging

## Pending/Backlog
- (P1) Complete fair replay of Opus 4.6 for remaining ICLR datasets (coverage 39-94%)
- (P2) Add UI visualization for gap-stratified human accuracy in A/B test section
- (P2) Complete data generation for `iclr-llms` dataset
- (P2) Add missing HTTP security headers
- (P2) Production deployment (user action required)
- (P3) Extract shared utilities (`_norm_tier`, `TIER_ORDER`, expert ratings builder)
- (P3) Split validation.py (3800+ lines) into modules (importers, tournament, analysis, experiments)
- Run full_pdf tournaments for Qeios domains
- Strip HTML tags from paper titles
- Hide 0% Expert-Expert for single-evaluator datasets
