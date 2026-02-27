# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Key Results

### Deep Dive 2-Pass Assessment — CORRECTED (Feb 27 2026)
- **CRITICAL FIX**: `compute_analysis()` was comparing deep dive against Opus 4.5 baseline instead of Opus 4.6 (the actual replayed baseline). This inflated all deep dive results.
- **Corrected finding**: The 2-pass methodology adds NOTHING measurable over Opus 4.6 single-pass
- **Molecules**: 89.9% vs 89.9% = 0.0pp lift (p=0.80)
- **Fairness**: 78.2% vs 79.7% = +1.5pp (p=0.62, NOT significant)
- **Codegen**: 72.4% vs 73.4% = +1.0pp (p=0.47, NOT significant)

### Summarizer A/B: Opus 4.5 vs 4.6
- Opus 4.6 summaries significantly better: 73.9% vs 71.8% (p=0.0007, McNemar's on 1582 pairs)
- This is the REAL finding — the model upgrade matters, not the 2-pass approach

### Cross-Dataset Convergence Analysis (Feb 27 2026)
- GT resolution is a SAMPLE EFFICIENCY factor, not a fundamental barrier
- Recommended headline metric: Non-tie pairwise accuracy (not Spearman rho)
- All datasets distinguishable from chance on non-tie accuracy
- Detailed analysis: /app/DATASET_CONVERGENCE_ANALYSIS.md

## Same-Tier Match Waste
- All tournaments include same-tier pairs that can't be evaluated against GT
- MIDL: ~60% ties, molecules: ~53%, pdes: ~46%, fairness: ~44%
- Deep dive replays alone: ~2,139 wasted LLM calls

## Completed (Feb 27 2026)
- Fixed compute_analysis baseline comparison bug
- Added convergence cache invalidation to deep dive pipeline
- Updated all UI labels to say "non-tie pairs"
- Added methodology notes explaining tie exclusion
- Fixed "flipped numbers don't add up" UI (shows tie-pair flips separately)
- Cross-dataset convergence analysis across 12 datasets
- Ran deep dive on fairness and molecules (null result after baseline correction)

## Pending
- Filter tournaments to exclude same-tier pairs (30-60% LLM savings)
- Update DATASET_CONVERGENCE_ANALYSIS.md with corrected deep dive findings
- Gap-stratified human accuracy UI
- HTTP security headers
- Refactor iclr_deep_dive.py
