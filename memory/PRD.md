# Kurate.org Validation Hub — PRD

## Original Problem Statement
Build and maintain a sophisticated "Validation Hub" for an AI paper-judging system at kurate.org.
The application evaluates scientific papers using an incremental TrueSkill & Win-Rate approach.
PRODUCT REQUIREMENTS: implement Multiple AI Reviewer Personas based on the "ReviewerToo" academic paper.

## Full Architecture Doc
`/app/memory/ARCHITECTURE.md` (1,250+ lines, 13 sections)

## What's Been Implemented

### Revision System — Standalone-Paper-Per-Version Refactor (Apr 18, 2026 · second pass)
- **Model change**: each arXiv revision is now a *new standalone paper document* with its own UUID, ranking row, and match history — not an in-place mutation of the original.
- **`_handle_revision`** (scheduler.py): on new version detection it now (1) inserts a fresh paper doc with the new arxiv_id, shared `arxiv_id_base`, and `previous_version_paper_id` link; (2) flips the old paper's `is_latest_version=False`, sets `frozen_at`, `superseded_by_paper_id`; (3) denormalises the flag onto the old ranking row so leaderboard queries can filter without a `$lookup`; (4) seeds a fresh ranking (baseline TrueSkill) for the new paper with denormalised title/authors/arxiv_id for leaderboard display. Old paper's summaries, matches, ranking stats are left untouched.
- **Filters applied** — frozen rows are now excluded from:
  - Category, tag-filtered, and all-papers leaderboard queries (`is_latest_version: {$ne: false}` added to `_RANK_PROJ`-consuming queries)
  - Monthly/weekly archive ingestion
  - Pair selection (`get_matchable_paper_ids`)
  - Version-detection lookup in `run_fetch_cycle` (only latest sibling is compared against new raw papers)
- **Paper detail API**: `GET /api/papers/{id}` now returns `sibling_versions` (list of `{paper_id, version, arxiv_id, is_latest, frozen_at}`) when 2+ standalone versions exist, driving the front-end toggle.
- **Index model**: previous unique-sparse index on `arxiv_id_base` dropped (multiple versions legitimately share a base) and replaced with a non-unique sparse index. New compound index `(category, is_latest_version, ts_score)` on rankings keeps leaderboard queries fast.
- **Frontend**:
  - New `VersionToggle` component on the paper page — segmented pill control (`v1 | v2 | v3`) placed inline to the right of the arXiv link, active version dark / other versions are clickable router links. Hidden when `sibling_versions` is absent.
  - Leaderboard: `v{N}` badge rendered from the `arxiv_id` suffix (e.g., `2602.12345v3` → badge `v3`) next to the paper title, amber accent.
  - Previous revision UI (RevisionBanner / VersionHistory / ArchivedMatches) removed — each version is a standalone page.
- **Admin revision feed** (`/api/admin/revision-feed`): reworked to surface standalone-paper families (grouped by `arxiv_id_base`, 2+ docs) alongside legacy in-place revised papers for auditability.
- **Migration script** updated: backfills `is_latest_version=True` on the highest-version sibling within each `arxiv_id_base` group, `False` on the rest; idempotent, env-guarded, scheduler-paused during writes.
- **Tests**: 69/69 passing (`backend/tests/test_standalone_versions.py`) — covers sibling creation, leaderboard filtering, frozen-page access, match isolation, pair-selection exclusion, `_handle_revision` new-doc creation, preserved-old-state invariants, admin feed, index shape, and legacy compatibility.
- **Demo data**: 3 standalone versions (`demo-multi-v1-abc` → `demo-multi-v3-abc`) share base `8888.77777` and are wired into the cs.RO leaderboard for live UI review.
- Files touched: `backend/services/scheduler.py`, `backend/routers/leaderboard.py`, `backend/routers/admin.py`, `backend/server.py`, `backend/scripts/migrate_arxiv_versions.py`, `backend/scripts/seed_standalone_versions_demo.py` (new), `backend/tests/test_standalone_versions.py` (new), `frontend/src/pages/PaperPage.jsx`, `frontend/src/components/leaderboard/LeaderboardTable.jsx`

### Revision System Hardening + Frontend UI (Apr 18, 2026)
- **🔴 Critical backend fixes**:
  - `_incr_match_counts` now decrements after supersession (UI/DB consistency — previously counter stayed inflated after every revision, misreporting match counts to admin dashboards).
  - Migration script hardened for production: requires `MONGO_URL` env var (no localhost default), auto-pauses scheduler via `db.settings.paused=true`, loops merge step until zero duplicates remain, restores prior pause state in `finally`, adds `--dry-run` flag.
  - Cross-category version drift: `existing_bases` lookup now scans all categories (not just the current one) so v1→v2 papers that switch primary category don't trigger `DuplicateKeyError` and abort the fetch batch. `insert_one` wrapped in try/except so a single collision only skips that paper.
