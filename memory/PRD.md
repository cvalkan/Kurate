# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a system to validate AI's paper comparison capabilities against human peer review experts.

## Core Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React + Shadcn/UI + Recharts (static build via `npx serve`)
- **LLMs**: GPT-5.2, Claude Opus 4.5, Gemini 3 Pro (via Emergent LLM key)

## Input Formats (ordered: fewer → richer data)
1. **Abstract**: Paper abstract only (~200 words)
2. **Extract**: Section-extracted text (~8k chars)
3. **Full PDF**: Complete paper text (~40k chars)
4. **AI Summary**: Claude Opus 4.5 generates ~850-word impact assessment from full PDF

## Cross-Mode Results — ICLR Protein Science (862 common pairs)
| Input Format | AI vs Expert | AI vs Majority | AI Consensus vs Majority |
|---|---|---|---|
| Abstract | 68.6% | 68.0% | 71.0% |
| Extract | 76.5% | 75.3% | 74.9% |
| Full PDF | 78.5% | 78.1% | 76.3% |
| **AI Summary** | 77.0% | 76.9% | **79.4%** |
| Expert-Expert | 86.0% | — | — |

**Key finding**: AI Summary achieves the highest AI Consensus vs Majority (79.4%) while being ~50x more compact than Full PDF.

## Backlog
- [ ] (P1) Run AI Summary on PeerRead ACL 2017
- [ ] (P1) "View Prompts" modal for SciPost
- [ ] (P1) F1000Prime dataset integration
- [ ] (P2) Test AI Summary with different generating models
- [ ] (P2) Run targeted pairwise for ICLR LLMs
- [ ] (P2) HTTP security headers
- [ ] (P3) Refactor backend services

## Changelog
- **Feb 14, 2026 (session 8)**: Added AI Summary to Tournament toggle (visible when data exists). Ran multimodel for ai_summary (1754 matches). AI Consensus filled in at 79.4%. Refactored StandardStats and MultiModelStats to support dynamic modes.
- **Feb 14, 2026 (session 7)**: AI Summary pipeline. Generated summaries for 46 ICLR Protein papers. Ran 877 pairwise evaluations.
- **Feb 14, 2026 (session 6)**: Per-model charts, AI consensus, Abstract→Extract→Full PDF ordering.
- **Feb 14, 2026 (session 5)**: Side-by-side Qeios/SciPost, targeted pairwise, ran evaluations.
