# Sub-topic-aware Matchmaking — Design Doc

## Goal
Per arxiv category, bias matchmaking toward topically-related pairs to
improve ranking precision, while keeping a coherent global scale.

## Option A (preferred, simplest): use arxiv secondary categories
Arxiv papers already carry primary + secondary categories (cs.LG primary
with cs.CL, stat.ML secondaries). No classifier, no taxonomy admin.

Matchmaking budget per paper:
- 60% shared-secondary — opponents sharing >=1 secondary category
- 30% primary-only    — same primary category, no secondary overlap
- 10% cross-primary   — global anchors for scale calibration

Implementation:
- Already stored on paper doc (`categories[]`).
- Compound index `(primary, secondaries, comparisons)` enables bucket sampling.
- No new LLM calls, no shadow-mode rollout needed — ship behind a flag.

Tradeoffs: coarser granularity than custom sub-topics (20-30 buckets vs
arxiv's ~200), but free and requires zero extra infra.

## Option B (later, if A insufficient): LLM sub-topic classifier
Custom ~20-30 label taxonomy per arxiv category, assigned via an extra
JSON field in the existing summarization prompt. Same 70/20/10 split.
Use if per-label ρ on Option A plateaus below the Fixed benchmark ceiling.

## Expected wins (both options)
- Per-sub-topic ρ increases (Fixed precedent: 0.55 → 0.65).
- Global ranking stays coherent via anchor bucket.
- Enables sub-topic / secondary-category filters on the leaderboard UI.

## Rollout
1. Ship Option A behind a feature flag on cs.AI. Compare 2-week A/B.
2. If gains are small, add Option B classifier for categories that
   lack granular secondaries.

## Risks
- Secondary categories are author-assigned and sometimes sparse/noisy.
- Small secondary overlaps → fall back to primary-only bucket automatically.
