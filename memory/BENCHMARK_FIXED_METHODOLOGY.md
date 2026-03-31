# Human vs AI Benchmark (Fixed) — Methodology

## Overview

This benchmark measures how well AI pairwise judgments agree with human expert reviewers on the same paper pairs. It uses 8 ICLR 2025 topical datasets (469 papers, ~6,800 controlled pairs) where 3 AI models (GPT-5.2, Claude Opus, Gemini 3 Pro) independently judge which paper has higher scientific impact, and their verdicts are compared against human reviewer scores and program committee decisions.

## Data

**Papers**: 469 papers across 8 ICLR 2025 topical subsets (Code Generation, Fairness, LLMs, Molecules, Optimization, Optimal Transport, PDEs & Dynamical Systems, Protein Science). Each paper has 4–8 expert reviewers with numerical scores on a 1–10 scale.

**AI Matches**: Each paper pair is judged by 3 AI models in round-robin, with multiple rounds. AI matches use the paper's abstract + AI-generated impact summary as input. The **AI majority vote** (most common winner across all AI judgments for a pair) determines the AI's verdict.

**PeerRead ACL 2017 is excluded** — it uses a coarser 1–5 rating scale with only 2–3 reviewers per paper, producing structurally different agreement patterns.

## Filters

| Filter | Setting | Rationale |
|---|---|---|
| Expert eligibility | **No minimum** — all reviewers included | Every reviewer contributes to pairs involving their rated papers |
| Minimum preferences per pair | **≥1** non-tie expert preference | A pair enters the controlled set if any expert distinguishes the two papers |
| Expert majority threshold | **≥1 vote** — single non-tie vote counts as majority | Consistent with the ≥1 preference filter |
| Tier mapping | **Rankable only**: Oral > Spotlight > Poster > Reject | Withdrawn and desk-rejected papers have no meaningful tier → treated as ties |
| Within-tier matches | **Included** — subsampled to natural proportion | Tests AI on the full difficulty spectrum, not just easy cross-tier pairs |
| Datasets | **ICLR only** (no PeerRead ACL) | Ensures consistent rating scale and reviewer count |

## Controlled Pair Sets

- **Controlled pairs (CF)**: All pairs where (a) at least one expert rated both papers AND (b) the AI judged the pair. Includes pairs where all experts gave the same score to both papers (all-tie pairs). This is the denominator for "ties included" metrics.

- **Controlled pairs (ties excluded)**: Pairs where a **clear expert majority** exists (more than half of non-tied experts prefer the same paper). This is the denominator for "ties excluded" metrics. The difference from CF = pairs with no clear majority (all-tie + split votes).

## Metrics

### Pairwise Agreement Table

**Three rows:**

1. **All pairs (ties = coin flip)**: Every controlled CF pair is included. When the ground truth is tied (expert tie, no majority, or same program committee tier), agreement is scored as **0.5** (the expected value of a fair coin flip). This avoids excluding hard cases.

2. **All pairs (ties excluded)**: Only pairs where the ground truth has a clear answer. Tied pairs are dropped entirely. Higher rates than row 1 because the ambiguous cases are removed.

3. **Equal-weighted (coin flip)**: Concordance averaged per dataset (each dataset weighted equally regardless of size). "Per reviewer" means each expert's agreement with AI is computed separately, then averaged.

**Six columns:**

| Column | AI ground truth | Human ground truth | Unit of comparison |
|---|---|---|---|
| AI vs Human | AI majority vote | Each expert's preference | Per (expert, pair) |
| Human vs Human | Expert A's preference | Expert B's preference | Per (expert-pair, pair) |
| AI vs Majority | AI majority vote | Expert majority vote | Per pair |
| Human vs Majority (LOO) | One expert's preference | LOO majority (that expert excluded) | Per (expert, pair) |
| AI vs Committee | AI majority vote | ICLR program committee tier | Per pair |
| Human vs Committee | Each expert's preference | ICLR program committee tier | Per (expert, pair) |

### Tie Definitions (differ by column)

- **AI/H vs Human**: Tie = reviewer gave both papers the same score. ~24% of expert-pair comparisons.
- **AI/H vs Majority**: Tie = no clear majority among non-tied experts (split vote or all tied). ~9% of pairs.
- **AI/H vs Committee**: Tie = both papers have the same acceptance tier (e.g., Poster vs Poster) or a non-rankable tier (Withdrawn, Desk Rejected). ~52% of pairs.

### Ranking Correlation Table

Bradley-Terry scores are computed from pairwise preferences (AI or human), producing a ranking over papers. Spearman ρ and Kendall τ measure rank agreement between different rankings.

**AI vs Human correlations:**
- **AI vs Individual aggregate**: AI BT ranking vs human BT ranking (from all individual expert votes pooled as separate matches)
- **AI vs Avg Rating**: AI BT ranking vs simple average of reviewer scores
- **AI vs Majority**: AI BT ranking vs BT ranking from expert majority votes (one match per pair)
- **AI vs Committee (ICLR PC)**: AI BT ranking vs program committee tier scores

**Human internal correlations (LOO):**
Each expert's BT ranking (from their own pairwise preferences) is compared against:
- LOO individual aggregate (all other experts' votes pooled)
- LOO average rating (other experts' mean scores)
- LOO majority (other experts' majority vote BT ranking)
- Committee tier scores

These are averaged across all experts to produce a single number.

## Within-Tier Subsampling

The extended benchmark includes **within-tier matches** (e.g., Poster vs Poster) that the legacy benchmark excluded. These are harder for both AI and humans (no tier signal). To avoid over-representing within-tier pairs (which are more numerous), within-tier AI matches are subsampled to match the **natural proportion** of within-tier vs cross-tier paper pairs in each dataset.

The subsampling uses a **deterministic seed** (`42 + sha256(dataset_id)`) so results are reproducible across server restarts.

## Reproducibility

All controlled CF pairs are exported as CSV files:
- `matches_extended.csv`: 6,833 pairs (ICLR only, with within-tier)
- `papers.csv`: 469 papers with individual reviewer scores and committee decisions

The pair counts may vary by ±5 from the live page due to the within-tier subsampling seed, which affects which specific AI matches are included. This can cause ~50 borderline AI majority votes to flip, producing ±0.5% variation in agreement rates.

The "coin flip" row uses the **expected value (0.5)** for tied pairs, not actual random flips. External reproductions using actual random flips will see additional variation of ±0.5–1.0% depending on the random seed.
