# Orphan Rankings — Root Cause Analysis & Action Plan

## Problem

Rankings entries can become orphaned (no matching paper doc) or duplicated (same arxiv paper, two UUIDs). This causes:
- Ghost entries on the leaderboard with high CI that can never converge
- Inflated paper counts
- Wasted LLM matches (the infinite loop bug discovered during sigma migration testing)

## Scope

### Production (checked via public API)
- **10 duplicate titles** across 18 categories (minor — likely arxiv revisions)
- **350 papers with 1-9 matches** — real papers that Wilson prematurely converged, NOT orphans. The sigma migration handles these correctly.
- **0 zero-match papers** — production seeding works correctly

### Preview (checked via direct DB access)
- **420 orphan ranking entries** (no paper doc)
- **394 duplicate titles** in rankings
- **159 papers with no ranking entry**
- ~40x worse than production. Caused by follower optimization skipping `_startup_seed_rankings`

## Root Cause

Two independent issues:

**1. Category cleanup deletes papers but not rankings** (`server.py::_deferred_startup`)
When papers with invalid primary categories are removed, their ranking entries persist as ghosts.

**2. Re-fetched papers get new UUIDs**
When a paper is deleted (by cleanup or other migration), its `arxiv_id` unique index is freed.
The next fetch cycle creates a new paper doc with a new UUID for the same arxiv paper.
The old ranking entry (orphaned) and the new ranking entry (fresh) coexist = duplicate.

## Already-Deployed Fixes (zero data loss)

These are already in the codebase from the sigma migration work:

1. **`_select_pairs` guard** — Papers without ranking entries are excluded from pair selection. Prevents the infinite match loop entirely.

2. **`insert_ranking_for_paper` — removed summary check** — The function no longer validates Claude summaries (the caller is responsible via matchability filter). When a match completes for a paper without a ranking, the handler can now successfully create the ranking entry.

## Remaining Action Items (all additive, zero deletion)

### Item 1: Seed ranking at summary generation time

**Currently**: Rankings are seeded by `_startup_seed_rankings` on leader restart.
New papers wait for the next restart to become matchable.

**Proposed**: Call `insert_ranking_for_paper` immediately after a paper's summary is generated
in the fetch loop. The paper enters rankings the moment it becomes matchable.

**Location**: `scheduler.py::_generate_paper_summaries`, after successful summary save.

**Risk**: None — `insert_ranking_for_paper` uses `upsert=True`, so duplicate calls are idempotent.

### Item 2: Seed ranking in the comparison round (belt-and-suspenders)

**Currently**: `_select_pairs` filters out papers not in rankings.

**Proposed**: Before filtering, seed any missing papers into rankings:
```python
# Before filtering, seed any papers missing from rankings
for p in all_papers:
    if p["id"] not in paper_stats:
        paper_doc = await db.papers.find_one({"id": p["id"]}, {"_id": 0})
        if paper_doc:
            await insert_ranking_for_paper(db, paper_doc)
            # Re-read the fresh ranking
            rdoc = await db.rankings.find_one({"paper_id": p["id"]}, {...})
            if rdoc:
                paper_stats[p["id"]] = {...}
# Then filter
all_papers = [p for p in all_papers if p["id"] in paper_stats]
```

**Risk**: Adds a few DB reads per round for unranked papers. Negligible cost, and only triggers
for papers that somehow missed Item 1.

### Item 3: Log orphan rankings for visibility (no deletion)

Add a lightweight check on leader startup that COUNTS orphan rankings per category and logs them.
No deletion, no modification — just visibility for monitoring.

```python
async def _startup_log_orphan_rankings():
    orphan_count = 0
    async for cat in db.rankings.aggregate([...group by category, check paper exists...]):
        if cat["orphan_count"] > 0:
            logger.warning(f"[orphan-rankings] {cat['_id']}: {cat['orphan_count']} rankings with no paper doc")
            orphan_count += cat["orphan_count"]
    if orphan_count:
        logger.warning(f"[orphan-rankings] Total: {orphan_count} orphan rankings across all categories")
```

## Deferred (manual decision, not automated)

### Orphan cleanup
Deleting the 420 orphan rankings on preview (or any on production) is a manual admin decision.
The matches are preserved in the `matches` collection and can be replayed via full rerank.
A cleanup endpoint can be added to the admin panel if desired.

### Category cleanup fix
Making the category cleanup migration also remove rankings when deleting papers.
Deferred because: if a paper is temporarily miscategorized, the deletion would be permanent.
Better to leave orphan rankings as harmless ghost entries than risk losing valid match history.

### Duplicate merging
Merging match history from orphan rankings into their replacement (same arxiv_id, new UUID).
Deferred because: requires full category rerank, and the two TrueSkill trajectories may not
be coherently mergeable. Safer to let the replacement accumulate its own match history.
