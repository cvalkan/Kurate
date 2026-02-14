# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts. Compare AI rankings/ratings with human expert judgments across multiple datasets and methodologies.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI (static build served via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Validation Framework (Unified Hub at /validation)

### Pairwise Comparison
- **Qeios**: Head-to-head paper pairs from same reviewer, 3 AI models, majority-vote agreement. Internal Abstract/Extract toggle.
- **SciPost**: Per-dimension pairwise comparison (validity, significance, originality, clarity). Internal Abstract/Extract toggle.
- **ICLR Protein Science**: Cross-mode head-to-head agreement analysis with bar charts (recharts). Uses `/api/validation/cross-mode-agreement` endpoint.
- **PeerRead ACL 2017**: Cross-mode head-to-head agreement analysis with bar charts. Same endpoint.

### Single-item Rating
- **SciPost**: AI rates individual papers on 4 dimensions (1-6 scale)

### Tournament Ranking
- **ICLR LLMs** (73 papers), **ICLR Protein Science** (46 papers), **PeerRead ACL 2017** (80 papers)
- Full ranking correlation (Spearman, Kendall, Pearson) between AI tournament rankings and human peer-review rankings
- **3 content modes**: Extract, Abstract, Full PDF
- **Multi-Model Analysis**: Inter-model agreement, rank correlation, and majority vote vs expert
- Non-comparable note on agreement stats (different match sets per mode)

## Key Pages
- `/` — Leaderboard
- `/correlation` — Model Analysis
- `/methodology` — Methodology
- `/validation` — **Unified Validation Hub** with sidebar navigation
- `/admin` — Admin controls

## Sidebar Structure
```
PAIRWISE
  Qeios (Abstract/Extract toggle)
  SciPost (Abstract/Extract toggle)
  ICLR Protein Science (head-to-head charts)
  PeerRead ACL 2017 (head-to-head charts)
SINGLE-ITEM
  SciPost
TOURNAMENT
  ICLR LLMs
  ICLR Protein Science
  PeerRead ACL 2017
```

## DB Collections
- `validation_datasets`, `validation_papers`, `validation_matches` — Tournament data
  - `validation_matches` has `content_mode` field: "abstract", "extract", or "full_pdf"
  - `abstract_only` field for backward compat with older matches

## What's Been Implemented
- [x] Leaderboard, Model Analysis, Methodology pages
- [x] Tournament validation (ICLR LLM, ICLR Protein, PeerRead ACL)
- [x] Qeios pairwise comparison with internal Abstract/Extract toggle
- [x] SciPost pairwise and single-item per-dimension with internal Abstract/Extract toggle
- [x] Unified Validation Hub with restructured sidebar
- [x] Centralized LLM utilities (llm.py) with 100-thread pool
- [x] 3-way content mode toggle (Extract / Abstract / Full PDF) on Ranking Correlation
- [x] Content mode toggle on Multi-Model Analysis
- [x] Full PDF tournament mode for ICLR Protein Science
- [x] Multi-model fills for all datasets/modes
- [x] "View Prompts" modal on Qeios page
- [x] Cross-mode head-to-head moved to Pairwise section (ICLR Protein, PeerRead)
- [x] Bar charts (recharts) on all Pairwise items
- [x] Non-comparable note on Tournament agreement stats
- [x] Renamed "Extract (Full Text)" to "Extract" throughout
- [x] Removed coincidence note
- [x] Fixed duplicate $ne key bug in tournament status endpoint
- [x] Added mode_disagreements to cross-mode-agreement API response

## Multi-Model Data Status
| Dataset | Extract | Abstract | Full PDF |
|---------|---------|----------|----------|
| ICLR Protein | 499 pairs | 497 pairs | 446 pairs |
| ICLR LLMs | 494 pairs | 500 pairs | — |
| PeerRead ACL | 499 pairs | 500 pairs | — |

## Backlog
- [ ] (P1) Add "View Prompts" modal to SciPost page
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Run Full PDF tournaments for ICLR LLMs and PeerRead ACL
- [ ] (P2) HTTP security headers for production
- [ ] (P2) Experiment with Gemini 3 Flash
- [ ] (P3) Refactor business logic into backend/services layer

## Changelog
- **Feb 14, 2026 (session 4)**: Major Validation page restructure. Merged Qeios Abstract/Extract into single item with internal toggle. Same for SciPost. Moved head-to-head comparisons to new Pairwise items (ICLR Protein, PeerRead) with recharts bar charts. Added non-comparable note to Tournament. Renamed "Extract (Full Text)" to "Extract". Removed coincidence note. Fixed duplicate $ne bug. Added mode_disagreements to API.
- **Feb 14, 2026 (session 3b)**: Updated `run-multimodel` endpoint to support `content_mode` parameter. Generated multi-model data for all available dataset/mode combinations.
- **Feb 14, 2026 (session 3a)**: Added 3-way content mode toggle (Extract/Abstract/Full PDF) to Ranking Correlation and Multi-Model Analysis. Implemented Full PDF mode in `compare_papers()`. Ran Full PDF tournament for ICLR Protein Science.
- **Feb 14, 2026 (session 2)**: Qeios synced pairwise, parallel evaluation (40x+ speedup), abstract-only tournaments.
