# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org.
The application evaluates scientific papers using an incremental TrueSkill & Win-Rate approach.
PRODUCT REQUIREMENTS: implement Multiple AI Reviewer Personas based on the "ReviewerToo" academic paper.

## Full Architecture Doc
`/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)

## What's Been Implemented

### Archive Current-Week Visibility Fix (Apr 13, 2026)
- Removed current-week/month exclusion from `_filter_archives_by_frequency`
- Archives now appear immediately upon creation (previously hidden until the following week)
- Fixes cs.AI and other new categories showing empty archive lists

### ICLR 2026 Batch Summary Completion (Apr 13, 2026)
- Fixed `generate_summary()` to detect Claude refusal responses (`finish_reason: refusal`)
- Previously, refusals caused 4 wasted retries per paper (classified as MAX_RETRIES_EXCEEDED)
- Final coverage: 3,912 / 3,949 (99.1%)
- Remaining 37: 26 refused by Claude (content policy), 6 PDF unavailable, 4 budget errors, 1 PDF too short

### ICLR 2026 Correlation Analysis (Apr 13, 2026)
- Reproduced and validated AI-Human correlation: Spearman ρ = 0.639, Pearson r = 0.627
- Computed pairwise tournament correlations using TrueSkill:
  - AI(sorted) vs Human tourney(TS): ρ = 0.618
  - Expert(TS) vs Human tourney(TS): ρ = 0.560
- Compared with ScholarPeer paper (multi-agent review framework): Kurate ρ=0.639 vs ScholarPeer ρ=0.42
- Key finding: single Opus 4.6 call outperforms 6-agent pipeline on weaker model for score alignment

### Badge System Consistency Fix (Apr 11, 2026)
- Unified TrueSkill (rank_ts/ts_score) as canonical ranking metric across ALL views
- Leaderboard default sort changed from WR score to TrueSkill score
- All keyset cursor pagination updated to use ts_score
- `_rank_doc_to_entry` uses rank_ts as primary rank
- Fixed SVG medal rank no-op bug (template rank replacement was self-referencing)
- Fixed missing rank_ts in Paper Page DB projection
- Badge image renders archive snapshot data (rank, paper_count, score, win_rate)
- Footer shows current live all-time position
- `_find_paper_badge`: prioritizes top-3 medal, falls back to most recent archive for non-medalists
- Respects admin weekly/monthly frequency setting per category
- Extracted `_compute_archive_rank` helper (eliminated 3x code duplication)
- Fixed hardcoded `p["rank"]` in share HTML → `data["rank"]`
- Badge text on Paper Page: plain text (not clickable link)
- Share page nav links: Paper details · {archive} leaderboard · All Time leaderboard

### Logo Font Unification (Apr 12, 2026)
- Replaced PNG logo with CSS-rendered Inter Bold (700) matching badge CairoSVG rendering
- "Ku" + "rate" use Inter 700, ".org" uses Inter 400 at 90% size ratio
- Added Inter 800 to Google Fonts import for full weight coverage
- Theme-adaptive: "rate" uses foreground color for dark/light mode support

### Universal Share Page (Apr 2026)
- `/share/{paperId}` route reuses BadgePage
- Medal display for top-3 papers, plain rank for all others
- Backend endpoint `/api/badge/paper/{id}/share` with archive badge lookup

### Incremental OpenSkill
- Global + per-model incremental OS with separate OS_SCALE=15
- Model Analysis integration (single "OpenSkill" metric)

### Paper Page Redesign (E2)
- Tournament Score hero (70%) + Rating sidebar (30%)
- Score-based CI bar, 4 stat tiles, paginated comparison history

### Memory Optimizations (1,580->432 MB)
- Sequential reranks, single-pass rerank, pair-exhaustion detection
- Incremental match counters, two-tier goals cache

## Prioritized Backlog

### P0
- ReviewerToo Multiple Reviewer Personas

### P1
- Architecture Split (KURATE_ROLE)
- Author Verification (ORCID Option E/B)
- TrueSkill-first matchmaking
- Email notifications via Resend
- Circular import cleanup
- 14 papers missing `ai_rating` on production

### P2
- httpOnly cookie migration
- Gmail congrats flow cleanup
- Refactor monolithic files
- Mobile Twitter/X unfurling (blocked on Cloudflare)
