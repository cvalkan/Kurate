# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Model Analysis**: Live WR/TS/SI computed on-the-fly from rankings (~200ms). OpenSkill cached in `analysis_store`, merged on read, refreshed via admin buttons.
- **Background**: Compare loop + fetch loop. Tournament matches update rankings incrementally.

## What's Been Implemented

### Session: Apr 5, 2026

**Incremental Model Analysis (Major Architecture Change):**
- Split `compute_model_analysis()` into `compute_live_analysis()` (fast, from rankings) + `compute_openskill_cache()` (heavy, from matches)
- Model Analysis page now loads in 0.07-0.23s (was 2+ min from cold cache)
- No more "warming up" state — always instant live data
- OpenSkill columns merged from cached `openskill-cache` docs when available
- Admin "Refresh This Category" / "Refresh 'All Categories'" buttons compute OpenSkill only
- Startup prewarm now only computes OpenSkill caches (not full analysis)

**Scaling:**
- DB-backed pair dedup: `dedup_pair` field + compound index
- `_select_pairs` async with indexed DB queries — O(100) memory, scales to 100K+ papers

**Critical Fixes:**
- Restored `_select_pairs` (was accidentally deleted, blocked ALL matches)
- GPT-5.2 Model Correlation fix (MongoDB dot-in-key merge bug)
- "Average" tab crash fix (optional chaining + error boundaries)

**Admin Dashboard:**
- Redesigned numbers (consistent denominators)
- Pair exhaustion notice
- Per-category fetch state
- Match timestamps
- Model Analysis Cache section with refresh buttons

**Safeguards:**
- Startup can't clear analysis cache (no index drops, no version auto-clear)
- Only admin buttons trigger OpenSkill recompute
- Cache clear logging

**Code Quality:**
- Shared `get_matchable_paper_ids()`, removed dead code
- Single code path for progress endpoint (removed precomputed cache duplicate)

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Email notification system (Resend integration)
- Resolve circular import chain
- Migrate to httpOnly cookies

### P2
- Wire up AuthorClaimSection or remove
- Complete Gmail congrats flow or remove
- Refactor monolithic leaderboard.py and scheduler.py
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
