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
- **SciPost (Abstract + Extract)**: Per-dimension pairwise comparison (validity, significance, originality, clarity). Abstract-only mode plus PDF-extracted sections

### Single-item Rating
- **SciPost**: AI rates individual papers on 4 dimensions (1-6 scale), compared with human referee ratings

### Tournament Ranking
- **ICLR LLMs** (73 papers), **ICLR Protein Science** (46 papers), **PeerRead ACL 2017** (80 papers)
- Full ranking correlation (Spearman, Kendall, Pearson) between AI tournament rankings and human peer-review rankings
- **3 content modes**: Extract (section extraction), Abstract Only, Full PDF (complete paper text)

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
    pairwise.py      — Qeios pairwise endpoints (legacy)
    qeios.py         — Qeios synced pairwise (abstract vs extract)
    validation.py    — Tournament validation endpoints (supports content_mode: abstract/extract/full_pdf)
    admin.py         — Admin endpoints
  services/llm.py    — Centralized LLM call helpers (100-thread pool), supports content_mode param
  core/config.py     — Config, models, DB

frontend/src/
  pages/
    ValidationHubPage.jsx       — Unified hub with sidebar
    QeiosPairwiseSection.jsx    — Qeios pairwise abstract/extract
    SciPostPairwiseSection.jsx  — SciPost pairwise per-dimension
    PairwisePage.jsx            — Qeios pairwise legacy (embedded mode)
    SciPostPage.jsx             — SciPost single-item (embedded mode)
    ValidationPage.jsx          — Tournament DatasetView with 3-way content mode toggle
  components/
    Navbar.jsx                  — Simplified nav
  App.js                        — Routes
```

## DB Collections
- `pairwise_comparisons` — Qeios pairs (legacy)
- `qeios_pairwise_abstract` — Qeios synced abstract-only pairs
- `qeios_pairwise_extract` — Qeios synced full-text pairs
- `scipost_comparisons` — SciPost single-item ratings
- `scipost_pairwise` — SciPost per-dimension pairs (abstract)
- `scipost_pairwise_extract` — SciPost per-dimension pairs (extract)
- `validation_datasets`, `validation_papers`, `validation_matches` — Tournament data
  - `validation_matches` has `content_mode` field: "abstract", "extract", or "full_pdf"

## What's Been Implemented
- [x] Leaderboard, Model Analysis, Methodology pages
- [x] Tournament validation (ICLR LLM, ICLR Protein, PeerRead ACL)
- [x] Qeios pairwise comparison (optimized with async + caching)
- [x] SciPost single-item dimension analysis
- [x] SciPost pairwise per-dimension comparison
- [x] Unified Validation Hub with sidebar navigation
- [x] Centralized LLM utilities (llm.py) with 100-thread pool
- [x] Admin controls with progress feedback
- [x] Synced SciPost & Qeios Pairwise Abstract + Extract runs
- [x] Parallel evaluation with configurable agents — 40x+ speedup
- [x] Tournament abstract-only mode
- [x] **3-way content mode toggle** (Extract / Abstract / Full PDF) on Ranking Correlation tab
- [x] **Content mode toggle on Multi-Model Analysis** tab
- [x] **Full PDF tournament mode** — sends complete paper text to LLMs instead of extracted sections
- [x] **Ran Full PDF tournament for ICLR Protein Science** (485/500 matches completed)
- [x] "View Prompts" modal on Qeios page

## Backlog
- [ ] (P1) Add "View Prompts" modal to SciPost page (feature parity with Qeios)
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Run Full PDF tournaments for ICLR LLMs and PeerRead ACL
- [ ] (P2) HTTP security headers for production
- [ ] (P2) Experiment with Gemini 3 Flash for comparisons
- [ ] (P3) Refactor business logic into backend/services layer

## Changelog
- **Feb 14, 2026 (session 3)**: Added 3-way content mode toggle (Extract/Abstract/Full PDF) to both Ranking Correlation and Multi-Model Analysis tabs. Implemented Full PDF mode in `compare_papers()` — sends complete paper text (up to 40k chars) to LLMs. Added `content_mode` field to match documents for backward-compatible filtering. Ran 500-match Full PDF tournament for ICLR Protein Science. Results: Full PDF achieves highest correlation with human rankings (Spearman ρ=0.696 vs Extract 0.608 vs Abstract 0.627).
- **Feb 14, 2026 (session 2)**: Implemented Qeios synced pairwise, parallel evaluation (40x+ speedup), abstract-only tournaments, "View Prompts" for Qeios.
- **Feb 13, 2026**: Added synced Abstract + Extract runs, additive data with dedup, gap charts, PDF extraction pipeline.
