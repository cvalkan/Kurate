# Admin Statistics Page Rebuild — Handoff to Opus 4.8

## Goal
Rebuild the admin statistics page from scratch at `/admin2` (new route + new backend endpoints). The current implementation at `/admin/dashboard` (Statistics tab) has been plagued by production failures due to MongoDB Atlas timeouts, BSON Date vs string type mismatches, and fragile aggregation pipelines that work on preview (local MongoDB) but fail on production (Atlas).

## What to Build

### New Backend: `/api/admin2/stats-overview`
A single endpoint that returns ALL data the stats page needs in one response. No separate timeseries/stats/logs endpoints — one call, one response.

### New Frontend: `AdminStatistics2.jsx`
Mounted at `/admin2` route (keep the old `/admin/dashboard` untouched for comparison).

## Functional Requirements (must match current admin stats)

### 1. Summary Cards (top row, 5 cards)
- **Total Papers**: count from `rankings` collection
- **Total Matches**: count from `matches` collection (+ avg matches per paper)
- **Total Tokens**: sum of input/output tokens from matches
- **Total Cost**: match cost + summary cost (per-model pricing, see MODEL_PRICING below)
- **Cost/Paper**: (match_cost / papers) + (summary_cost / papers)

### 2. Cost/Paper Over Time (line chart)
- 3 lines: Total $/paper, Match $/paper, Summary $/paper
- X-axis: dates from platform inception (~Feb 2026) to today
- Y-axis: running cumulative average (cumulative_cost_up_to_date / cumulative_papers_up_to_date)

### 3. Match Costs Panel (horizontal bar chart)
- Per model: name, match count, total cost, % of total
- Models come from `matches.model_used` field: `{provider: "openai", model: "gpt-5.2"}`

### 4. Summary Costs Panel (side by side with match costs)
- Per model: name, summary count, total cost, % of total
- Summary model keys stored in `papers.summaries` dict keys (e.g., `"anthropic:claude-opus-4-6:thinking"`)
- Data comes from leaderboard cache `_summary_stats` (precomputed by `_compute_summary_stats_agg` in leaderboard.py)

### 5. Memory Usage Chart
- RSS over time from `system_logs` collection (field: `rss_mb`, filter: `level: "mem"`)
- Configurable: 6h, 12h, 24h, 3d, 7d

### 6. Timeseries Charts (2×2 grid: Papers, Matches, Tokens, Cost)
- Toggle: Cumulative (area chart) / Daily (bar chart)
- Toggle: System (single series) / By Category (stacked, top 10 categories + "Other")
- Per-category totals table when "By Category" is selected

### 7. User Registration Chart
- Cumulative user count over time from `users.created_at`

### 8. Refresh Button + Last Refreshed Timestamp

## Architecture: How to Make It Scalable

### The Core Problem
The current implementation tries to aggregate 762K+ matches in real-time via MongoDB aggregation pipelines. This works on localhost but times out on Atlas (30s read timeout). The data also has type inconsistencies (BSON Date vs string) between preview and production.

### The Solution: `daily_stats` Collection (Incremental Materialized View)

**Schema:**
```
{
  date: "2026-06-01",        // ISO date string (always string, never Date)
  category: "cs.AI",         // or "_total" for global aggregates
  papers: 5,
  matches: 120,
  input_tokens: 500000,
  output_tokens: 50000,
  cost: 15.50,               // match cost (per-model pricing)
  summaries: 15,             // number of summary generations
  summary_cost: 4.20,        // summary cost (per-model pricing)
}
```
**Index:** `{date: 1, category: 1}` (unique compound)

**Population strategy:**
1. **On every match completion** (in scheduler.py `_process_match_result` or equivalent): fire-and-forget `$inc` on the daily_stats doc for that date+category. This is O(1) per match — no aggregation needed.
2. **On every paper addition** (in scheduler.py fetch cycle): fire-and-forget `$inc` on papers count.
3. **On every summary generation**: fire-and-forget `$inc` on summaries count + summary_cost.
4. **The API endpoint just reads daily_stats** — never aggregates matches/papers. Reading ~150 daily_stats docs is instant regardless of data scale.

**For the initial backfill** (when daily_stats is empty after first deploy):
- Run a background task that processes **one 7-day chunk at a time**
- Each chunk queries matches/papers with bounded date range using the `created_at` index
- Total backfill for 762K matches: ~20 chunks × 2-3s = ~60s background, API responds immediately with whatever data is available

### Critical: Handle BSON Date vs String

Production MongoDB stores `created_at`, `added_at`, `published` as **BSON Date objects** (native `datetime`), NOT strings. Preview stores them as strings. Your code MUST handle both:

**In MongoDB aggregation pipelines:**
```python
# WRONG — breaks on Date objects:
{"$substrCP": [{"$ifNull": ["$created_at", ""]}, 0, 10]}

# CORRECT — works for both Date and string:
{"$substrCP": [{"$toString": {"$ifNull": ["$created_at", ""]}}, 0, 10]}
```

