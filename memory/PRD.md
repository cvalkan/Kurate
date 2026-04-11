# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org.

## Full Architecture Doc
`/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)

## What's Been Implemented (Apr 9-11, 2026)

### Incremental OpenSkill
- Global + per-model incremental OS with separate OS_SCALE=15
- Backfill endpoints for model_os, archive_scores, si_ratings
- Model Analysis integration (renamed from OS 1p/3p/10p to single "OpenSkill")
- Leaderboard toggle: TrueSkill (default) + OpenSkill

### Paper Page Redesign (E2)
- Tournament Score hero (70%) + Rating sidebar (30%)
- Grey score bars for sub-ratings
- Integrated badge header (Gold/Silver/Bronze with tier colors)
- Universal rank header (#X of Y · Category Name)
- Score-based CI bar with category min/max range
- 4 stat tiles (Win Rate, Wins, Losses, Matches)
- Paginated comparison history (20 per page)
- Mobile-responsive stacked layout

### Universal Share Page
- `/share/{paperId}` route reuses BadgePage
- Medal display for top-3 papers, plain rank for all others
- Backend endpoint `/api/badge/paper/{id}/share`

### Badge Consistency
- All views sort by ts_score for rank (archive list, paper page, badge page)
- Merged weekly/monthly badge endpoints into shared `_get_badge_data`
- Badges filtered by category archive_frequency setting

### Memory Optimizations (1,580→432 MB)
- Sequential reranks with GC
- Single-pass rerank (eliminated double DB scan)
- Pair-exhaustion detection
- Incremental match counters
- Two-tier goals cache with snapshot staleness detection
- Removed obsolete SI backfill + community_likes

### Experiments
- Vision vs Text PDF summaries (100 papers, ρ improvement not significant)
- Summary-only vs Abstract+Summary (7K matches, abstract helps ρ+0.055 on ICLR)
- WR vs TS vs OS scoring method analysis with subsampling

### Code Cleanup
- BT→WR rename across entire codebase
- Removed OpenSkill 1p/3p/10p (replaced by incremental)
- Removed community_likes

## Prioritized Backlog

### P0
- ReviewerToo Multiple Reviewer Personas

### P1
- Architecture Split (KURATE_ROLE)
- Badge image for non-medal papers
- TrueSkill-first matchmaking
- Email notifications via Resend

### P2
- Shareable badge card redesign
- Refactor monolithic files
- Mobile Twitter/X unfurling
