# PaperSumo — Scientific Paper Ranking Validation System

## Problem Statement
Build a robust system for validating AI model performance on scientific papers. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.5/4.6, Gemini 3 Pro (via Emergent LLM key)

## Datasets & Results

### ICLR — Opus 4.5 vs 4.6 (Controlled A/B)
| Dataset | 4.5 ρ | 4.6 ρ | Winner |
|---|---|---|---|
| Code Gen | 0.685 | **0.690** | 4.6 |
| Fairness | 0.432 | **0.562** | 4.6 |
| LLMs | **0.771** | 0.746 | 4.5 |
| Molecules | 0.513 | **0.637** | 4.6 |
| Optimization | **0.742** | 0.738 | ~tie |
| Optimal Transport | 0.528 | **0.690** | 4.6 |
| PDEs | 0.488 | **0.552** | 4.6 |
| Protein | 0.770 | **0.785** | 4.6 |

### eLife — Opus 4.5 vs 4.6
| Dataset | 4.5 ρ | 4.6 ρ |
|---|---|---|
| Microbiology | 0.394 | **0.472** |
| Cancer | **0.269** | 0.253 |
| Neuroscience | **0.398** | 0.394 |

### MIDL Medical Imaging
| 4.5 ρ=0.270 | 4.6 ρ=**0.314** |

## Completed (Feb 22 2026)
### Data Fixes
- Opus 4.6 `winner_id` backfill (7,688 matches)
- `judge_key` → `judge_model` bug fix in replay code
- Extract filter excluding tagged modes (`$not: {$regex: ":"}`)

### Bug Fixes (Phase 1)
- `cross-mode-agreement` now dynamically discovers all modes
- `agreement-analysis` uses majority vote for multi-judge pairs
- `run-tournament` dedup filter excludes tagged modes

### Performance (Phase 2)
- Convergence: 10-30s → ~1s (bisect pre-compute replaces binary search)
- Server-side result cache (5min TTL, match-count invalidation)
- Startup cache pre-warming for top 8 datasets
- `available-modes` single aggregate pass
- Frontend: smart default tab (selects mode with most data)
- Convergence chart: disabled animations, O(1) data lookups

### Cleanup (Phase 3)
- Extracted `validation_utils.py`: shared TIER_ORDER, norm_tier, expert ratings builders, content mode filter, safe_round, interp, cache layer
- Removed 4x duplicated `_norm_tier`/`TIER_ORDER`, 2x `_safe_round`, 2x `_build_content_mode_filter`

## Pending/Backlog
- (P1) Complete remaining Opus 4.6 ICLR replays (coverage 39-94%)
- (P2) Gap-stratified human accuracy UI in A/B test section
- (P2) HTTP security headers
- (P2) Production deployment (user action required)
- (P3) Further split validation.py into importers/analysis/experiments modules
- Run full_pdf tournaments for Qeios domains
