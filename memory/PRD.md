# AI Model Benchmark Lab — PRD

## Original Problem Statement
Build a comprehensive system for validating and comparing the performance of AI models on scientific papers.

## Core Features Implemented
- **Validation Hub** with Pairwise, Single-item, and Tournament sections
- **Multiple Datasets**: ICLR Protein Science, ICLR LLMs, PeerRead ACL 2017, Qeios, SciPost, **F1000Prime Alzheimer's**
- **Content Modes**: Abstract, Extract, Full PDF, AI Summary, Abstract + Summary
- **AI Summary Feature**: LLM-generated impact assessments for papers
- **Convergence Analysis**: Rank correlation and top-k overlap charts
- **AI Summary Viewer**: Modal to inspect generated summaries per paper
- **F1000Prime Scraper**: Automated data collection from F1000Prime archive

## Architecture
- Frontend: React + Shadcn/UI + Recharts
- Backend: FastAPI + MongoDB
- LLMs: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent integrations)

## Key Files
- `backend/routers/validation.py` — Core validation logic, endpoints, F1000 scraper endpoints
- `backend/services/f1000_scraper.py` — F1000Prime archive scraper + Semantic Scholar enrichment + dataset expansion
- `backend/services/f1000_rescrape.py` — Re-scrape multi-evaluator articles for complete evaluation data
- `frontend/src/pages/ValidationHubPage.jsx` — Sidebar navigation (key prop fix)
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Head-to-head comparison UI (per-model fallback fix)
- `frontend/src/components/validation/ConvergenceSection.jsx` — Convergence charts
- `backend/services/llm.py` — LLM integration

## Completed (Feb 15, 2026)
- Fixed: AI Summaries modal showing wrong dataset papers when switching (added `key` prop)
- Built F1000Prime Alzheimer's dataset:
  - Scraped 54 papers from archive.connect.h1.co (Alzheimer's + Opioids collections)
  - Re-scraped multi-evaluator articles: 114 total evaluations (up from 54), 59 unique evaluators
  - 23 multi-paper evaluators, 49 discriminative + 67 tie = 116 pairwise preferences
  - Enriched 53/54 with abstracts (PubMed + Semantic Scholar), 14 with full PDF text
  - Generated 52/54 AI impact summaries (Claude Opus 4.5)
  - Ran Abstract and Abstract+Summary pairwise comparisons (35 expert-preference pairs)
  - Ran multimodel evaluation (GPT-5.2, Claude Opus 4.5, Gemini 3 Pro)
- Fixed per-model chart to show "AI vs Expert" for single-evaluator datasets
- Modified targeted pairwise run to support single-evaluator preferences

## F1000Prime Alzheimer's Results
- **Abstract mode**: 71.4% AI vs Expert (25/35)
  - GPT-5.2: 74.3% | Claude Opus: 71.4% | Gemini 3 Pro: 71.4%
- **Abstract + Summary mode**: 68.6% AI vs Expert (24/35)
  - GPT-5.2: 77.1% | Claude Opus: 62.9% | Gemini 3 Pro: 71.4%
- **AI Pick Consistency**: 80% (28/35 same across modes)
- Key finding: GPT-5.2 benefits from summaries (+3%), Claude degrades (-8.5%)

## Pending / In Progress
- P1: Complete multi-model runs for ICLR LLMs dataset (paused)
- P1: Add "View Prompts" modal to SciPost page

## Backlog
- P2: Expand F1000 dataset further (more collections, evaluator graph crawl)
- P2: Run Extract/Full PDF modes for F1000 (14 papers have full text)
- P2: Explore eLife as complementary dataset
- P2: Experiment with different LLMs for generating summaries
- P3: Refactor data processing logic from routers into services layer
