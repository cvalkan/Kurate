# AI Model Benchmark Lab — PRD

## Original Problem Statement
Build a comprehensive system for validating and comparing the performance of AI models on scientific papers.

## Datasets
- ICLR Protein Science (46 papers), ICLR LLMs (73), PeerRead ACL 2017 (80), Qeios, SciPost
- F1000Prime Alzheimer's (54 papers)
- **ResearchHub (994 papers)** — largest pairwise validation dataset

## Key Results: ResearchHub (2076 pairs, 994 papers)
| Metric | Abstract | Abstract + Summary |
|--------|----------|-------------------|
| **Aggregate AI vs Expert** | **67.2%** | **67.9%** |
| GPT-5.2 | 68.2% | 67.8% |
| Claude Opus 4.5 | 68.1% | 67.7% |
| Gemini 3 Pro | 65.2% | 68.0% |

### By Score Gap (Abstract + Summary)
| Gap | Agreement | N |
|-----|-----------|---|
| Small (1pt) | 63.8% | 1559 |
| Medium (2pts) | 77.4% | 420 |
| Large (3+pts) | **90.9%** | 99 |

## ResearchHub-50 (Well-Connected Subset)
- **50 papers**, single connected component, 115 discriminative human preference pairs, 24 evaluators
- Extracted from the 3-core of the largest connected component in full ResearchHub dataset
- Avg degree 5.0 in comparison graph
- **Tournament results (767 AI matches, 30.7 avg/paper)**:
  - Spearman ρ = 0.440 (p=0.001), Kendall τ = 0.285, Pearson r = 0.443
  - AI vs Expert agreement: 74.3%
  - Convergence: ρ rises from 0.22 → 0.47 (clear upward trend)

## Graph Connectivity Analysis
- **ResearchHub-100** had 12 disconnected components → flat convergence (ρ ≈ 0.2)
- **ResearchHub-50** is fully connected → meaningful convergence to ρ ≈ 0.47
- Added graph connectivity diagnostic to convergence API + frontend indicator

## Recent Changes (Feb 15, 2026)
- Created `researchhub-50` dataset: well-connected 50-paper subset via k-core decomposition
- Ran 750-match tournament (30 matches/paper) on researchhub-50
- Added graph connectivity diagnostics to `/api/validation/convergence` endpoint
- Frontend shows connectivity status (green = connected, amber = disconnected) in convergence summary
- Rebuilt frontend with correct REACT_APP_BACKEND_URL (was serving stale build)
- Previous: Expanded ResearchHub to 4 pairs/reviewer, human pairwise ground truth, score gap chart

## Key Files
- `backend/routers/validation.py` — Core validation, convergence (now with graph connectivity)
- `frontend/src/components/ConvergenceSection.jsx` — Convergence charts with connectivity indicator
- `backend/services/rh_scraper.py` — ResearchHub API scraper
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Score gap chart, per-model fix

## Pending
- P1: Resume ICLR LLMs multi-model runs
- P1: Run multimodel for ResearchHub (AI Consensus metric)
- P1: Add "View Prompts" modal to SciPost

## Backlog
- Explore eLife as complementary dataset
- Experiment with different LLMs (Gemini 3 Flash)
- Refactor data processing into services layer
- Add missing HTTP security headers
- Full security scan review
