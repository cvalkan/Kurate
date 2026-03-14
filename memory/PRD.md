# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `npx serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org
- **Preview**: llm-ranker.preview.emergentagent.com

## IMPORTANT: Frontend Build Process
Frontend is served as a pre-built static site. Any changes to .jsx files require:
1. `cd /app/frontend && yarn build`
2. `sudo supervisorctl restart frontend`
Hot-reloading is NOT sufficient.

## Current State (Mar 14 2026)
- 2174 papers, 64731 matches, 10 active categories
- 25 validation datasets, validation experiments publicly accessible
- Human vs AI Benchmark: pairwise concordance-based inter-rater reliability with:
  - Human-Human concordance (72.0%) and AI-Human concordance (73.6%)
  - Thurstonian ceiling (68.4%) from Kruskal-derived rho (0.62)
  - Tie Impact Analysis: 3 scenarios (excluded/coin-flip/disagreement)
  - Committee and individual BT ranking correlations
  - Difficulty stratification (cross-tier/adjacent/within-tier)
  - 9 controlled datasets, 5,766 paper pairs, 42.3% tie fraction

## Pending Tasks
- (P0) Phase 3: Notification System via Resend integration
- (P1) Synthetic Unfurl Test Suite for social media card rendering
- (P2) Consolidate fragile MIDL experiment pipeline
- (P2) Explore adding new validation datasets from OpenReview (ICLR 2024 CV)
- (P2) Continue refactoring monolithic leaderboard.py
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict

## Known Issues
- Mobile Twitter/X unfurling fails — blocked on user's Cloudflare configuration

## Completed Work
- Pairwise concordance-derived rho + tie impact analysis (Mar 14 2026)
  - Replaced score-based Spearman with direct pairwise concordance
  - Added AI-Human concordance (73.6%) alongside Human-Human (72.0%)
  - Added Tie Impact Analysis section (3 scenarios × H-H and AI-H)
  - Merged agreement + difficulty tables, clarified BT title
  - Key finding: under coin-flip tie handling, H-H/AI-H gap nearly vanishes (68.5% vs 69.3%)
- All prior work (see CHANGELOG.md for full history)
