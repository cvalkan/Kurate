> **Superseded:** See [/app/memory/SCALABILITY_ANALYSIS.md] for the current unified analysis (Apr 7, 2026).

# Scheduler Scaling Plan: 100+ Categories

## Current State (Apr 2026)
- 14 active categories, largest has 1,597 papers
- Compare loop cycles every 60s, ~200 DB queries per cycle
- Works fine at current scale

## Bottleneck Analysis

The compare loop runs every 60 seconds and does per-category work regardless of whether anything changed:

| Operation | Queries per category | At 100 cats | At 500 cats |
|---|---|---|---|
| `count_documents` (papers) | 1 | 100 | 500 |
| `count_documents` (matches) | 1 | 100 | 500 |
| `update_tournament_stats` | 2 (count + update) | 200 | 1,000 |
| `_check_goals_met` (rankings load) | 1 | 100 | 500 |
| `_check_goals_met` (matchable filter) | 1 | 100 | 500 |
| `_check_goals_met` (top-K cross-match) | up to 45 | 4,500 | 22,500 |
| **Total per cycle** | **~51** | **~5,100** | **~25,500** |

At 100+ categories, this is ~5,000 DB queries every 60 seconds — Atlas will throttle.

## Proposed Fixes

### Fix 1: Skip Converged Categories (Priority: HIGH)

**Problem:** Categories where all goals are met still get full stats + goals check every cycle.

**Fix:** Track per-category convergence state. Once `_check_goals_met` returns True, skip that category until:
- The fetch loop adds new papers (wakes via `wake_scheduler()`)
- A periodic re-check fires (every 10th cycle = ~10 min)

```python
_converged_cats: Dict[str, int] = {}  # {category: cycle_count_since_converged}
_RECONVERGE_CHECK_INTERVAL = 10  # Re-check every 10 cycles

for cat in active_cats:
    if cat in _converged_cats:
        _converged_cats[cat] += 1
        if _converged_cats[cat] < _RECONVERGE_CHECK_INTERVAL:
            continue  # Skip — still converged
        _converged_cats.pop(cat)  # Time for re-check
    
    if await _check_goals_met(cat):
        _converged_cats[cat] = 0
        continue
    unmet_cats.append(cat)
```

**Tradeoff:** Ranking drift from manual DB edits not detected for up to 10 minutes.
**Regression risk:** Low. Fetch loop already wakes compare loop on new papers.
**Impact:** At 100 cats with 80% converged, reduces per-cycle queries from ~5,100 to ~1,100.

### Fix 2: Cache count_documents (Priority: MEDIUM)

**Problem:** Paper and match counts queried every 60s for every category. These change slowly (at most once per fetch/comparison round).

**Fix:** Per-category count cache with 5-minute TTL.

```python
_count_cache: Dict[str, dict] = {}  # {category: {"papers": N, "matches": M, "ts": float}}
_COUNT_CACHE_TTL = 300  # 5 minutes

async def _get_cached_counts(category: str) -> tuple:
    cached = _count_cache.get(category)
    if cached and time.time() - cached["ts"] < _COUNT_CACHE_TTL:
        return cached["papers"], cached["matches"]
    papers = await db.papers.count_documents({"categories.0": category})
    matches = await db.matches.count_documents({...})
    _count_cache[category] = {"papers": papers, "matches": matches, "ts": time.time()}
    return papers, matches
```

**Tradeoff:** Admin UI shows paper/match counts up to 5 min stale.
**Regression risk:** Very low. Counts are display-only.
**Impact:** Eliminates ~200 queries per cycle at 100 cats.

### Fix 3: Batch Top-K Cross-Match Check (Priority: HIGH)

**Problem:** `_check_goals_met` runs up to 45 individual `count_documents` queries per category to verify all top-K pairs have been compared.

**Fix:** Build all 45 `dedup_pair` keys, do one `$in` query. The `dedup_pair` index already exists.

```python
# Before (45 queries):
for i in range(len(top_k_list)):
    for j in range(i + 1, len(top_k_list)):
        has_match = await db.matches.count_documents({
            "$or": [{"paper1_id": p1, "paper2_id": p2}, ...]
        }) > 0

# After (1 query):
pair_keys = [_make_dedup_pair(top_k_list[i], top_k_list[j])
             for i in range(len(top_k_list))
             for j in range(i+1, len(top_k_list))]
matched = set()
async for m in db.matches.find(
    {"primary_category": category, "dedup_pair": {"$in": pair_keys},
     "completed": True, "failed": {"$ne": True}},
    {"_id": 0, "dedup_pair": 1}
):
    matched.add(m["dedup_pair"])
all_cross_matched = len(matched) == len(pair_keys)
```

**Tradeoff:** None. Same data, same result, fewer round-trips.
**Regression risk:** Zero. Uses the existing `dedup_pair` index.
**Impact:** Reduces per-category goal check from ~47 queries to ~3 queries. At 100 cats: saves ~4,400 queries per cycle.

### Fix 4: Batch Tournament Stats Updates (Priority: LOW)

**Problem:** `update_tournament_stats` does individual `count_documents` + `update_one` per category.

**Fix:** Collect all stats in memory, write with `bulk_write(ordered=False)`.

```python
ops = []
for cat in all_tournament_cats:
    papers = cached_counts[cat]["papers"]
    matches = cached_counts[cat]["matches"]
    goals_met = cat in _converged_cats
    ops.append(UpdateOne(
        {"tournament_id": f"cat={cat}|mode=standard"},
        {"$set": {"stats.papers": papers, "stats.matches": matches,
                  "stats.goals_met": goals_met, "updated_at": now_iso}},
    ))
if ops:
    await db.tournaments.bulk_write(ops, ordered=False)
```

**Tradeoff:** None. Same writes, batched.
**Regression risk:** Very low. `ordered=False` ensures one failure doesn't block others.
**Impact:** Reduces ~200 individual writes to 1 bulk write at 100 cats.

## Combined Impact

| Scenario | Before (queries/cycle) | After (queries/cycle) |
|---|---|---|
| 14 cats, 80% converged | ~200 | ~50 |
| 100 cats, 80% converged | ~5,100 | ~120 |
| 500 cats, 90% converged | ~25,500 | ~300 |

## When to Implement
- **Trigger:** When active categories exceed 30, or Atlas monitoring shows query throttling
- **Effort:** ~3-4 hours for all 4 fixes
- **Testing:** Run compare loop for 10 cycles on preview, verify no missed goals or stale data
- **Rollback:** Each fix is independent — can revert individually

## Dependencies
- Fix 3 depends on `dedup_pair` index (already deployed)
- Fix 1 depends on `wake_scheduler()` being called reliably from fetch loop (already in place)
- Fix 2 and 4 are standalone
