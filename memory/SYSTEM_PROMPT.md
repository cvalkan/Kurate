# Kurate.org Development System Prompt

You are working on Kurate.org, an AI paper-ranking platform that uses pairwise LLM tournaments to rank scientific papers by predicted impact. The platform runs on FastAPI + MongoDB + React in a memory-constrained 2GB container.

## Core Principles

### 1. Investigate Before Implementing
Never guess at root causes. Always reproduce the issue first, then trace the full execution path before writing a fix. When the user reports a bug, your first action is diagnosis (logs, API calls, screenshots), not code changes.

**Mistakes this prevents**: We misdiagnosed a memory issue as "thread pool too large" when the real cause was MongoDB's 3.5GB WiredTiger cache in a 2GB container. We also incorrectly attributed 502 errors to backend crashes when they were Cloudflare proxy drops.

### 2. Ask Before Implementing
Never add features, caching layers, UI components, or architectural changes without explicit user approval. Propose the approach, explain the tradeoff, and wait for confirmation. The user knows the product better than you.

**Mistakes this prevents**: We added a mobile sort picker (reverted), client-side caching (reverted), and changed badge logic (reverted twice) — all without being asked.

### 3. Understand the Full Data Flow
Before changing any component, trace the complete path: database → backend query → API response → frontend state → DOM rendering. A change at any point can cascade unexpectedly.

**Mistakes this prevents**: We bumped `_ANALYSIS_STORE_VERSION` to clear stale gpt-5 data, but production was running old code that re-cached WITH gpt-5. The fix only worked after adding a response-level filter. Similarly, `is_ranking` used a narrow allowlist of "idle" strings, showing "Ranking in progress" for states like "Generating summaries" that weren't actual ranking.

### 4. Never Load Large Documents in Aggregation Pipelines
MongoDB aggregation with `$strLenCP` on `full_text` (40-100KB per paper) forces MongoDB to load every document's full text into memory. With 1500+ papers, this causes OOM. Use fixed estimates or pre-computed fields instead.

**Mistakes this prevents**: The admin timeseries endpoint used `$strLenCP` on `full_text` and `abstract` in an aggregation pipeline, causing 502 errors on production with 1500+ papers.

### 5. Memory Budget Awareness
The container has 2GB shared between Python (~375MB), MongoDB (~600MB with 512MB WiredTiger cap), and OS (~100MB). Never introduce operations that could spike either process:
- No bulk-loading match collections into Python (use aggregation pipelines or targeted queries)
- No uncapped MongoDB caches (WiredTiger is capped to 512MB at startup)
- Always use `force_gc()` (gc.collect + malloc_trim) after heavy operations
- `--reload` is auto-patched out at startup to prevent restart storms

### 6. Cache Invalidation Requires the NEW Code
Bumping a cache version only helps if the production server is running the code with the filter/fix. If old code is still deployed, it will re-populate the cache with stale data. Always add response-level filters as a safety net.

### 7. Frontend State: Avoid Two-Render Cycles
Using `useEffect` to update state (like `renderCount`) causes a flash: React renders once with old state, then re-renders with the new state. Users see a brief flicker. Instead, derive values synchronously (useMemo) or set state before the async gap.

**Mistakes this prevents**: Progressive rendering caused badge flashing when `loadMore` appended data — the `useEffect` reset `renderCount` to 100, causing a visible shrink-then-regrow.

### 8. Race Conditions in Infinite Scroll
When the user changes sort/category/scoring method, `fetchLeaderboard` fires asynchronously. During the network wait, `loadMore` can fire from the IntersectionObserver with stale parameters (wrong offset, wrong sort). Guard with a `sortPending` flag and check `loading` state in `loadMore`.

### 9. Promise.all Fails Completely on Any Rejection
If one of N concurrent requests returns 502, `Promise.all` rejects and none of the successful responses are used. Use `Promise.allSettled` for independent requests (like the admin stats page loading timeseries + stats + logs in parallel).

### 10. Benchmark Methodology Precision
The Human vs AI benchmark has multiple layers of aggregation that produce different numbers:
- **Pair-pooled** vs **expert-averaged** vs **dataset-averaged** — these give different rates
- **Ties excluded** vs **coin-flip (0.5)** vs **actual random flip** — different CF numbers
- **≥1 vs ≥2 expert preferences** — changes which pairs have "majority"
- **Rankable tiers** (Oral/Spotlight/Poster/Reject) vs **all tiers** (incl. Withdrawn) — changes committee tie rate
- Within-tier subsampling seed affects ~50 borderline AI majority votes, cascading ±0.5% across all metrics

Always be explicit about which aggregation method, tie treatment, expert filter, and pair set you're using. Small filter differences produce measurably different results.

## Architecture Quick Reference

### Server-Side Sorting
The leaderboard uses server-side sorting with MongoDB indexes. The frontend sends `sort_by` and `sort_dir` params. In TrueSkill mode, `score` maps to `ts_score`. PAGE_SIZE=200 with infinite scroll.

### Background Tasks
- `_compare_loop`: runs tournament matches (when unpaused)
- `_fetch_loop`: fetches papers from arXiv
- `_bg_memory_heartbeat`: logs RSS every 5 minutes
- `_refresh_analysis_store`: pre-computes Model Analysis data after each rerank
- `_recompute_convergence_bg`: rate-limited to 5% match growth

### Key Collections
- `rankings`: pre-computed scores, wins, comparisons per paper (the primary read source)
- `matches`: raw pairwise match results (avoid bulk-loading into Python)
- `analysis_store`: pre-computed correlation/model data for instant page loads
- `validation_matches`: separate collection for benchmark experiments
- `system_logs`: memory heartbeats, events, monitor checks

### What NOT to Do
- Don't reintroduce in-memory Python dict caches for analytics
- Don't load the full `matches` collection into memory (use rankings or targeted queries)
- Don't add `--reload` to uvicorn (it's auto-patched out for a reason)
- Don't use `hash()` for random seeds (non-deterministic across restarts; use hashlib)
- Don't use `Promise.all` for independent parallel requests
- Don't clear leaderboard data on sort change (causes empty flash; use sortPending flag instead)
