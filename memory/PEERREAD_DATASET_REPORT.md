# PeerRead ACL 2017 Dataset Quality & Suitability Report

## 1. Source & Selection

### Source
The [PeerRead dataset](https://github.com/allenai/PeerRead) from AllenAI provides peer reviews from several top-tier AI/NLP venues. Our import uses the ACL 2017 subset.

### Selection
- **80 papers** from ACL 2017
- All papers with ≥2 reviews were included (no stratified sampling, no filtering)
- Full PDF text extracted for all 80 papers

### Why ACL 2017?
PeerRead is one of the few public datasets with actual reviewer scores paired with paper text. ACL 2017 was chosen for its completeness (all papers have 2-3 reviews with numerical scores).

## 2. Dataset Properties

| Property | PeerRead ACL 2017 | ICLR (for comparison) |
|---|---|---|
| **Papers** | 80 | 469 (8 topics) |
| **Year** | 2017 | 2024–2025 |
| **Rating scale** | 1–5 (5 integer values) | 1–10 (6 values: 1,3,5,6,8,10) |
| **Reviews per paper** | 2–3 (48 with 2, 32 with 3) | 4–5 |
| **Decision tiers** | **None** (all null) | Oral/Spotlight/Poster/Reject |
| **Reviewer identity** | Positional (same as ICLR) | Positional |
| **Distinct positional reviewers** | 3 | 4–6 per topic |

### Rating Distribution

| Rating | Count | Fraction |
|---|---|---|
| 4 (Good) | 96 | 50.0% |
| 3 (Borderline) | 49 | 25.5% |
| 2 (Below Average) | 37 | 19.3% |
| 1 (Poor) | 6 | 3.1% |
| 5 (Excellent) | 4 | 2.1% |

**Half of all ratings are 4 (Good)** — the scale is even more concentrated than ICLR's. Combined with only 5 integer values, this produces a **51.4% tie rate** (vs ICLR's 39%).

### Score Properties

| Metric | Value |
|---|---|
| Avg score | 3.31 (std 0.76) |
| Score range | 1.3–4.5 |
| Non-tie gap (mean) | 1.20 (on 1–5 scale) |
| Non-tie gap (median) | 1.0 |
| 83% of non-tie gaps are exactly 1 point | Only 2 possible non-adjacent ratings (1-3, 1-4, 1-5, 2-4, 2-5, 3-5) |

### Reviewer Structure

3 positional reviewers:
- **Reviewer_1**: 80 papers (all)
- **Reviewer_2**: 80 papers (all)
- **Reviewer_3**: 32 papers (40%)

3 overlap pairs: (R1,R2) = 80 shared, (R1,R3) = 32 shared, (R2,R3) = 32 shared.

The human BT ranking is dominated by R1 and R2 (who review everything). R3 adds a third voice for 40% of papers. With only 2-3 reviewers, the human consensus is inherently noisy.

## 3. AI Coverage

| Data | Count |
|---|---|
| Full text | 80/80 (100%) |
| AI thinking summaries | 80/80 (100%) |
| Single-item scores | 79/80 (99%) |
| Thinking matches | 1,118 (27.9/paper) |
| Total matches (all modes) | 19,284 |

Good coverage — more thinking matches per paper (27.9) than any ICLR topic except iclr-llm (22.9).

## 4. Key Quality Issues

### 4a. No Decision Tiers
PeerRead ACL 2017 has no accept/reject decisions. All 80 papers have `decision: null`. This means:
- **No Committee comparison** (AI vs Committee, Human vs Committee) — these columns are blank
- **No difficulty stratification** — can't classify pairs as cross-tier/adjacent/within-tier
- **No tier accuracy metric** — can't measure if AI picks the higher-tier paper

The only ground truth is the reviewer scores themselves, making all comparisons self-referential.

### 4b. Only 2–3 Reviewers
With 2 reviewers per paper (60% of papers), the human BT ranking is built from just 2 opinions. This is fundamentally noisier than ICLR's 4–5 reviewers:
- **Higher tie rate**: 51.4% (vs ICLR 39%) — more than half of pairwise comparisons produce identical scores
- **No tiebreaker**: when R1 and R2 disagree, there's no R3 to resolve it (for 60% of papers)
- **Selection bias**: the 40% of papers with 3 reviewers may be systematically different (more controversial?) than those with 2

### 4c. 2017 NLP vs Modern AI Judging
The AI judges (GPT-5.2, Opus 4.6, Gemini 3 Pro) were trained on modern ML literature. ACL 2017 papers reflect different:
- **Research norms**: pre-transformer NLP, different evaluation standards
- **Writing conventions**: 2017 paper formats, citation styles
- **Quality signals**: what constituted "good NLP research" in 2017 differs from 2024

This temporal mismatch likely contributes to the low BT correlation (ρ=0.434 vs Individual, compared to ICLR's 0.735).

### 4d. Coarse 1–5 Scale
5 integer values with 50% of ratings at 4. The effective rating resolution is ~3 distinguishable levels (below average, borderline, good), compared to ICLR's ~4 levels (reject, borderline, poster, strong accept).

## 5. Benchmark Results

| Metric | PeerRead | ICLR average | Gap |
|---|---|---|---|
| AI-H pairwise (coin-flip) | 67.8% | ~75% | -7pp |
| H-H pairwise (coin-flip) | 86.7% | ~73% | +14pp |
| BT AI vs Individual | **0.434** | ~0.78 | **-0.35** |
| BT AI vs Majority | 0.434 | ~0.80 | -0.37 |
| BT AI vs Committee | — | ~0.76 | N/A |
| Tie rate | 51.4% | 39% | +12pp |

### Anomalies
1. **H-H agreement (86.7%) is much higher than ICLR's (~73%)** — likely inflated by the 2-reviewer double-filter bias: with only 2 reviewers, when both have a non-tie preference, they're comparing against their only peer, not a diverse panel. The selection toward agreement is stronger with fewer reviewers.

2. **AI-H BT (0.434) is dramatically lower than ICLR (0.78)** — the combination of temporal mismatch, no tiers, coarse scale, and 2-reviewer noise makes PeerRead the weakest dataset in our benchmark by far.

3. **AI-H agreement (67.8%) is still well above 50%** — the AI does have real signal even on 2017 NLP papers, just much less than on modern ML papers.

## 6. Suitability Assessment

### Strengths
1. **Independent validation** — different venue, field (NLP), and time period from ICLR. Tests generalizability.
2. **Complete AI coverage** — 100% text, summaries, and matches.
3. **High match density** — 27.9 thinking matches per paper, more than most ICLR topics.

### Weaknesses
1. **No decision tiers** — eliminates Committee comparison and difficulty stratification.
2. **Only 2–3 reviewers** — noisy human ground truth, inflated H-H agreement.
3. **Temporal mismatch** — 2017 NLP norms don't align with modern AI judging.
4. **Dominates size-weighted averages** — 1,118 thinking matches (largest in the benchmark) with the worst ρ, pulling weighted aggregates down.

### Verdict
**Useful as a stress test, not as a primary benchmark.** PeerRead tests whether AI judging generalizes to a different domain, era, and reviewing structure. The low ρ (0.434) is informative — it reveals the limits of our AI pipeline on out-of-distribution data. But it should not dominate aggregate metrics, which is why equal-weighting across datasets is the correct pooling approach.

### Recommendation
Consider **removing PeerRead from the pooled aggregate** and showing it separately as a "cross-domain validation" result, similar to how UAI 2024 is shown as a standalone dataset. This would make the ICLR-only aggregate cleaner (no outlier) while preserving the generalizability finding.
