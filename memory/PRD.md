# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts. Compare AI rankings/ratings with human expert judgments across multiple datasets and methodologies.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI + Recharts (static build via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Input Formats
1. **Abstract**: Paper abstract only (~200 words)
2. **Extract**: Section-extracted text (intro, methods, results, conclusion ~8k chars)
3. **Full PDF**: Complete paper text (~40k chars)
4. **AI Summary**: Claude Opus 4.5 generates ~850-word impact assessment from full PDF, then used as input for pairwise comparison

## AI Summary Pipeline
- **Step 1**: Feed full PDF to Claude Opus 4.5 with impact assessment prompt
- **Prompt criteria**: Core contribution, methodological rigor, potential impact, timeliness, strengths/limitations + anything else model deems important
- **Step 2**: Store ~850-word summary on paper document (`ai_impact_summary`)
- **Step 3**: Use summaries as input for standard pairwise tournament (all 3 models)

## Cross-Mode Pairwise Results — ICLR Protein Science (862 pairs)
| Input Format | AI vs Expert | AI vs Majority | AI Consensus vs Majority |
|---|---|---|---|
| Abstract | 68.6% | 68.0% | 71.0% |
| Extract | 76.5% | 75.3% | 74.9% |
| Full PDF | 78.5% | 78.1% | 76.3% |
| **AI Summary** | **77.7%** | **78.2%** | — |
| Expert-Expert | 86.0% | — | — |

**Key finding**: AI Summary (~850 words) matches Full PDF performance (40k chars) while being ~50x more compact.

## Key API Endpoints
- `POST /api/validation/generate-impact-summaries` — Generate AI impact assessments for papers
- `GET /api/validation/impact-summary-status` — Check summary generation progress
- `POST /api/validation/run-targeted-pairwise` — Run evaluations for expert-majority pairs
- `GET /api/validation/cross-mode-agreement` — Cross-mode agreement analysis

## Backlog
- [ ] (P1) Run AI Summary on PeerRead ACL 2017 for comparison
- [ ] (P1) Add "View Prompts" modal to SciPost page
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Run targeted pairwise for ICLR LLMs
- [ ] (P2) Test AI Summary with different summary-generating models
- [ ] (P2) HTTP security headers
- [ ] (P3) Refactor backend services layer

## Changelog
- **Feb 14, 2026 (session 7)**: Introduced "AI Summary" input format. Built summary generation pipeline (Claude Opus 4.5, ~850 words). Generated summaries for all 46 ICLR Protein papers. Ran 877 targeted pairwise evaluations. Result: AI Summary matches Full PDF performance (78.2% vs 78.1% AI-Majority) while being 50x more compact.
- **Feb 14, 2026 (session 6)**: Per-model charts, AI consensus baseline, Abstract→Extract→Full PDF ordering.
- **Feb 14, 2026 (session 5)**: Side-by-side Qeios/SciPost, targeted pairwise endpoint, ran evaluations.
- **Feb 14, 2026 (session 4)**: Validation page restructure.
