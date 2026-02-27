# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org

## Key Results

### Deep Dive 2-Pass Assessment (Feb 26-27 2026)
- **Finding**: Two-pass assessments are SUB-FIELD DEPENDENT — not universally helpful
- **ICLR Fairness**: 79.7% vs 71.8% baseline (+7.9pp, p=0.0029, McNemar's test) — SIGNIFICANT
- **ICLR Code Gen**: 73.4% vs 72.4% opus46 baseline (+1.0pp, p=0.47) — NOT significant
- **Confounding**: Original codegen result (+6.2%) was confounded with Opus 4.5→4.6 model upgrade
- **Method**: Step 1 generates assessment + focus areas JSON, Step 2 generates standalone deep-dive informed by focus areas, Step 3 replays tournament with same pairs + same judge models

### Cross-Dataset Convergence Analysis (Feb 27 2026)
- **Key finding**: GT resolution is a SAMPLE EFFICIENCY factor, not a fundamental barrier
- **Recommended headline metric**: Non-tie pairwise accuracy (not Spearman ρ)
- **All datasets distinguishable from chance** on non-tie accuracy, including MIDL (2 tiers)
- **Written to**: /app/DATASET_CONVERGENCE_ANALYSIS.md (needs revision per user's correction)

### Summarizer A/B: Opus 4.5 vs 4.6
- Opus 4.6 summaries significantly better: 73.9% vs 71.8% (p=0.0007, McNemar's on 1582 pairs)
- Consistent across most ICLR and eLife datasets

## Datasets with Deep Dive Results
- iclr-fairness: 68 papers, 871 replays, +7.9pp lift, p=0.0029
- iclr-codegen: 62 papers, 958 replays, +1.0pp lift (vs opus46), p=0.47
- iclr-pdes: 80 papers, 869 replays (partial), +0.4pp lift
- midl-medical-imaging: 81 papers, 498 replays, +1.0pp lift
- peerread_acl_2017: 80 papers, 1025 replays, +0.9pp lift
- acmi-micro-100: 100 papers, 1226 replays, -0.1pp lift
- elife-neuro-100: 100 papers, 1325 replays, -4.1pp lift

## Completed (Feb 27 2026)
- Cross-dataset convergence analysis across 12 datasets
- Identified 5 structural factors for convergence
- Ran ICLR Fairness deep dive: significant +7.9pp lift
- Added Fairness deep dive to Experiments sidebar

## Pending
- Run deep dive on remaining 5 ICLR datasets (llm, molecules, optimization, ot, protein)
- Update analysis document with corrected framing (sample efficiency vs fundamental barrier)
- Resume iclr-pdes replay (869/1785 done)
- Gap-stratified human accuracy UI
- HTTP security headers
- Refactor iclr_deep_dive.py
