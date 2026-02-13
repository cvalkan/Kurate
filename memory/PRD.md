# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts. Compare AI rankings/ratings with human expert judgments across multiple datasets and methodologies.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI (static build served via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Validation Framework (Unified Hub at /validation)

### Pairwise Comparison
- **Qeios**: Head-to-head paper pairs from same reviewer, 3 AI models, majority-vote agreement (330 pairs)
- **SciPost (Abstract + Extract)**: Per-dimension pairwise comparison (validity, significance, originality, clarity). Abstract-only mode plus PDF-extracted sections (intro/method/results/conclusion) using the tournament extraction algorithm

### Single-item Rating
- **SciPost**: AI rates individual papers on 4 dimensions (1-6 scale), compared with human referee ratings (282 comparisons). Shows close-rate, MAE, per-model and per-dimension breakdown

### Tournament Ranking
- **ICLR LLMs** (73 papers), **ICLR Protein Science** (46 papers), **PeerRead ACL 2017** (80 papers)
- Full ranking correlation (Spearman, Kendall, Pearson) between AI tournament rankings and human peer-review rankings

## Key Pages
- `/` — Leaderboard
- `/correlation` — Model Analysis
- `/methodology` — Methodology
- `/validation` — **Unified Validation Hub** with sidebar navigation
- `/admin` — Admin controls

## File Structure
```
backend/
  routers/
    scipost.py       — SciPost single-item + pairwise endpoints
    pairwise.py      — Qeios pairwise endpoints
    validation.py    — Tournament validation endpoints
    admin.py         — Admin endpoints
  services/llm.py    — Centralized LLM call helpers
  core/config.py     — Config, models, DB

frontend/src/
  pages/
    ValidationHubPage.jsx      — Unified hub with sidebar
    SciPostPairwiseSection.jsx  — SciPost pairwise per-dimension
    PairwisePage.jsx            — Qeios pairwise (embedded mode)
    SciPostPage.jsx             — SciPost single-item (embedded mode)
    ValidationPage.jsx          — Tournament DatasetView (exported)
  components/
    Navbar.jsx                  — Simplified nav (Validation link only)
  App.js                        — Routes
```

## DB Collections
- `pairwise_comparisons` — Qeios pairs
- `scipost_comparisons` — SciPost single-item ratings
- `scipost_pairwise` — SciPost per-dimension pairs (NEW)
- `scipost_pairwise_extract` — SciPost per-dimension pairs using PDF extraction (NEW)
- `validation_datasets`, `tournament_papers`, `tournament_matches` — Tournament data

## What's Been Implemented
- [x] Leaderboard, Model Analysis, Methodology pages
- [x] Tournament validation (ICLR LLM, ICLR Protein, PeerRead ACL)
- [x] Qeios pairwise comparison (optimized with async + caching)
- [x] SciPost single-item dimension analysis (with prompts modal, referee column, tooltips)
- [x] SciPost pairwise per-dimension comparison (backend + frontend working, verified Feb 2026)
- [x] Unified Validation Hub with sidebar navigation
- [x] Removed old /pairwise and /scipost routes
- [x] Centralized LLM utilities (llm.py)
- [x] Admin controls with progress feedback
- [x] Fixed SciPost Pairwise KeyError bug (escaped curly braces in prompt template, Feb 13 2026)
- [x] Added separate SciPost Pairwise modes: Abstract and Extract (PDF download + section extraction)
- [x] Added “Performance by Model” chart to SciPost Pairwise results
- [x] Added “Agreement by Score Gap” charts for SciPost Pairwise (Abstract + Extract)
- [x] Synced SciPost Pairwise Abstract + Extract runs to use identical paper pairs (paired once, evaluated twice)

## Backlog
- [ ] (P1) Add "View Prompts" modal to Qeios Pairwise page (feature parity with SciPost)
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) HTTP security headers for production
- [ ] (P2) Regenerate old AI impact summaries with model badge
- [ ] (P2) Experiment with Gemini 3 Flash for comparisons
- [ ] (P2) Full security scan review
- [ ] (P3) Refactor data importers into backend/services/importers/
- [ ] (P3) Break down pairwise.py (500+ lines) into smaller modules
