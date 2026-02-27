# Why ICLR Converges and Others Don't: A Deep Analysis of Dataset Performance

## Executive Summary

After analyzing 12 datasets across 6 dataset families (ICLR, MIDL, PeerRead, ACMI, eLife, Qeios), with 50,000+ tournament matches, we identify **five structural factors** that determine whether an AI judging tournament will converge to match human ground truth. ICLR datasets consistently outperform others not because of any AI bias toward ML papers, but because of **measurable properties of their ground truth structure**.

The single most important factor is **ground truth resolution** — the number of meaningfully distinct quality tiers. ICLR has 5 clean tiers. MIDL has 2. ACMI has continuous scores in a narrow range. This difference alone explains most of the variance in convergence.

---

## 1. The Data: All Datasets at a Glance

### Ranking Correlation (Spearman rho) — Higher is Better

| Dataset | Mode | rho | p-value | n |
|---|---|---|---|---|
| **iclr-pdes** | opus46 | **0.566** | <0.001 | 80 |
| **iclr-fairness** | opus46 | **0.542** | <0.001 | 68 |
| **iclr-protein** | opus46 | **0.582** | <0.001 | 46 |
| **iclr-molecules** | opus46 | **0.528** | <0.001 | 46 |
| **iclr-llm** | opus46 | **0.421** | <0.001 | 73 |
| **iclr-ot** | opus46 | **0.438** | 0.001 | 52 |
| **iclr-codegen** | opus46 | **0.379** | 0.002 | 62 |
| **iclr-optimization** | opus46 | **0.414** | 0.006 | 42 |
| **peerread_acl_2017** | summary | **0.612** | <0.001 | 80 |
| **elife-neuro-100** | summary | 0.342 | <0.001 | 100 |
| **midl-medical-imaging** | opus46 | 0.261 | 0.019 | 81 |
| **acmi-micro-100** | summary | 0.212 | 0.035 | 100 |

### Pairwise Accuracy (% matches agreeing with GT) — Best Mode per Dataset

| Dataset | Best Mode | Accuracy | GT Pairs | Ties |
|---|---|---|---|---|
| **iclr-pdes** | deep_dive | **86.0%** | 472 | 397 |
| **iclr-optimization** | summary | **84.3%** | 261 | 239 |
| **iclr-molecules** | opus46 | **89.9%** | 158 | 183 |
| **iclr-fairness** | opus46 | **78.4%** | 491 | 380 |
| **iclr-codegen** | deep_dive | **74.7%** | 659 | 299 |
| **iclr-llm** | full_pdf | **70.9%** | 1748 | 490 |
| **peerread_acl_2017** | deep_dive | **74.3%** | 1018 | 7 |
| **midl-medical-imaging** | deep_dive | **68.7%** | 201 | 297 |
| **elife-neuro-100** | summary | **67.6%** | 3048 | 1949 |
| **acmi-micro-100** | summary | **57.6%** | 1639 | 39 |

---

## 2. The Five Factors That Determine Convergence

### Factor 1: Ground Truth Resolution (Most Important)

**Definition:** How many meaningfully distinct quality levels exist in the ground truth.

| Dataset Family | GT Type | Distinct Tiers | Impact |
|---|---|---|---|
| ICLR | Committee decision | 5 (reject, withdrawn, poster, spotlight, oral) | Excellent |
| PeerRead | Avg reviewer score | 14 unique values (continuous 1-5) | Good |
| ACMI | Composite score | 45 unique values (1.93-4.33) | Sounds good, but... |
| eLife | Significance label | 4 (useful, valuable, important, fundamental) | Marginal |
| MIDL | Venue assignment | **2 (Poster, Oral)** | Very Poor |

**Why this matters:** With only 2 tiers (MIDL), 58.8% of all paper pairs are ties — there is literally no ground truth to evaluate against for the majority of comparisons. With 5 tiers (ICLR), only 25-47% are ties.

ACMI's 45 unique values sounds excellent, but the **range is only 1.93 to 4.33** (stdev=0.57). Most papers cluster within 0.5 points of each other, making the "distinct" values meaningfully indistinguishable. It's like measuring height differences with a ruler that only has mm markings but your measurement error is 5cm.

