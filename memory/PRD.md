# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Datasets & Results

### ICLR Tournaments (abs+sum vs full_pdf)
| Dataset | Papers | abs+sum ρ | full_pdf ρ | Winner |
|---|---|---|---|---|
| LLMs | 73 | 0.771 | 0.751 | abs+sum |
| Protein Science | 46 | 0.770 | 0.743 | abs+sum |
| Optimization | 42 | 0.742 | 0.716 | abs+sum |
| Code Generation | 62 | 0.685 | 0.760 | full_pdf |
| Optimal Transport | 52 | 0.528 | 0.516 | abs+sum |
| Molecules | 46 | 0.513 | 0.544 | full_pdf |
| PDEs | 80 | 0.488 | 0.459 | abs+sum |
| Fairness | 68 | 0.432 | 0.448 | full_pdf |

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

## Pending/Backlog
- Run full_pdf tournaments for Qeios domains
- Strip HTML tags from paper titles
- Hide 0% Expert-Expert for single-evaluator datasets
- Multi-model data fill, HTTP security headers, production deployment
