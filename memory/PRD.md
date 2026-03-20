# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build a benchmark comparing LLM judges to human experts for scientific paper evaluation. The system validates AI pairwise comparison, single-item scoring, and tournament ranking methods against multiple peer review datasets.

## Architecture
- **Backend**: FastAPI + MongoDB
- **Frontend**: React (CRA) + Shadcn/UI
- **Caching**: 3-layer (precomputed JSON → in-memory with event-driven refresh → per-request cache)
- **Validation endpoints**: ALL file-only (see /app/backend/STATIC_VALIDATION.md)
- **Leaderboard cache**: Event-driven refresh only on data changes (notify_data_changed())

## Key Technical Decisions
- Coin-flip correction is the "fair" standard for pairwise agreement
- LOO baselines control for circularity in committee comparisons
- All reviewer identities are positional (documented in footnotes)
- BT correlations use score (not rank) — no negation needed
- Abstract truncation removed — full abstracts used for all new matches
- All validation data served from precomputed JSON — never compute on request path

## Datasets
- **ICLR** (8 topics, 469 papers): Primary comparative GT
- **PeerRead ACL 2017** (80 papers): Cross-domain validation (weak ρ=0.434)
- **UAI 2024** (100 papers): Standalone only (near-random 53.9%)
- **eLife Neuro** (100 papers): Standalone GT (moved from comparative)
- **Others**: eLife Cancer/Micro/CompSysBio, MIDL, Qeios, ResearchHub

## What's Been Implemented
- Human vs AI Benchmark with coin-flip, LOO, difficulty stratification, ceiling analysis
- PW vs SI pages with SI Subscore Average metrics and full BT correlation tables
- Per-dataset tournament pages with convergence charts
- Event-driven leaderboard cache (no polling)
- Precomputed JSON system for all validation data
- Badge font system (Inter bundled)
- Data exports (papers.csv, matches.csv, rankings CSV)

## Background Tasks
- Leaderboard cache: refreshes ONLY when notify_data_changed() called
- Analysis cache: refreshes ONLY when notify_data_changed() called  
- Archive snapshots: daily at 00:05 UTC
- Fetch loop: checks every 60s, fetches per category interval (24h default)
- Compare loop: continuous with 5s sleep between rounds

## Known Issues
- PeerRead dominates size-weighted averages (documented, using equal-weight)
- Mobile Twitter/X unfurling fails (blocked on Cloudflare)
- Production convergence prewarm takes ~10 min (but serves from JSON now)

## Prioritized Backlog
### P0
- Phase 3: Notification System (Resend)
### P1  
- Import ICLR 2026 from berenslab parquet
- Score ICLR-OT with single-item AI
- Update Summarizer Report Section 2
### P2
- Expand ICLR topics (CV, RL, NLP)
- Run SI pipeline on production DB
- Remove PeerRead from pooled aggregate
- HTTP security headers
- Refactor leaderboard.py
