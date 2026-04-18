# Sub-topic-aware Matchmaking — Design Doc

## Goal
Per arxiv category, bias live-leaderboard matchmaking toward same-sub-topic
pairs to improve ranking precision, while keeping a coherent global scale.

## Sub-topic assignment (one-time per paper)
- Admin-editable taxonomy of ~20-30 labels per arxiv category.
- Classifier runs inside the existing summarization LLM call — add a JSON
  field `{primary_label, secondary_labels[]}` to the prompt; no extra call.
- Cache `primary_label`, `secondary_labels[]`, `embedding` on paper doc.
- Fallback: cosine similarity on cached embedding when a label pool is <10.

## Matchmaking budget split (per paper, per fetch cycle)
- 70% intra-label  — opponents sharing `primary_label`
- 20% adjacent    — opponents in `secondary_labels` (either direction)
- 10% cross-label — random same-category anchors (global calibration)

The 10% anchor prevents TrueSkill scale divergence across sub-topics —
intra-label tournaments alone produce incomparable ratings.

## Implementation notes
- Compound index: `(category, primary_label, comparisons)` → O(log n) selection.
- Weighted reservoir sampling via three `$sample` buckets per paper.
- In-memory "underplayed-per-label" pool refreshed every 5 min.
- Shadow mode first: classify + store labels without changing matchmaking.

## Expected wins
- Per-sub-topic ρ jumps (Fixed benchmark precedent: 0.55 → 0.65).
- Global ranking stays coherent via 10% anchor.
- Enables sub-topic filter chips on the leaderboard UI.

## Rollout
1. Phase 1: classifier + storage, shadow mode, validate labels.
2. Phase 2: 70/20/10 matchmaking on cs.AI behind feature flag, 2-week A/B.
3. Phase 3: roll to all categories, add UI filter chips.

## Risks
- Taxonomy drift (straddling papers) → secondary_labels + embedding fallback.
- Cold-start for new labels → 10% anchor keeps them ranked until pool fills.
- Small sub-topics (<10 papers) → embedding-nearest fallback.
