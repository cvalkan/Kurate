# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts. Compare AI rankings/ratings with human expert judgments across multiple datasets and methodologies.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI (static build served via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Validation Framework (Unified Hub at /validation)

### Pairwise Comparison
- **Qeios**: Head-to-head paper pairs, 3 AI models. Abstract & Extract shown side-by-side with horizontal CSS progress bars.
- **SciPost**: Per-dimension pairwise (validity, significance, originality, clarity). Abstract & Extract side-by-side.
- **ICLR Protein Science**: Cross-mode agreement analysis — 879 common pairs across Extract, Abstract, Full PDF. Bar charts + detailed table.
- **PeerRead ACL 2017**: Cross-mode agreement — 1323 common pairs across all 3 input formats.

### Single-item Rating
- **SciPost**: AI rates individual papers on 4 dimensions (1-6 scale)

### Tournament Ranking
- **ICLR LLMs** (73 papers), **ICLR Protein Science** (46 papers), **PeerRead ACL 2017** (80 papers)
- Full ranking correlation (Spearman, Kendall, Pearson)
- 3 content modes: Extract, Abstract, Full PDF
- Multi-Model Analysis
- Non-comparable note on agreement stats

## Sidebar Structure
```
PAIRWISE
  Qeios (Abstract + Extract side-by-side)
  SciPost (Abstract + Extract side-by-side)
  ICLR Protein Science (cross-mode charts)
  PeerRead ACL 2017 (cross-mode charts)
SINGLE-ITEM
  SciPost
TOURNAMENT
  ICLR LLMs
  ICLR Protein Science
  PeerRead ACL 2017
```

## Key API Endpoints
- `POST /api/validation/run-targeted-pairwise` — Run evaluations for expert-majority pairs missing in a given content mode
- `GET /api/validation/cross-mode-agreement` — Agreement stats on shared pairs across all content modes
- `POST /api/validation/run-tournament` — Run random tournament matches
- `GET /api/validation/pairwise-results`, `irt-results`, `agreement-analysis` — Per-mode ranking data

## What's Been Implemented
- [x] Leaderboard, Model Analysis, Methodology pages
- [x] Tournament validation (ICLR LLM, ICLR Protein, PeerRead ACL)
- [x] Qeios pairwise — Abstract & Extract side-by-side with CSS bars
- [x] SciPost pairwise — Abstract & Extract side-by-side with CSS bars
- [x] ICLR Protein pairwise — 879 pairs, 3 input formats, bar charts
- [x] PeerRead pairwise — 1323 pairs, 3 input formats, bar charts
- [x] Targeted pairwise endpoint for expert-majority pairs
- [x] Unified Validation Hub with restructured sidebar
- [x] Non-comparable note on Tournament agreement stats
- [x] Neutral wording (no "apples-to-apples")
- [x] "Extract" naming (not "Extract (Full Text)")

## Cross-Mode Pairwise Results
### ICLR Protein Science (879 pairs)
| Input Format | AI vs Expert | AI vs Majority |
|---|---|---|
| Full PDF | **78.2%** | **78.1%** |
| Extract | 76.3% | 75.3% |
| Abstract | 68.5% | 68.0% |
| Expert-Expert | 85.5% | — |

### PeerRead ACL 2017 (1323 pairs)
| Input Format | AI vs Expert | AI vs Majority |
|---|---|---|
| Extract | **75.1%** | **75.1%** |
| Full PDF | 74.6% | 74.5% |
| Abstract | 73.8% | 74.0% |
| Expert-Expert | 94.1% | — |

## Backlog
- [ ] (P1) Add "View Prompts" modal to SciPost page
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Run Full PDF tournaments for ICLR LLMs
- [ ] (P2) HTTP security headers for production
- [ ] (P2) Experiment with Gemini 3 Flash
- [ ] (P3) Refactor business logic into backend/services layer

## Changelog
- **Feb 14, 2026 (session 5)**: Qeios/SciPost now show Abstract & Extract side-by-side with horizontal CSS bars (no toggle). ICLR/PeerRead pairwise uses neutral wording ("AI vs Expert/Majority"). Created `run-targeted-pairwise` endpoint. Ran targeted evaluations for all expert-majority pairs: ICLR Protein (879 common pairs, 3 modes), PeerRead (1323 pairs, 3 modes).
- **Feb 14, 2026 (session 4)**: Major Validation page restructure. Merged sidebar items. Moved head-to-head to Pairwise. Added non-comparable note. Renamed "Extract (Full Text)" to "Extract".
- **Feb 14, 2026 (session 3)**: 3-way content mode toggle, Full PDF mode, multi-model data generation.
- **Feb 14, 2026 (session 2)**: Qeios synced pairwise, parallel evaluation (40x+ speedup).