**In Python when reading date fields from DB:**
```python
# WRONG:
date_str = doc["created_at"][:10]

# CORRECT:
raw = doc["created_at"]
date_str = raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]
```

**In MongoDB $match with date comparison:**
```python
# WRONG — string "2026-01-01" never matches Date objects:
{"created_at": {"$gte": "2026-01-01"}}

# CORRECT — use $expr with $toString:
{"$expr": {"$gte": [{"$substrCP": [{"$toString": "$created_at"}, 0, 10]}, "2026-01-01"]}}
```

## MODEL_PRICING ($/million tokens)
```python
MODEL_PRICING = {
    "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
    "anthropic/claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "anthropic/claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "gemini/gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
}
```

Summary model keys (in `papers.summaries` dict) use colon format: `"anthropic:claude-opus-4-6:thinking"`, `"openai:gpt-5_2"`, `"gemini:gemini-3-pro-preview"`. Map provider prefix to MODEL_PRICING key for cost calculation.

## MongoDB Indexes on `matches` Collection
```
created_at_1: [('created_at', 1)]
primary_category_1: [('primary_category', 1)]
primary_category_1_completed_1_failed_1_mode_1: [('primary_category', 1), ('completed', 1), ('failed', 1), ('mode', 1)]
```
**Important:** There is NO index on `{completed}` alone. Any query without `primary_category` in the filter will do a full collection scan. Always filter by `primary_category` or use the `created_at` index with date bounds.

## DB Schema Reference

### `matches` document:
```json
{
  "id": "uuid",
  "paper1_id": "uuid", "paper2_id": "uuid",
  "primary_category": "cs.AI",
  "winner_id": "uuid",
  "model_used": {"provider": "openai", "model": "gpt-5.2"},
  "tokens": {"input_est": 4215, "output_est": 171},
  "created_at": "2026-02-16T21:09:24.538674+00:00",  // STRING on preview, DATE on production!
  "completed": true,
  "failed": false
}
```

### `papers` document:
```json
{
  "id": "uuid",
  "title": "...", "abstract": "...",
  "categories": ["cs.AI", "cs.LG"],
  "added_at": "2026-02-16T...",  // STRING on preview, DATE on production!
  "published": "2026-02-05T...",  // STRING on preview, DATE on production!
  "summaries": {
    "anthropic:claude-opus-4-6:thinking": "## Scientific Impact Assessment...",
    "openai:gpt-5_2": "## Scientific Impact Assessment...",
    "gemini:gemini-3-pro-preview": "## Scientific Impact Assessment..."
  },
  "summary_tokens": {
    "anthropic:claude-opus-4-6:thinking": {"input": 12000, "output": 1800, "thinking": 4000}
  }
}
```

### `rankings` document:
```json
{
  "paper_id": "uuid",
  "category": "cs.AI",
  "score": 1450,
  "comparisons": 35,
  "wins": 20, "losses": 15
}
```

### `users` document:
```json
{
  "user_id": "uuid",
  "email": "...",
  "created_at": "2026-05-01T...",
  "last_active": "2026-06-01T...",
  "visit_count": 5
}
```

## Frontend Stack
- React + Shadcn/UI components (at `/app/frontend/src/components/ui/`)
- Recharts for charts (`ResponsiveContainer`, `LineChart`, `BarChart`, `AreaChart`, `ComposedChart`)
- Axios for API calls
- `process.env.REACT_APP_BACKEND_URL` for API base URL
- Admin auth: `sessionStorage.getItem("admin_token")` sent as `X-Admin-Token` header

## Files to Create
1. `/app/backend/routers/admin2_stats.py` — New endpoint(s)
2. `/app/frontend/src/pages/Admin2StatsPage.jsx` — New page component
3. Add route in `/app/frontend/src/App.js`: `<Route path="/admin2" element={<Admin2StatsPage />} />`
4. Register router in `/app/backend/server.py`

## Testing Strategy
1. After building, verify on preview that ALL chart views work (Cumulative/Daily × System/Category)
2. The numbers should match the existing admin stats page on preview
3. Simulate production conditions: the code must never do an unindexed full scan of matches
4. Every MongoDB aggregation must complete within 10 seconds even with 10M matches
5. Every `$substrCP` on a date field must use `$toString` first
6. Every Python `[:10]` on a DB date field must use `str()` or `strftime()` first
7. The API must never block on a computation that scales with total data size — always read from pre-aggregated data

## What NOT to Do
- Do NOT use `mode: {$exists: False}` in any match query — this field was removed
- Do NOT use `$strLenCP` on `summaries` or `full_text` fields — these are 3-100KB each and will OOM
- Do NOT aggregate all matches in a single pipeline without date bounds — will timeout on Atlas
- Do NOT cache empty results — if the leaderboard cache hasn't warmed yet, return what you have but don't cache the empty response for 5 minutes
