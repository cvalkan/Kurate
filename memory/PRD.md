# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org.
The application evaluates scientific papers using an incremental TrueSkill & Win-Rate approach.
PRODUCT REQUIREMENTS: implement Multiple AI Reviewer Personas based on the "ReviewerToo" academic paper to enhance pairwise ranking accuracy.

## Full Architecture Doc
`/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)

## What's Been Implemented

### Badge Consistency Fix (Apr 11, 2026)
- Fixed SVG medal rank no-op bug (template rank replacement was self-referencing)
- Unified TrueSkill (rank_ts/ts_score) as canonical ranking metric across ALL views
- Leaderboard default sort changed from WR score to TrueSkill score
- Fixed missing rank_ts in Paper Page DB projection
- Share page: archive leaderboard link from best_badge, proper nav links
- Badge text on Paper Page: plain text (not clickable link)
- Verified consistency across leaderboard, paper page, and share page for 4 papers

### Universal Share Page (Apr 2026)
- `/share/{paperId}` route reuses BadgePage
- Medal display for top-3 papers, plain rank for all others
- Backend endpoint `/api/badge/paper/{id}/share` with best_badge lookup

### Incremental OpenSkill
- Global + per-model incremental OS with separate OS_SCALE=15
- Backfill endpoints for model_os, archive_scores, si_ratings
- Model Analysis integration (renamed from OS 1p/3p/10p to single "OpenSkill")
- Leaderboard toggle: TrueSkill (default) + OpenSkill

### Paper Page Redesign (E2)
- Tournament Score hero (70%) + Rating sidebar (30%)
- Grey score bars for sub-ratings
- Integrated badge header (Gold/Silver/Bronze with tier colors)
- Universal rank header (#X of Y - Category Name)
- Score-based CI bar with category min/max range
- 4 stat tiles (Win Rate, Wins, Losses, Matches)
- Paginated comparison history (20 per page)
- Mobile-responsive stacked layout

### Badge Consistency
- All views sort by ts_score for rank (archive list, paper page, badge page)
- Merged weekly/monthly badge endpoints into shared `_get_badge_data`
- Badges filtered by category archive_frequency setting

### Memory Optimizations (1,580->432 MB)
- Sequential reranks with GC
- Single-pass rerank (eliminated double DB scan)
- Pair-exhaustion detection
- Incremental match counters
- Two-tier goals cache with snapshot staleness detection

### Experiments
- Vision vs Text PDF summaries (100 papers, rho improvement not significant)
- Summary-only vs Abstract+Summary (7K matches, abstract helps rho+0.055 on ICLR)
- WR vs TS vs OS scoring method analysis with subsampling

### Code Cleanup
- BT->WR rename across entire codebase
- Removed OpenSkill 1p/3p/10p (replaced by incremental)
- Removed community_likes

## Prioritized Backlog

### P0
- ReviewerToo Multiple Reviewer Personas

### P1
- Architecture Split (KURATE_ROLE)
- Author Verification (ORCID Option E/B)
- TrueSkill-first matchmaking
- Email notifications via Resend
- Circular import cleanup

### P2
- httpOnly cookie migration
- Gmail congrats flow cleanup
- Refactor monolithic files
- Mobile Twitter/X unfurling (blocked on Cloudflare)
