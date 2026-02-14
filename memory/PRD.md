# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts. Compare AI rankings/ratings with human expert judgments across multiple datasets and methodologies.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI + Recharts (static build served via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Validation Framework (Unified Hub at /validation)

### Pairwise Comparison
- **Qeios**: Abstract & Extract side-by-side, horizontal CSS progress bars
- **SciPost**: Per-dimension pairwise, Abstract & Extract side-by-side
- **ICLR Protein Science**: 879 pairs, 3 input formats, per-model + AI consensus charts
- **PeerRead ACL 2017**: 1323 pairs, 3 input formats, per-model + AI consensus charts

### Single-item Rating
- **SciPost**: AI rates individual papers on 4 dimensions (1-6 scale)

### Tournament Ranking
- 3 datasets, 3 content modes (Abstract, Extract, Full PDF)
- Agreement cards: Expert-Expert, AI vs Expert, AI vs Expert Majority
- Non-comparable note directing users to Pairwise section

## Ordering Convention
**Everywhere**: Abstract → Extract → Full PDF (fewer to richer data)

## Key Metrics
- **AI vs Expert**: Individual AI model vs individual human reviewer
- **AI vs Expert Majority**: Individual AI model vs human majority vote
- **AI Consensus vs Expert Majority**: 3-model majority vote vs human majority (new)
- **Per-Model**: GPT-5.2, Claude Opus, Gemini 3 Pro individual rates
- **Expert-Expert**: Human reviewer agreement (baseline)

## Cross-Mode Pairwise Results
### ICLR Protein Science (879 pairs)
| Input Format | AI vs Expert | AI vs Majority | AI Consensus vs Majority |
|---|---|---|---|
| Abstract | 68.5% | 68.0% | 71.0% |
| Extract | 76.3% | 75.3% | 74.9% |
| Full PDF | **78.2%** | **78.1%** | **76.3%** |
| Expert-Expert | 85.5% | — | — |

### PeerRead ACL 2017 (1323 pairs)
| Input Format | AI vs Expert | AI vs Majority | AI Consensus vs Majority |
|---|---|---|---|
| Abstract | 73.8% | 74.0% | TBD |
| Extract | **75.1%** | **75.1%** | TBD |
| Full PDF | 74.6% | 74.5% | TBD |
| Expert-Expert | 94.1% | — | — |

## Backlog
- [ ] (P1) Add "View Prompts" modal to SciPost page
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Run targeted pairwise for ICLR LLMs
- [ ] (P2) HTTP security headers
- [ ] (P2) Experiment with Gemini 3 Flash
- [ ] (P3) Refactor business logic into backend/services layer

## Changelog
- **Feb 14, 2026 (session 6)**: Added per-model bar charts (GPT-5.2, Claude Opus, Gemini 3 Pro) to ICLR/PeerRead pairwise. Added "AI Consensus vs Majority" (3-model vote) to existing charts. Reordered all toggles/charts/tables to Abstract → Extract → Full PDF. Updated Tournament agreement cards labeling.
- **Feb 14, 2026 (session 5)**: Qeios/SciPost side-by-side with CSS bars. ICLR/PeerRead neutral wording. Targeted pairwise endpoint. Ran evaluations: ICLR Protein (879 pairs), PeerRead (1323 pairs).
- **Feb 14, 2026 (session 4)**: Validation page restructure. Merged sidebar items. Head-to-head moved to Pairwise.
- **Feb 14, 2026 (session 3)**: 3-way content mode toggle, Full PDF mode, multi-model data.