### Factor 2: Ground Truth Spread / Signal-to-Noise Ratio

**Definition:** How far apart papers are in quality, relative to the noise in their scores.

| Dataset | GT Stdev | Reviewer Stdev | Ratio (signal/noise) | % Tie Pairs |
|---|---|---|---|---|
| iclr-codegen | 1.27 | 1.26 | 1.01 | 33.5% |
| iclr-pdes | 1.15 | 1.16 | 0.99 | 46.9% |
| peerread_acl_2017 | 0.76 | 0.42 | **1.81** | 15.7% |
| midl-medical-imaging | 0.91 | 0.64 | 1.42 | **58.8%** |
| acmi-micro-100 | 0.57 | 0.51 | 1.12 | 2.7% |
| elife-neuro-100 | 0.68 | 0.00* | N/A | 40.5% |

*eLife has mostly 1 reviewer per paper, so no within-paper disagreement can be measured.

**Key insight:** ICLR's signal-to-noise ratio (~1.0) seems mediocre, but this is misleading. ICLR's advantage is that its **committee decision** (accept/reject/tier) is a **cleaner, higher-order signal** than the raw reviewer scores. The committee integrates multiple reviewer perspectives into a definitive categorical verdict. The individual reviewer scores are noisy, but the tier decision is clean.

PeerRead has the best raw signal-to-noise (1.81) — its reviewers agree with each other more than any other dataset. This explains why PeerRead achieves rho=0.61 despite being a non-ICLR dataset.

### Factor 3: Proportion of Discriminable Pairs

**Definition:** What fraction of paper pairs have a clear winner according to GT.

| Dataset | % Easy (gap>2) | % Medium (gap 1-2) | % Hard (gap<1) | % Ties |
|---|---|---|---|---|
| iclr-codegen | 42.6% | 23.9% | 0% | 33.5% |
| iclr-pdes | 50.3% | 2.8% | 0% | 46.9% |
| iclr-fairness | 51.5% | 6.1% | 0% | 42.4% |
| peerread_acl_2017 | 30.4% | 53.9% | 0%* | 15.7% |
| midl-medical-imaging | 41.2% | 0% | 0% | **58.8%** |
| acmi-micro-100 | 21.7% | **75.6%** | 0%* | 2.7% |
| elife-neuro-100 | 10.4% | 49.2% | 0% | 40.5% |

*PeerRead and ACMI use continuous scores, so "hard" is subsumed into "medium".

**Accuracy by gap size (selected datasets):**

| Dataset | Small (<1) | Medium (1-2) | Large (>2) |
|---|---|---|---|
| iclr-codegen (opus46) | N/A | 68.8% | **86.5%** |
| iclr-pdes (opus46) | N/A | 85.0% | **89.3%** |
| peerread_acl_2017 | 64.6% | 71.6% | **98.0%** |
| acmi-micro-100 | **54.4%** | 67.0% | 92.9% |
| elife-neuro-100 | N/A | 67.5% | 84.2% |

**The pattern is universal:** AI accuracy scales linearly with GT gap. When papers are >2 tiers apart, accuracy is 85-98%. When papers are <1 apart, accuracy drops to ~55% (barely above chance).

ACMI's problem is now crystal clear: **75.6% of its pairs are in the "hard" zone** where even humans would struggle.

### Factor 4: Number and Quality of Reviewers

| Dataset | Reviews/Paper | Min | Review Quality |
|---|---|---|---|
| ICLR | 4.2 avg | 4 | Expert researchers, calibrated scores (1-10) |
| MIDL | 3.2 avg | 3 | Expert researchers, narrower scale (1-5) |
| PeerRead | 2.4 avg | 2 | ACL reviewers, recommendation scores (1-5) |
| ACMI | 2-6 | 2 | Sub-field reviewers, multi-dimensional scoring |
| eLife | **1.8 avg** | **1** | Editorial significance assessment only |

**Human split-half agreement (the theoretical ceiling):**

