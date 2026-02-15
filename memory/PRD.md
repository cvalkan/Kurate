# AI Model Benchmark Lab — PRD

## Original Problem Statement
Build a comprehensive system for validating and comparing the performance of AI models on scientific papers.

## Core Features Implemented
- **Validation Hub** with Pairwise, Single-item, and Tournament sections
- **Multiple Datasets**: ICLR Protein Science, ICLR LLMs, PeerRead ACL 2017, Qeios, SciPost, **F1000Prime Alzheimer's** (NEW)
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
- `backend/services/f1000_scraper.py` — NEW: F1000Prime archive scraper + Semantic Scholar enrichment
- `frontend/src/pages/ValidationHubPage.jsx` — Sidebar navigation (key fix applied)
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Head-to-head comparison UI
- `frontend/src/components/validation/ConvergenceSection.jsx` — Convergence charts
- `backend/services/llm.py` — LLM integration

## Completed (Feb 15, 2026)
- Fixed: AI Summaries modal showing wrong dataset papers when switching (added `key` prop)
- NEW: Built F1000Prime Alzheimer's dataset scraper
  - Scraped 59 papers from archive.connect.h1.co (Alzheimer's + Opioids collections)
  - 17 overlapping evaluators, 65 derivable pairwise preferences
  - Enriched 54/59 papers with abstracts via Semantic Scholar API
  - Dataset appears in Validation hub sidebar under Pairwise and Tournament

## F1000Prime Alzheimer's Dataset Stats
- 59 papers (Nature, Science, Cell, PNAS, etc.)
- 22 unique evaluators, 17 with 2+ papers
- Rating scale: Good=1, Very Good=2, Exceptional=3
- 65 derivable pairwise preferences from evaluator overlaps
- Top evaluators: Brian Popko (5), Mark Bothwell (4), Eui-Ju Choi (4), Jairaj Acharya (4)

## Pending / In Progress
- P0: Run AI pairwise comparisons on F1000 Alzheimer's dataset (abstract mode first)
- P1: Complete multi-model runs for ICLR LLMs dataset (paused, needs user approval)
- P1: Add "View Prompts" modal to SciPost page
- P1: Implement additional datasets (eLife?)

## Backlog
- P2: Experiment with different LLMs for generating summaries (e.g., Gemini 3 Flash)
- P2: Full review of security scan report / HTTP security headers
- P3: Refactor data processing logic from routers into `backend/services` layer
