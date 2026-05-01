# Changelog

## May 1, 2026 — Admin Panel Real-Time Data Fix
- **Root cause**: `_ADMIN_CACHE_TTL = 300` (5 min) applied as blanket cache to ALL admin endpoints. After data changes (fetch, summarize, compare), the UI showed stale numbers for up to 5 minutes.
- Removed caching from `progress` and `status` endpoints — they now always serve real-time data from indexed DB queries (~150-250ms).
- Retained 5-min cache only for expensive endpoints (`stats` — model aggregation, `timeseries` — historical daily data).
- Fixed `progress` endpoint to query `db.matches.count_documents()` directly instead of stale `_category_status` in-memory dict.
- Added `_invalidate_admin_cache(category)` to `run_fetch_cycle()` so `stats` cache refreshes after new data.
- Fixed `_invalidate_admin_cache` to also clear `__precomputed__` keys (cross-category stats aggregation).
- Eliminated `_goals_met_cache` entirely: rewrote goal3 check from 45 individual `count_documents` queries to 2 batch `$in` queries, making goals computation fast enough (~50ms) to run fresh every scheduler cycle. Removed `invalidate_goals_cache()` and all 6 call sites.
- Eliminated `_settings_cache` (5s TTL): `find_one` on indexed key is 0.3ms, cache was unnecessary. Removed `invalidate_settings_cache()` and all 7 call sites.
- Fixed KeyError on missing `title` field in `status` endpoint (some ranking docs lack denormalized title).
- Fixed archive dropdown scroll bug: scroll events inside the dropdown no longer close it.
- Fixed archive search: keyword filtering now works client-side in archive views.
- Reordered leaderboard columns to: #, Paper, Score, 95% CI, Match, Win %, Rating, Gap, Published.
- Fixed duplicate LLM calls on "Add Paper": `_pipeline_active` flag prevents scheduler from racing with single-paper pipeline.
- **Fixed paper fetch gap**: `run_fetch_cycle` now passes `date_from` (based on `last_fetch_at`) to `fetch_arxiv_papers`. In catch-up mode, the fetcher pages through ALL papers since the last fetch (up to 2000) instead of capping at 50. Prevents permanently missed papers in high-volume categories like `cs.AI`.

## April 22, 2026 (later) — Variant 1 rollout + deployment prep
- Applied Variant 1 (stacked card layout) to both Medalists view and Category Explorer via new shared `<CandidateCardV1>` component: handle + engagement counts on top, color-coded tweet text in the middle (blue when engaged, muted gray when not), and four 24×24 icon-only action buttons (Like, Follow, QT, Draft) on the bottom.
- Added `size="icon"` mode to `LikeButton` and `FollowButton`; new `QTIconButton` (link when quote-tweeted, muted otherwise) and `DraftIconButton` (Medalists only).
- Deleted `/app/frontend/src/pages/OutreachDesignPreview.jsx` and its `/admin/outreach/design-preview` route.
- Testing agent: 9/9 backend + 10/10 frontend pass (iteration_58).

## April 22, 2026 — Follow button
- New backend endpoints: `/api/admin/outreach/follow-handle` and `/unfollow-handle` (TweetAPI `interaction.follow(user_id)`). Handle→user_id cached in new `twitter_user_cache`. Follow state tracked in new `tweet_follows` collection.
- `_annotate_candidates` now also sets `followed` + `followed_at` on every candidate.
- `/activity` endpoint now returns `follows[]` plus counts.
- Frontend: new `FollowButton` (indigo theme); new **Follows** tab on `/admin/outreach/activity`.

## April 22, 2026 — Outreach: Quote & Like persistence + Activity page
- Fixed `/api/admin/outreach/medalists` to hydrate candidates with `liked` and `quote_tweeted` state (shared `_annotate_candidates` helper with `/discoveries`). Previously the Medalists view would drop the QT'd / Liked badges after any reload since the backend never returned those fields.
- Fixed race condition where Medalists view occasionally rendered empty until the user switched tabs: the parent's "current" sentinel period was truthy, so MedalistsView never swapped it for a real `weekly:YYYY-WW`, and stale empty responses could overwrite real ones.
- `handlePost` (quote tweet) now triggers a parent `onRefresh()` so DB-persisted QT state replaces optimistic in-place mutation, surviving view switches and period changes.
- Post-discovery polling now fires a single delayed reload 1.5 s after completion to cover the DB-flush tail.
- New backend endpoint `GET /api/admin/outreach/activity` returns all posted quote tweets + likes, joined with paper title/authors/arxiv_id.
- New frontend page `/admin/outreach/activity` (`OutreachActivityPage.jsx`) — tabbed table listing every quote and like with direct links to our post and the original tweet. Link added to the Outreach page header.