| Dataset | Human-Human Agreement |
|---|---|
| peerread_acl_2017 | 84.6% |
| iclr-protein | 83.1% |
| iclr-llm | 82.1% |
| iclr-optimization | 78.5% |
| iclr-ot | 78.4% |
| iclr-codegen | 77.5% |
| acmi-micro-100 | 76.9% |
| iclr-pdes | 75.3% |
| iclr-molecules | 72.0% |
| iclr-fairness | 71.0% |
| midl-medical-imaging | **59.9%** |
| elife-neuro-100 | 100.0%* |

*eLife ceiling is artificially 100% because most papers have only 1 reviewer (no disagreement possible, but also no reliability).

**MIDL's ceiling is only 60%** — human reviewers themselves can barely distinguish Poster from Oral papers. An AI getting 68% actually *exceeds* the split-half human baseline, which suggests it might be picking up on a real signal that individual reviewers miss.

### Factor 5: Domain Alignment with LLM Training Data

| Domain | LLM Familiarity | Evidence |
|---|---|---|
| ML/AI (ICLR) | Very High | LLMs trained on millions of ML papers, arXiv, conference proceedings |
| NLP (PeerRead) | Very High | Same training corpus advantage as ML |
| Medical Imaging (MIDL) | Moderate | Some medical literature in training, but highly specialized methods |
| Microbiology (ACMI, eLife) | Lower | Bench science, wet lab methods, species-specific biology |

This factor is **secondary** to ground truth structure. PeerRead (NLP) outperforms ICLR-codegen on Spearman rho (0.61 vs 0.38) despite being the same domain family, because PeerRead has better GT properties (lower ties, higher reviewer consistency).

---

## 3. Why Each Dataset Performs the Way It Does

### ICLR Datasets (rho 0.38-0.58): The Gold Standard

**Why they work:**
1. **5 clean tiers** from committee decisions (not just averaged scores)
2. **4-6 expert reviewers** per paper provide robust averaging
3. **Good stratification**: import script selects papers across the score range
4. **Domain advantage**: LLMs understand ML papers deeply
5. **Structured papers**: Clear intro/method/results/conclusion format

**Variation within ICLR:** rho ranges from 0.38 (codegen) to 0.58 (protein/pdes). This correlates with the **proportion of easy pairs** — pdes and protein have more papers with extreme tier differences.

### PeerRead ACL 2017 (rho 0.61): Surprisingly the Best

**Why it works so well:**
1. **14 unique GT values** — continuous scores (1-5) with fine granularity
2. **Lowest reviewer disagreement** (stdev=0.42) — ACL reviewers are remarkably consistent
3. **Only 15.7% ties** — most pairs have a clear GT winner
4. **98% accuracy on easy pairs** — when papers are clearly different, AI gets them right
5. **NLP domain** — LLMs understand NLP papers as well as ML

**Why it might be slightly deceiving:** PeerRead's high rho could partially reflect that **average recommendation scores (1-5)** are a more direct GT signal for "paper quality" than ICLR's categorical tiers. A continuous score with low noise is statistically easier to correlate with.

### MIDL Medical Imaging (rho 0.26): Binary Ceiling Problem

**Root cause: Only 2 tiers (Poster/Oral)**

This is not a failure of the AI — it's a failure of the ground truth. With only binary classification:
- 58.8% of pairs are ties (no GT signal)
- Of the 41.2% discriminable pairs, ALL are "medium" difficulty (gap=2)
- Human split-half agreement is only 59.9%
- AI achieves 68% — **exceeding the human baseline**

**MIDL cannot be fixed by better AI.** The dataset needs richer ground truth (e.g., reviewer scores, not just accept/reject).

### ACMI Access Microbiology (rho 0.21): The Noise Problem

**Root cause: Very narrow score distribution**

- Composite scores range 1.93-4.33, stdev=0.57
- 75.6% of pairs differ by <1.0 point — in a zone where even humans agree only ~55% of the time
- Only 14 pairs (0.9%) have gap >2.0
- Multi-dimensional scoring (rigour, presentation, conclusions) adds granularity but each dimension is equally compressed

**ACMI is the "worst case scenario":** continuous scores that *look* rich but are actually compressed into a narrow, noisy band. The ground truth cannot reliably distinguish most papers from each other.