- **🟠 High-priority fixes**:
  - In-flight match race: new in-memory `_paper_revision_epochs` tracker bumped inside `_handle_revision`. Pair selection snapshots the epoch; at match insert, if the paper's epoch has moved forward, the new match is flagged `revision_superseded=True` at write time. Counter bump and ranking update are both skipped for stale matches. Prevents matches judged against old summaries from polluting the freshly-reset v2 tournament.
  - `_content_similarity` now stopword-filtered (common English + scientific boilerplate). Unrelated ML papers score ~0.00 instead of ~0.30; paraphrased edits score 0.80+. Threshold 0.95 now works as intended.
  - Orphan full_text (paper with PDF extraction failure) falls back to abstract similarity instead of defaulting to tournament-reset. If both texts are missing, treat as "updated" not "revised".
  - Compound indexes added: `paper1_revision_idx`, `paper2_revision_idx` for per-paper archived-match queries. (Partial index with `$ne` not supported by MongoDB — documented in server.py comment.)
  - `version_history` array capped at 20 most-recent versions via `$slice: -20` to prevent unbounded growth.
- **Frontend revision UI**:
  - Paper page: amber `RevisionBanner` surfaces "Revised on arXiv — tournament restarted for v{N}" with previous rank / score / match count.
  - Paper page: collapsible `VersionHistory` section below score card showing each archived version (rank, score, matches, similarity score + basis, tournament_reset flag).
  - Paper page: collapsible `ArchivedMatches` section showing superseded comparisons from previous versions (dashed borders, faded opacity).
  - Leaderboard: inline `v{N}` chip next to the paper title on revised papers, with hover tooltip showing `prev_rank`, `prev_ts_score`, `prev_comparisons`.
- Tests: 7 original + 12 regression + 4 new race-fix tests = **23/23 passing**. New tests cover counter drift, epoch mismatch detection, stopword similarity, and abstract fallback.
- Files touched: `backend/services/scheduler.py`, `backend/server.py`, `backend/scripts/migrate_arxiv_versions.py`, `backend/tests/test_revision_race_fixes.py`, `frontend/src/pages/PaperPage.jsx`, `frontend/src/components/leaderboard/LeaderboardTable.jsx`

### Convergence Chart on Fixed Benchmark + Fair Pooling (Apr 17, 2026)
- Added convergence chart to AI vs. Human (Fixed) page via new `/api/validation/fixed-convergence` endpoint
- Refactored `_compute_convergence` to run **per-dataset** TrueSkill tournaments and equal-weight average ρ across datasets, eliminating cross-dataset score-scale mixing artifact
- Added single-item baseline as dashed orange horizontal reference line on both ICLR 2026 and Fixed convergence charts (ρ from ai_rating/single_item_score vs h1_avg_rating)
- Chart X-axis capped at 0–30 matches/paper; only emit a checkpoint when all datasets reached that depth (prevents spurious drops at deep matches where only 1-2 datasets contribute)
- Fixed bug: precompute registry routed `human-ai-benchmark-fixed-comp` through the wrong compute function; now uses `compute_fixed_benchmark` directly

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

### Revision Handling System (Apr 18, 2026)
- Implemented arXiv revision detection and handling in the live ingestion pipeline
- Every revision: snapshots old version (summaries, ratings, rank), re-downloads PDF, clears summaries for re-generation
- Content-diff gate (admin setting `revision_diff_threshold`, default 0.95): controls whether tournament is also reset
  - Significant revision (similarity < threshold): supersedes old matches (`revision_superseded` flag), resets ranking to 0
  - Cosmetic revision (similarity ≥ threshold): keeps tournament state, only re-evaluates content
- Version history stored as append-only array on paper document
- Revision badge on rankings shows previous rank/score on hover
- Paper detail API returns `version_history`, `revision_badge`, split `matches` vs `archived_matches`
- Admin revision feed: `GET /api/admin/revision-feed` — lists all revised papers with match counts, superseding status, version history
- Migration script: backfilled `arxiv_id_base` + `current_version` for 2,180 papers, merged 9 pre-existing duplicates, created sparse unique index
- `revision_superseded` filter added to all ranking/match queries (backwards-compatible — no behavior change for non-revised papers)
- Files: `services/arxiv.py`, `services/scheduler.py`, `services/ranking.py`, `routers/leaderboard.py`, `routers/admin.py`, `core/config.py`, `scripts/migrate_arxiv_versions.py`
- Tested: 7/7 unit tests + 12/12 regression tests covering duplicate prevention, match superseding, dedup reuse, summary clearing, version history, ranking reset, cosmetic revision, migration idempotency, revision feed, orphan detection, production data regression

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
- Missing GPT/Gemini SI Ratings — enforce `{"score": X.X}` JSON schema across all 3 models
- Sub-topic Matchmaking via LLM classifier (Option B)

### P2
- httpOnly cookie migration
- Gmail congrats flow cleanup
- Refactor monolithic files
- Mobile Twitter/X unfurling (blocked on Cloudflare)
