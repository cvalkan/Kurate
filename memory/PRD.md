# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Full architecture doc**: `/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)
- **Scalability doc**: `/app/memory/SCALABILITY_ANALYSIS.md`

## What's Been Implemented

### Session: Apr 8-9, 2026

**Memory Optimization (4 fixes):**
- Fix A: `force_gc()` + `malloc_trim` after every rerank
- Fix B: Pair-exhaustion detection for stalled categories
- Fix C: Single-pass rerank (eliminated double DB scan)
- Sequential reranks in compare loop (prevents concurrent memory stacking)
- Memory profiling instrumentation in `_deferred_startup`

**BT→WR Naming Cleanup:**
- Renamed all misleading BT variables/API keys across 6 backend files + 5 frontend files + precomputed JSON
- `bt_correlation` → `wr_correlation`, `ai_bt` → `ai_wr_score`, `bt_sampling` → `score_gap_sampling`

**Vision vs Text Experiment:**
- Selected 100 papers (50 visual-heavy, 50 text-heavy) across 3 categories
- Ran Claude Opus 4.6 Thinking on all 100 with text-only AND native PDF input
- Result: ρ improvement not statistically significant (Δ=+0.029, 95% CI [-0.022, +0.087])
- PDF mode costs 1.9x more than text mode via Anthropic direct API
- Native PDF document type DOES include vision (confirmed empirically)

**Scoring Method Analysis:**
- Subsampling experiment: TS/OS outperform WR at sparse data (<18 M/P)
- At full data density (>30 M/P), all methods converge
- H-BT vs scalar GT comparison across 9 ICLR datasets
- Anthropic direct pricing: ~$6.41/M input vs Emergent $5.00/M

**Other:**
- Admin button fixes (force bypass, resilient fetch pipeline, PDF retry)
- Correlation page 6.6s→0.15s (background cache logger fix)
- Summary fallback chain for Claude content policy
- Gap tooltip improvement
- Architecture document (13 sections)
- Investor pitch document

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper

### P1
- Architecture Split: KURATE_ROLE env var (web vs worker) — fundamental memory fix
- Investigate production 1,550 MB baseline (profiling instrumentation deployed)
- TrueSkill-first matchmaking
- Email notifications via Resend
- Resolve circular import chain

### P2
- Migrate to httpOnly cookies
- Refactor monolithic files
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
- Vision-based PDF summaries (experiment shows marginal quality improvement at 2x cost)