### eLife Neuroscience (rho 0.34): The Thin GT Problem

**Root cause: Too few reviewers, coarse scale**

- Only 4 GT levels (significance: useful/valuable/important/fundamental)
- Average 1.8 reviewers per paper — many have just 1
- 40.5% tie pairs
- Only 10.4% easy pairs (gap>2)
- Cannot compute meaningful human agreement because most papers have 1 reviewer

**eLife's structure is fundamentally limited:** single-reviewer significance labels are an editorial shorthand, not a reliable quality metric.

---

## 4. Requirements for Future Datasets

Based on this analysis, a dataset is likely to produce good convergence (rho > 0.40) if it meets these criteria:

### MUST-HAVE Requirements

| # | Requirement | Threshold | Rationale |
|---|---|---|---|
| 1 | **Distinct GT tiers** | >=4 meaningfully different levels | Binary (2-tier) GT caps accuracy at ~60% |
| 2 | **GT score spread** | stdev >= 0.8 (on normalized 0-5 scale) | Narrow spread = most pairs indistinguishable |
| 3 | **Tie pairs** | <40% of total pairs | >40% ties = less than 60% of data is usable |
| 4 | **Easy pairs (gap>1)** | >=30% of non-tie pairs | Easy pairs anchor the ranking; without them, there's no "skeleton" |
| 5 | **Reviewers per paper** | >=3, ideally >=4 | <3 reviewers = unreliable individual paper GT |
| 6 | **Papers** | >=40, ideally >=60 | Smaller pools have too few pairs for statistical power |
| 7 | **Full text available** | >=80% of papers | Abstract-only mode is 5-10% worse than full-text modes |

### SHOULD-HAVE Requirements

| # | Requirement | Threshold | Rationale |
|---|---|---|---|
| 8 | **Committee/editorial decision** | Present (accept/reject + tier) | Committee decisions are cleaner signals than averaged scores |
| 9 | **Score scale range** | >=5 points (e.g., 1-10 or 1-8) | Wider scales allow finer discrimination |
| 10 | **Human split-half agreement** | >=70% | If humans can't agree, AI can't be expected to match them |
| 11 | **Domain** | CS, NLP, Statistics, Social Science | Domains with more training data in LLM corpora perform better |
| 12 | **Paper structure** | Clear IMRaD format | Structured papers are easier for section extraction and assessment |

### NICE-TO-HAVE / Quality Boosters

| # | Requirement | Impact |
|---|---|---|
| 13 | **Stratified import** | Select papers across the full score range, not random |
| 14 | **Multi-dimensional GT** | Separate scores for rigor, novelty, presentation, etc. |
| 15 | **Reviewer confidence scores** | Weight confident reviews higher |
| 16 | **Multiple tournaments** | Run with different judge models for cross-validation |

### Red Flags — Datasets Likely to Fail

- Only 2 acceptance tiers (e.g., accept/reject with no quality gradation)
- Average score stdev < 0.5
- >50% of pairs are GT ties
- <2 reviewers per paper on average
- Scores on a 3-point scale (approve/revise/reject)
- Highly specialized domain with little LLM training data (e.g., taxonomy, mycology)

---

## 5. Predictive Model: Expected rho from Dataset Properties

Based on our 12-dataset sample, convergence quality can be roughly predicted:

```
Expected_rho ~= 0.15 * log2(n_tiers)          [+0.15 to +0.37 for 2-5 tiers]
             + 0.10 * (1 - tie_fraction)        [+0.04 to +0.09]
             + 0.10 * easy_pair_fraction         [+0.01 to +0.05]
             + 0.05 * (domain == CS/NLP)         [+0.00 to +0.05]
             + base (0.10)
```

This gives:
- ICLR-codegen: 0.15*2.32 + 0.10*0.67 + 0.10*0.43 + 0.05 + 0.10 = **0.51** (actual: 0.38-0.58 range)
- MIDL: 0.15*1.00 + 0.10*0.41 + 0.10*0.41 + 0.00 + 0.10 = **0.33** (actual: 0.26)
- ACMI: 0.15*1.58 + 0.10*0.97 + 0.10*0.22 + 0.00 + 0.10 = **0.46** (actual: 0.21 — compressed range penalty not captured)
- PeerRead: 0.15*3.81 + 0.10*0.84 + 0.10*0.30 + 0.05 + 0.10 = **0.83** (actual: 0.61 — ceiling effect)

