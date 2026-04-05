# Pair Dedup Scaling Plan

## Problem
`run_comparison_round` loads ALL matches for a category into Python memory to build a `compared_pairs` set. This is used by `_select_pairs` to avoid generating repeat matches.

| Category size | Matches | Memory for compared_pairs |
|---|---|---|
| 50 papers | 1.2K | ~100KB |
| 700 papers | 20K | ~2MB |
| 1,600 papers | 40K | ~4MB |
| 5,000 papers | 200K+ | ~20MB (risk zone) |
| 100,000 papers | 5M+ | ~500MB (OOM) |

## Current Implementation (scheduler.py lines 1031-1038)
```python
all_matches = await collect_all(db.matches.find(
    {"completed": True, "failed": {"$ne": True}, "primary_category": category},
    {"_id": 0, "paper1_id": 1, "paper2_id": 1},
))
compared_pairs = set()
for m in all_matches:
    compared_pairs.add(tuple(sorted([m["paper1_id"], m["paper2_id"]])))
```

Then `_select_pairs` checks `if pair_key in compared_pairs` for each candidate.

## Proposed Fix

### 1. Normalize pair order on write
When saving matches, always store `paper1_id < paper2_id` (lexicographic). This makes the compound index work without `$or`.

```python
# In run_comparison_round, before saving:
p1, p2 = sorted([p1_id, p2_id])
```

**Migration**: One-time script to normalize existing matches:
```python
async for m in db.matches.find({"paper1_id": {"$gt": "$paper2_id"}}):
    await db.matches.update_one({"_id": m["_id"]}, {"$set": {
        "paper1_id": min(m["paper1_id"], m["paper2_id"]),
        "paper2_id": max(m["paper1_id"], m["paper2_id"]),
    }})
```

### 2. Add compound index
```python
db.matches.create_index(
    [("primary_category", 1), ("paper1_id", 1), ("paper2_id", 1)],
    name="pair_dedup_idx",
    partialFilterExpression={"completed": True, "failed": {"$ne": True}},
)
```

### 3. Replace in-memory set with batch DB queries
```python
async def _get_compared_opponents(paper_id: str, category: str, candidates: list[str]) -> set:
    """Return which candidates have already been compared with paper_id."""
    # paper_id is always the smaller ID in the pair (normalized)
    already = set()
    for batch in [candidates[i:i+100] for i in range(0, len(candidates), 100)]:
        lower = [c for c in batch if c < paper_id]
        upper = [c for c in batch if c >= paper_id]
        if lower:
            async for m in db.matches.find(
                {"primary_category": category, "paper2_id": paper_id, "paper1_id": {"$in": lower},
                 "completed": True, "failed": {"$ne": True}},
                {"_id": 0, "paper1_id": 1},
            ):
                already.add(m["paper1_id"])
        if upper:
            async for m in db.matches.find(
                {"primary_category": category, "paper1_id": paper_id, "paper2_id": {"$in": upper},
                 "completed": True, "failed": {"$ne": True}},
                {"_id": 0, "paper2_id": 1},
            ):
                already.add(m["paper2_id"])
    return already
```

### 4. Update `_select_pairs` to use DB queries
Instead of receiving `compared_pairs: set`, each needy paper queries its compared opponents on demand. Memory usage becomes O(candidates_per_round) ≈ O(100) regardless of category size.

## Trade-offs

| Aspect | Current | Proposed |
|---|---|---|
| Memory | O(all_matches) | O(candidates_per_round) ≈ O(100) |
| DB reads per round | 1 bulk read | ~10-50 indexed queries |
| Latency per round | ~100ms (memory) | ~300-500ms (DB round-trips) |
| Scales to | ~5K papers | Unlimited |
| Regression risk | N/A | Medium (pair dedup is critical) |

## When to Implement
- **Current max category**: 1,600 papers (cs.RO) — well within safe limits
- **Trigger**: When any category approaches 3,000 papers
- **Estimated effort**: 1 day (including migration + testing)
- **Testing**: Replay existing matches, verify zero repeat pairs generated

## Validation Plan
1. Run migration on preview with production data snapshot
2. Verify `compared_pairs` set from old method matches DB query results exactly
3. Run 10 comparison rounds, verify no repeat matches
4. Deploy with old method as fallback (feature flag)
5. Monitor for 24h, remove fallback
