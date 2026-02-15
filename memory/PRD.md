# AI Model Benchmark Lab — PRD

## Original Problem Statement
Build a comprehensive system for validating and comparing the performance of AI models on scientific papers.

## Core Features
- **Validation Hub** with Pairwise, Single-item, and Tournament sections
- **Datasets**: ICLR Protein Science, ICLR LLMs, PeerRead ACL 2017, Qeios, SciPost, F1000Prime Alzheimer's, **ResearchHub**
- **Content Modes**: Abstract, Extract, Full PDF, AI Summary, Abstract + Summary
- **AI Summary Feature**: LLM-generated impact assessments
- **Convergence Analysis**: Rank correlation and top-k overlap charts

## Key Files
- `backend/routers/validation.py` — Core validation, F1000/RH endpoints
- `backend/services/f1000_scraper.py` — F1000Prime scraper
- `backend/services/f1000_rescrape.py` — F1000 multi-evaluator fix
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Pairwise comparison UI

## ResearchHub Dataset (NEW — Feb 15, 2026)
- **168 discriminative pairwise preferences** from 168 independent reviewers (1 random pair per reviewer)
- **325 unique papers**, 315 with abstracts, 312 with AI summaries
- **1-5 review scale** (score distribution: 1=12, 2=33, 3=121, 4=136, 5=34)
- Source: ResearchHub leaderboard API + contributions API

### ResearchHub Pairwise Results (162 common pairs)
| Model | Abstract | Abstract + Summary |
|-------|----------|-------------------|
| GPT-5.2 | **69.6%** | **71.4%** |
| Claude Opus 4.5 | 60.4% | 69.8% |
| Gemini 3 Pro | 66.0% | 62.3% |
| **Aggregate** | **65.4%** | **67.9%** |

- AI Pick Consistency across modes: **88.9%**
- Abstract+Summary improves overall by +2.5% (65.4→67.9)
- Claude Opus benefits most from summaries (+9.4%), Gemini degrades (-3.7%)

## Pending
- P1: Resume ICLR LLMs multi-model runs
- P1: Add "View Prompts" modal to SciPost

## Backlog
- Run multimodel evaluation for ResearchHub (AI Consensus metric)
- Expand F1000 dataset (currently IP-blocked)
- Explore eLife as complementary dataset
- Refactor data processing into services layer
