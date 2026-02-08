# Scalability Analysis & Architecture Action Plan

## Current State (5 categories, 250 papers, 13K matches)

Everything runs fine at this scale. But several patterns will break or degrade badly at 100+ categories.

---

## Scalability Bottlenecks at 100+ Categories

### 1. Cache refresh: O(categories × matches) — CRITICAL

```python
# leaderboard.py:_refresh_cache()
for cat_id in CATEGORIES:                          # 100+ iterations
    cat_matches = [m for m in all_matches           # scan ALL matches each time
                   if m["paper1_id"] in cat_paper_ids
                   and m["paper2_id"] in cat_paper_ids]
```

At 100 categories × 50 papers × ~50 matches/paper = ~250K matches, each cache refresh scans 250K matches × 100 categories = **25M comparisons every 20 seconds**. This will stall the event loop.

**Fix**: Pre-index matches by paper_id once, then look up per category via the index. O(papers_in_cat × matches_per_paper) instead of O(total_matches × categories).

### 2. Scheduler: full match table scan per category — CRITICAL

```python
# scheduler.py:_check_goals_met() — called for EACH active category
async for m in db.matches.find({"completed": True, "failed": {"$ne": True}}):
    if m["paper1_id"] in pid_set and m["paper2_id"] in pid_set:  # full scan
```

At 100 categories, this runs 100 full collection scans per scheduler loop iteration. Each `run_comparison_round` also does `db.matches.find({}).to_list(100000)`.

**Fix**: Add a `primary_category` field to matches (denormalized from papers) and query `{"primary_category": cat}` directly. Or use the `shared_categories` array with `$in` queries.

### 3. Scheduler match count update: O(categories × matches) — HIGH

```python
# scheduler.py lines 117-132 — runs EVERY loop iteration
for cat in active_cats:
    async for m in db.matches.find({"completed": True, ...}):  # full scan per cat
        if m["paper1_id"] in cat_paper_ids and m["paper2_id"] in cat_paper_ids:
```

100 categories × full match scan = 100 full scans per loop. This is the most wasteful pattern.

**Fix**: Store match counts on the category status or use aggregation pipelines.

### 4. Config: all settings in one document — MEDIUM

```python
settings.get("active_categories", ["cs.RO"])    # single global settings doc
settings.get(f"last_fetch_at_{cat}")             # dynamic keys per category
```

At 100 categories, the settings document grows to 100+ `last_fetch_at_*` keys. MongoDB document size limit is 16MB so it won't break, but it's messy.

### 5. BT computation: O(iterations × papers × matches) — LOW risk

The BT solver does 50 iterations over all papers and their matches. At 50 papers × 50 avg matches × 50 iterations = 125K operations per category. At 100 categories this is 12.5M total — still fast (< 1 second).

### 6. Memory: all papers + matches in RAM — MEDIUM

The cache holds all papers (minus full_text/abstract) and all matches in memory. At 100 categories × 50 papers = 5,000 papers and ~500K matches, memory usage would be ~200-400MB. Manageable but worth monitoring.

---

## Action Plan from Architectural Feedback

### P0 — Do Now (enables scaling)

#### 1. Index matches by category for O(1) lookup
- Add `primary_category` field to match documents (denormalized)
- Backfill existing matches
- Replace all full-scan-then-filter patterns with indexed queries
- **Files**: `scheduler.py`, `leaderboard.py`
- **Impact**: Turns O(N×M) into O(M/N) for N categories, M matches

#### 2. Pre-index matches in cache refresh
- Build `paper_id → [match_indices]` map once per refresh
- Look up matches per category via paper_id set intersection
- **Files**: `leaderboard.py:_refresh_cache()`

### P1 — Do Before Scaling to 20+ Categories

#### 3. Tournament registry (feedback item #1, #3)
Create a `tournaments` collection:
```json
{
  "tournament_id": "cat=cs.RO|mode=standard",
  "category": "cs.RO",
  "mode": "standard",
  "status": "active",
  "goals": {"min_matches": 5, "ci_target": 12, "top_k": 10},
  "stats": {"papers": 51, "matches": 2148, "goals_met": true},
  "created_at": "...", "updated_at": "..."
}
```
Scheduler iterates over active tournaments, not `CATEGORIES` dict.
- **Files**: new `models/tournament.py`, refactor `scheduler.py`, `config.py`
- **Solves**: cost control, operational control, future extensibility (prediction modes, cohorts)

#### 4. Derive eligibility, don't enroll (feedback item #2)
Already the case for primary categories (`categories.0 == cat`). For secondary tournaments, use `categories CONTAINS tag`. No enrollment needed.
- **Status**: Already correct. Just document the contract.

#### 5. Minimum viable tournament threshold (feedback item #7)
Only activate tournaments for tags with `n_papers >= 8`. Show "insufficient data" for smaller tags.
- **Files**: scheduler activation logic, leaderboard UI
- **Simple**: one config value + one check

#### 6. Track prompt/model versions in match records (feedback item #8)
Add `prompt_version` hash to match documents. Currently we store `model_used` but not which prompt version was used.
```json
"judge": {
  "provider": "openai",
  "model": "gpt-5.2",
  "prompt_hash": "a1b2c3"
}
```
- **Files**: `scheduler.py` (match creation), `llm.py`
- **Simple**: hash the prompt text, store alongside model_used

### P2 — Nice to Have

#### 7. BT score proximity for matchmaking (feedback item #4)
Replace win-rate similarity with BT score proximity. The current heuristic works but BT-based pairing is more information-theoretically efficient.
- **Files**: `scheduler.py:_select_pairs()`
- **Complexity**: Medium — need to maintain running BT scores between rounds
- **Recommendation**: Keep current heuristic until we see empirical issues. Win-rate similarity is a reasonable proxy for BT proximity and is much simpler.

#### 8. BT regularization for small tournaments (feedback item #5)
Add pseudo-count prior (e.g., 1 virtual win + 1 virtual loss against mean-strength baseline) for tournaments with < 10 papers.
- **Files**: `ranking.py:calculate_bradley_terry()`
- **Simple**: add configurable prior strength

#### 9. Show primary/global score alongside secondary score (feedback item #6)
Already partially implemented (Global/Local toggle). Could enhance with a permanent "primary rank" badge.
- **Status**: Mostly done.

#### 10. Cross-category as separate global tournament, not normalization (feedback item #9)
Already the approach. The "All Papers" view computes BT from all matches, not by normalizing per-category scores.
- **Status**: Correct. No action needed.

#### 11. Tags as views by default, tournaments on-demand (feedback item #10)
Current piggyback (Option C) already treats tags as views. On-demand tournaments (Option B) would be the next step.
- **Status**: Correct hierarchy already in place.

---

## Summary

| Priority | Item | Effort | Impact at 100 cats |
|----------|------|--------|---------------------|
| P0 | Index matches by category | Small | Eliminates O(N×M) scans |
| P0 | Pre-index cache matches | Small | 100x faster cache refresh |
| P1 | Tournament registry | Medium | Operational control |
| P1 | Min viable tournament | Small | Cost control |
| P1 | Prompt version tracking | Small | Comparability |
| P2 | BT-based matchmaking | Medium | Marginal quality gain |
| P2 | BT regularization | Small | Better small tournaments |
| Already done | Eligibility derivation, global/local toggle, tags-as-views | — | — |
