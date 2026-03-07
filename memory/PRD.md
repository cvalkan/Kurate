# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro
- **Input format**: Abstract + AI impact assessment summary
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Recent Updates (Mar 7 2026)

### Matchmaking Improvement (Elo-Aware Opponent Selection)
- Established opponent selection now picks the paper closest to the new paper's estimated Elo (median for 0-match papers, current Elo for others) — was previously arbitrary first-found
- Top-K identification now uses regularized Elo scores instead of raw win-rate
- Post-convergence repeat logic now re-matches Elo-adjacent papers (validates ranking boundaries) instead of random least-compared pairs
- Simulation showed +3.4% ranking correlation improvement for new papers, 1 round faster to ρ≥0.8
- Simulation test file: backend/tests/sim_matchmaking.py

### GPT 5.4 Summarizer Experiment
- Added GPT 5.4 as experimental summarizer using user's own OpenAI key (Emergent key doesn't support gpt-5.4 yet)
- Results: GPT-5.4 accuracy=76.6%, tied with Opus 4.5, below Opus 4.6 Thinking (85.4%)
- Shown in separate "Experimental" table on the Accuracy by Summarizer page — main table preserved at full 1500+ pairs
- Config: OPENAI_API_KEY_GPT54 in backend/.env, SUMMARIZER_MODELS["gpt54"] in validation_experiments.py

### Pipeline Fixes (Mar 6 2026)
- Fixed summary filter lost after PDF re-fetch in run_comparison_round
- Fixed failed PDF downloads permanently excluding papers (now marks pdf_failed: True)
- Fixed run_comparison_round loading full_text unnecessarily
- PDF download cap increased from 200 to 500
- Pause now stops summary generation instantly via _summary_gen_stop flag
- Real-time summary generation progress tracking
- Admin stats caching + zero-day gap filling in charts

## Pending Tasks
- (P2) Further refactor validation.py
- (P2) Add missing HTTP security headers middleware
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict

## Key Issue: Budget Exhaustion
The Emergent LLM key budget gets exhausted during large-scale summary generation. User needs to top up via Profile → Universal Key → Add Balance.
