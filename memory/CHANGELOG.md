# Changelog

## 2026-06-05 — OAI-PMH Migration & arXiv Pipeline Overhaul

### OAI-PMH Fetcher (replaces REST API as primary)
- **New**: `fetch_arxiv_papers()` now uses arXiv OAI-PMH (`export.arxiv.org/oai2`) as primary fetcher
- **Set-level caching**: One harvest per top-level set (cs, physics, math...) serves ALL subcategories instantly. ~7 harvests cover all 45 categories vs. 45 individual API calls
- **REST API fallback**: Kept as automatic fallback when OAI-PMH fails
- **Created date filtering**: Only papers with `created >= date_from` are added (excludes old papers with metadata-only updates)
- **Revision handling**: OAI-PMH can't distinguish real revisions from metadata updates (no version numbers), so revisions are only detected via REST API fallback path
- Files: `services/arxiv.py` (rewritten)

### IPRoyal Rotating Proxy
- **New**: `ARXIV_PROXY_URL` env var routes REST API requests through rotating residential proxies
- Per-request session rotation (`_session-XXXX_lifetime-1m` in password) for fresh IP each attempt
- OAI-PMH does NOT use proxy (not needed — designed for bulk harvesting)
- Files: `services/arxiv.py`, `backend/.env`

### Round-Robin Fetch Loop
- **Changed**: Processes ONE category per tick (was: all 45 in a burst)
- **Removed**: `fetch_delay_minutes` setting — replaced with fixed 10s pause between categories
- **Removed**: Global backoff, per-category backoff — unnecessary with OAI-PMH + proxies
- Stale backoff keys auto-cleaned on startup
- Files: `services/scheduler.py`

### Logging Cleanup
- **Removed**: `slow_response` events (was 72% of all logs — 4,782/day)
- **Removed**: Duplicate `pdf_download` event (merged into `fetch_cycle`)
- **Removed**: Duplicate summary tracking (`track_llm_usage` was called in both llm.py and scheduler.py)
- **Renamed**: `slow_query` → removed entirely
- **Fixed**: `convergence` event only logs on transition (was spamming every 60s)
- **Fixed**: `fetch_failed` removed as separate event (info merged into `fetch_cycle`)
- Files: `services/scheduler.py`, `routers/leaderboard.py`, `routers/admin.py`

### Stats Drift Fix
- **Fixed**: `_seed_finalize` now scopes `_total` aggregation to active categories only
- Deletes stale daily_stats rows from non-active categories
- Root cause: `_total` included matches from previously-active categories not in `expected` count
- Files: `routers/admin2_stats.py`

### Admin Settings
- **Removed**: `fetch_delay_minutes` (obsolete with OAI-PMH)
- **Fixed**: `max_papers_per_fetch` now actually caps papers (was ignored, hardcoded to 2000)
- **Fixed**: `max_initial_backlog` now works correctly
- **Updated**: Descriptions for fetch-related settings
- Files: `routers/admin.py`, `core/config.py`, `frontend/src/pages/AdminPage.jsx`

### Bounded Dedup Query
- **Fixed**: Replaced unbounded global `papers` collection scan with bounded `$in` query
- **Fixed**: chemrxiv dedup scan changed from `{}` to category-scoped
- **Fixed**: MongoDB timeouts classified as `reason="db_timeout"` (was generic `fetch_error`)
- Files: `services/scheduler.py`

### arXiv Retry Logic
- **Changed**: 429 retries re-enabled (each retry gets fresh proxy IP)
- **Removed**: `_parse_retry_after`, `_BASE_BACKOFF`, `_MAX_BACKOFF` (obsolete)
- **Kept**: 3s global throttle between requests (polite baseline)
- Files: `services/arxiv.py`

## 2026-06-03 — Durable Drip Seed (prior session)
- See PRD.md for full details