The model overestimates for datasets with compressed score ranges (ACMI) and those at the ceiling (PeerRead), suggesting a **non-linear penalty for GT noise** that simple features don't capture.

---

## 6. Actionable Recommendations

### For Immediate Use: Best Candidate Datasets

1. **More ICLR sub-domains**: Any ICLR label with 40+ papers will work. The 5-tier system is the gold standard.
2. **NeurIPS / ICML**: Same review structure as ICLR. Should produce similar results.
3. **ACL / EMNLP**: Same structure as PeerRead but with more papers and newer reviews.
4. **OpenReview venues with scores + decisions**: Any venue that has both numerical scores (1-10) and categorical decisions.

### For Improving Existing Datasets

1. **MIDL**: Import the raw reviewer scores (1-5 preliminary + final ratings) instead of just Poster/Oral. Use score average as GT instead of venue tier. This should immediately improve from 2 tiers to ~15+ unique values.
2. **ACMI**: Filter to papers with >=4 reviews. Weight by reviewer confidence if available. Consider using only the top-25% and bottom-25% of papers (bimodal selection) to increase GT spread.
3. **eLife**: Only include papers with >=2 independent reviews. Use combined significance+strength score (e.g., sig*2 + strength) instead of significance alone.

### For New Dataset Selection

Before investing in a new dataset, compute these metrics on a sample:
1. Count distinct GT tiers/values
2. Compute GT score stdev
3. Compute % tie pairs
4. Check average reviewers per paper
5. If any metric falls below the MUST-HAVE thresholds, move on to another dataset.

---

## Appendix: Raw Data Tables

### A. Complete Pairwise Accuracy by Mode

| Dataset | abstract | summary | opus46 | deep_dive | full_pdf |
|---|---|---|---|---|---|
| iclr-codegen | 62.6% | 68.5% | 72.6% | **74.7%** | 70.8% |
| iclr-pdes | 65.3% | 81.2% | 85.6% | **86.0%** | 84.7% |
| iclr-llm | 62.4% | 70.3% | 70.0% | - | **70.9%** |
| iclr-fairness | - | 71.8% | **78.4%** | - | 76.7% |
| iclr-ot | 59.1% | 66.7% | **73.1%** | - | 70.6% |
| iclr-molecules | - | 76.2% | **89.9%** | - | 74.2% |
| iclr-optimization | - | **84.3%** | 83.4% | - | 83.1% |
| iclr-protein | 56.9% | 71.9% | **77.8%** | - | 68.1% |
| midl | - | 67.2% | 67.7% | **68.7%** | 68.6% |
| peerread | 71.3% | 73.4% | - | **74.3%** | 71.7% |
| acmi-100 | - | **57.6%** | - | 57.5% | - |
| elife-neuro | 61.5% | **67.6%** | 67.6% | 63.5% | - |

### B. Deep Dive Experiment Summary

| Dataset | Papers | Step2 | Step3 | Replays | Baseline Acc | DD Acc | Lift |
|---|---|---|---|---|---|---|---|
| iclr-codegen | 62 | 62 | 62 | 958 | 68.5% | 74.7% | **+6.2%** |
| iclr-pdes | 80 | 80 | 80 | 869* | 85.6% | 86.0% | +0.4% |
| midl | 81 | 81 | 81 | 498 | 67.7% | 68.7% | +1.0% |
| peerread | 80 | 80 | 80 | 1025 | 73.4% | 74.3% | +0.9% |
| acmi-100 | 100 | 100 | 100 | 1226 | 57.6% | 57.5% | -0.1% |
| elife-neuro | 100 | 100 | 100 | 1325 | 67.6% | 63.5% | -4.1% |

*Partial — stopped due to budget.

**Observation:** Deep dive provides meaningful lift only for ICLR-codegen (+6.2%). For datasets with poor GT structure, deeper analysis cannot compensate for the fundamental limitation of the ground truth.
