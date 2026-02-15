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

## Recent Changes (Feb 15, 2026)
- Expanded ResearchHub to 4 pairs/reviewer (742 pairs from 168 reviewers)
- Changed convergence analysis to use human pairwise ground truth (not internal consistency)
- Added "AI Agreement by Expert Score Gap" chart
- Fixed per-model chart fallback for single-evaluator datasets

## Key Files
- `backend/routers/validation.py` — Core validation, convergence (now human ground truth)
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Score gap chart, per-model fix

## Pending
- P1: Resume ICLR LLMs multi-model runs
- P1: Run multimodel for ResearchHub (AI Consensus metric)

## Backlog
- Add "View Prompts" modal to SciPost
- Explore eLife as complementary dataset
- Refactor data processing into services layer
