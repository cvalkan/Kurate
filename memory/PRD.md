# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org. The platform benchmarks AI judges against human peer reviewers using multiple methodologies (pairwise comparison, single-item rating, tournament ranking) across multiple academic datasets.

## Core Architecture
- **Backend**: FastAPI + MongoDB, live analysis from rankings + cached OpenSkill
- **Frontend**: React, served as compiled build
- **Model Analysis**: Live WR/TS/SI computed on-the-fly from rankings (~200ms). OpenSkill cached in `analysis_store`, merged on read, refreshed via admin buttons.
- **Background**: Compare loop + fetch loop. Tournament matches update rankings incrementally.
- **Full architecture doc**: `/app/memory/ARCHITECTURE.md` (1,238 lines, 13 sections)

## What's Been Implemented

### Session: Apr 7, 2026

**Admin Button Fixes:**
- Fixed `gen_one` to respect `force=True` (bypasses pause check)
- Made `run_fetch_cycle` resilient: 4 independent steps
- Fixed `summary_coverage.with_summaries` to use actual DB count
- Fixed `_run_fetch_in_background` status mapping
- Step 4 always runs (rankings insert for all unranked papers)
- Added per-step logging
- Updated frontend toast with detailed results

**PDF Download Retry:**
- Force mode retries previously failed PDFs (`pdf_failed=True` papers)
- 22 cs.CR papers unblocked (were permanently blacklisted)

**Correlation Page Performance:**
- Fixed missing `logger` import in `model_analysis.py` — background cache task was silently crashing
- TTL increased to 1h safety net (event-driven refresh is the primary mechanism)
- Page load: 6.6s → 0.15s

**Summary Fallback Chain:**
- Added GPT/Gemini as fallbacks when Claude refuses (content policy)
- 2 AI safety papers in cs.CR unblocked

**Diagnostics:**
- Added `/api/admin/unranked-papers` endpoint with `ranked_not_matchable` details
- Added ArXiv 429 error propagation (shows "failed" not "completed")

**Architecture Document:**
- Created `/app/memory/ARCHITECTURE.md` — comprehensive 13-section platform architecture

## Prioritized Backlog

### P0
- Implement Multiple AI Reviewer Personas from ReviewerToo paper (arXiv:2510.08867)

### P1
- Architecture Split: KURATE_ROLE env var (web vs worker)
- TrueSkill-first matchmaking (save ~35% LLM costs)
- Raise parallel_agents cap and test higher throughput
- Email notification system (Resend integration)
- Resolve circular import chain

### P2
- Migrate to httpOnly cookies
- Wire up AuthorClaimSection or remove
- Refactor monolithic files (admin.py: 3,336 lines, scheduler.py: 1,620 lines)
- Mobile Twitter/X unfurling (BLOCKED on Cloudflare)
