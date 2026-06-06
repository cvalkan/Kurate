# Cross-Category Tournament Exploration

## Current System

Papers are assigned to tournaments based on their **primary category** (`categories[0]`). A paper with categories `["physics.comp-ph", "physics.chem-ph", "cs.AI"]` only participates in the `physics.comp-ph` tournament. Its `physics.chem-ph` and `cs.AI` tags are metadata only.

### Current Data

| Primary Category | Papers | Matches |
|---|---|---|
| cs.RO | 51 | ~2100 |
| cs.DC | 50 | ~2100 |
| econ.GN | 50 | ~2000 |
| physics.comp-ph | 51 | ~2000 |
| q-bio.BM | 50 | ~2000 |

52 unique tags across 250 papers. The tag `physics.chem-ph` appears on 7 papers, but those 7 papers span 3 different primary categories (physics.comp-ph, q-bio.BM, cs.DC). When viewed through the tag filter, they only have **8 matches** between them (from occasional within-category overlap), vs. **100+ matches each** in their primary tournaments.

## The Problem This Solves

The tag-filtered leaderboard currently relies on incidental overlaps — two `physics.chem-ph` papers can only be compared if they happen to share the same primary category. For tags that cut across multiple primary categories, the filtered leaderboard has very sparse data:
- Few head-to-head matches → wide confidence intervals
- Unreliable rankings within the filtered set
- Win rates based on 0-4 matches vs. 50-150 in the primary view

## Proposed Approach: Secondary Category Tournaments

### How It Would Work

1. **Paper enrollment**: At fetch time, each paper is enrolled in tournaments for ALL its categories, not just the primary one.
2. **Separate match pools**: Each category tournament has its own independent match pool. A paper's match in `physics.chem-ph` is separate from its match in `physics.comp-ph`.
3. **Match tagging**: Each match document gets a `tournament_category` field: `{"paper1_id": "...", "paper2_id": "...", "tournament_category": "physics.chem-ph"}`.
4. **Scheduler changes**: The scheduler iterates over all tags that have 2+ papers (not just the 5 primary categories) and runs matchmaking for each.

### Key Files to Modify

| File | Change |
|---|---|
| `services/scheduler.py` | `_scheduler_loop`: iterate over all category tags (or a configurable subset), not just `CATEGORIES` keys. `run_comparison_round`: accept `tournament_category` param, scope paper lookup to papers with that tag (not just `categories.0`). |
| `services/scheduler.py` | `_check_goals_met`: scope to `tournament_category` when counting matches. |
| `core/config.py` | Add a `SECONDARY_CATEGORIES` config or a setting for which tags should have active tournaments. |
| `routers/leaderboard.py` | Tag-filtered leaderboard: prefer matches tagged with `tournament_category` matching the selected tag, instead of relying on incidental primary-category overlaps. |
| Match schema | Add `tournament_category` field to match documents. |

### Scheduling Strategy Options

**Option A: Full parallel** — Run secondary tournaments alongside primary ones, same scheduling cadence. Every category tag with 2+ papers gets its own tournament.
- Pros: Complete coverage, every filtered view has rich data.
- Cons: Expensive. 52 tags × many matches = high cost.

**Option B: On-demand** — Only run secondary tournaments for tags the admin explicitly enables, or that have been viewed in the tag filter.
- Pros: Cost-controlled, focused on tags users actually care about.
- Cons: Delay before filtered leaderboards become useful.

**Option C: Piggyback on primary** — When comparing two papers in a primary tournament, if they share a secondary tag, record the match result for that tag's tournament as well (zero additional LLM cost).
- Pros: Free calibration data for secondary tags.
- Cons: Coverage depends on primary overlap; tags that span many primary categories may still have sparse data.

**Recommendation: Start with Option C, add Option B later.** Option C is essentially free — just tag existing matches with the secondary categories they happen to cover. Then add Option B for important tags that still need dedicated matches.

## Cost Implications

| Scenario | Additional matches/day | Est. cost/day |
|---|---|---|
| Option C (piggyback) | 0 | $0 |
| Option B (5 secondary tags) | ~50-100 | ~$1-2 |
| Option A (all 52 tags) | ~500-1000 | ~$10-20 |

(Estimates based on current ~$0.02/match for full-text comparisons.)

## Potential Issues

1. **Score comparability**: A paper's score in `physics.chem-ph` tournament is independent of its score in `physics.comp-ph`. This is correct and intended — the paper's relative ranking among chemistry papers is a different question than its ranking among computational physics papers.

2. **Match explosion**: With 52 tags and some papers having 5+ tags, a naive "all-pairs" approach could create far more matches than needed. The adaptive scheduler's CI-based convergence naturally limits this.

3. **Which tournament's score to show?**: When a paper appears in a tag-filtered view, should it show its secondary-tournament score or its primary-tournament score? Answer: the secondary-tournament score, since that reflects its performance against peers with the same tag.

4. **Experiment isolation**: The existing `mode` field on matches (standard/prediction_abstract/prediction_full_text) must not collide with the new `tournament_category` field. These are orthogonal dimensions.

## Implementation Estimate

- **Option C (piggyback)**: Small change — add `tournament_categories` array to match documents after each comparison. ~1 file change.
- **Option B (on-demand)**: Medium change — extend scheduler to accept arbitrary category tags, add admin UI for enabling secondary tournaments. ~3-4 file changes.
- **Option A (full parallel)**: Mostly the same as B, but with auto-enrollment of all tags. Risk of runaway costs if not gated.
