# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org.
The application evaluates scientific papers using an incremental TrueSkill & Win-Rate approach.
PRODUCT REQUIREMENTS: implement Multiple AI Reviewer Personas based on the "ReviewerToo" academic paper.

## Full Architecture Doc
`/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)

## What's Been Implemented

### ICLR 2026 Match-Count Consistency Cleanup (Apr 17, 2026)
- Identified that `/app/memory/sampled_matches.csv` had been overwritten with a wrong 58K pair set; only 454/58,363 pairs overlapped with the user's target
- Restored correct CSV (user-uploaded) to `/app/memory/sampled_matches.csv`; old file archived as `sampled_matches_WRONG_20260417.csv.bak`
- Fixed `validation_match_pipeline.py` resume bug: `load_completed()` was reading only JSONL; added `load_completed_from_db()` using MongoDB as canonical source (prevents duplicates after crashes)
- Deleted 2,086 duplicate pairs in DB (same pair judged by multiple models)
- Deleted 9,898 orphan pairs (matches for pairs not in the target CSV) from both MongoDB and `validation_match_results.jsonl`
- Added `total_ai_matches`, `total_unique_pairs`, `avg_matches_per_paper` fields to `/human-ai-benchmark-iclr2026` endpoint
- Added explanatory blue callout on page clarifying AI matches vs unique pairs vs controlled pairs vs CF pairs
- Identified 58 zero-eval papers (34 Desk Reject, 24 Withdraw) — these cause the small gap between unique pairs and CF pairs

### Human vs. AI Benchmark — Avg Tie Rates + Coin Flip (Apr 17, 2026)
- Added tie rate + coin-flip numbers for `AI vs. Average` and `Human vs. Average (LOO)` columns (previously showed "—")
- Backend (`services/benchmark_fixed.py`): added `ai_avg` / `h_avg_loo` entries to `tie_rates` dict, added `ai_avg` / `human_avg_loo` to `_pool_datasets` coin-flip pooling
- Introduced `AVG_TIE_EPS = 0.25` rating-point tie threshold — averages within 0.25 treated as effectively tied (coin-flipped). Consistent with discreteness of 1-10 reviewer scale (ICLR uses only {1,3,5,6,8,10})
- Updated `services/precompute.py` to route `human-ai-benchmark-fixed-comp` through `compute_fixed_benchmark` (same source of truth as endpoint handler)
- Regenerated precomputed JSON cache; rebuilt frontend bundle
- Updated frontend footnotes (`HumanAIBenchmarkSection.jsx`):
  - Footnote ²: added "Selection bias warning" explaining Majority drops pairs with no clear majority (~5-10pp inflation)
  - New "avg" footnote: documents epsilon threshold and why Average preserves all pairs
  - Footnote ⁶: added AI/H vs. Average tie-condition explanation (< 0.25 rating points)

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

### Score–Pairwise Coherence Metric (Apr 14, 2026)
- New "Score–Pairwise Coherence" section on Model Analysis page (/correlation)
- For each judge model (Claude, GPT, Gemini): checks if its own SI score s(A)>s(B) predicts pairwise A>B
- Bins by |score gap|: [0–0.5, 0.5–1, 1–1.5, 1.5–2, 2–3, 3+]
- Bar chart + data table with per-model agreement rates
- Key finding: Claude Opus 81% overall (60.6%→97.7%), GPT 74.1%, Gemini 78.5%
- GPT has narrow SI score range so very few pairs at high gaps
- Backend: `_compute_score_pairwise_coherence()` in model_analysis.py
- Frontend: `CoherenceSection.jsx` component

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