## April 21, 2026
### Investigation: GPT-5.2 positional bias anomaly (resolved)
- Mapped the W08–W17 positional bias per model via `/api/positional-bias-diagnostic?group=week`.
- Found GPT-5.2's drop to 35% is **three discrete step-changes**, not gradual drift:
  - W08→W09 (+6.4pp): commit `bfad1aa5` — Opus 4.5→4.6 judge swap
  - W12→W13 (−5.7pp): match volume +41%, no code change
  - W13→W14 (−4.5pp): commit `6cad4113` — `_llm_executor max_workers 100→10` + volume +51%
- Ran controlled A/B (n=199 pairs, 398 calls, production prompt_config, concurrency=5):
  - **pos1 rate = 49.75% (95% CI 44.9–54.6), consistency = 97.5%**
  - Rejects H0: p=35.5% (p = 6.6 × 10⁻⁹)
  - Proves GPT-5.2 itself has no positional bias; production rate is **infra-induced**.
- Findings appended to `/app/memory/POSITIONAL_BIAS_INVESTIGATION.md` as "April 21 follow-up".
- Per-pair results at `/app/backend/data/positional_ab_gpt52_prod_prompt.jsonl`.

### Code cleanup: summary fallback chain in compare_papers
- Removed migration-era legacy fallback `ai_impact_summary_thinking → ai_impact_summary_opus46 → ai_impact_summary` from `llm.py` (lines 637-645, 677-685).
- Live tournament was already using only the single `ai_impact_summary` field (Claude Opus 4.6 thinking summary injected by `scheduler._get_paper_summary`), so zero production behavior change.
- The chain was silently overriding the summary for non-scheduler callers (e.g. `pairwise.py`) — contract now pinned.
- Regression test added: `backend/tests/test_compare_papers_summary_contract.py` (2 tests passing).

### New tooling (reusable)
- `backend/scripts/positional_ab_gpt52.py` — controlled A/B harness (harvests prod pairs via public API, calls compare_papers locally).
- `POST /api/admin/positional-ab-test/start` + `GET /status` + `GET /list` — on-production equivalent for future runs with direct DB access.



## March 14, 2026
### Bug Fix: Mobile Twitter Unfurling (Investigation ongoing)
- **Attempted Fix 1**: Replaced `<meta http-equiv="refresh" content="0;url=...">` with `<script>window.location.replace()</script>` — DID NOT FIX mobile issue
- **Attempted Fix 2**: Removed ALL redirects/JavaScript from share pages — made them 100% pure static HTML — DID NOT FIX mobile issue  
- **Attempted Fix 3**: Changed Twitter intent URL to use explicit `url` parameter instead of embedding share URL in `text` — user reports STILL NOT FIXED
- **Conclusion**: The issue is external to our code. Share pages serve correct OG tags. Likely causes:
  1. **Cloudflare Bot Management** interfering with Twitter's mobile crawler (different IP ranges/challenge behavior)
  2. **Twitter Card Cache** persisting old data for the URL
  3. **Twitter mobile app** using a different card resolution mechanism than desktop

### Feature: Open Congrats Section
- Made "Congrats on X" and "Congrats on LinkedIn" buttons accessible to all visitors (no login required)
- Email congrats flow remains behind sign-in (for rate limiting and LLM email extraction)
- Removed the full login gate that previously blocked all congrats functionality

### Feature: Human vs AI Agreement Benchmark
- New backend endpoint: `/api/validation/human-ai-benchmark`
- New frontend section in Validation Hub under Experiments > Judge Quality
- **6-layer analysis across 7 datasets (5,260 controlled same-pair comparisons)**:
  1. Inter-rater correlation rho (pooled: 0.39, NeurIPS ref: 0.2-0.3)
  2. Thurstonian theoretical ceiling (59.0% from model, actual H-H is 79.1%)
  3. Controlled pairwise agreement: H-H=79.1%, H-Comm=92.3%, AI-H=69.7%, AI-Comm=71.9%
  4. Difficulty stratification: hard (within-tier) H-H=62.9%, AI-H=59.5% — closest NeurIPS comparison
  5. BT rank correlation: Spearman=0.524, Kendall=0.360
  6. Cohen's kappa for chance-corrected agreement
- Per-dataset breakdown with collapsible table
- NeurIPS 2014 reference context with explanatory note

### Architecture: Share Page Simplification
- Share pages are now 100% pure static HTML — no JavaScript, no redirects
- Human visitors click a styled "View Leaderboard on Kurate.org" button
- Crawlers see only clean OG/Twitter meta tags
