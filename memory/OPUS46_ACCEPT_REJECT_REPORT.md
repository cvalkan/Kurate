# Opus 4.6 Thinking — Single-Item Accept/Reject Accuracy Report

**Date:** 2026-03-25  
**Methodology:** ReviewerToo (arXiv:2510.08867)

## Setup

| Parameter | Value |
|---|---|
| Model | Claude Opus 4.6 (extended thinking, budget_tokens=8000) |
| Input | Abstract + Opus 4.6-generated research impact summary |
| Prompt | ICLR 2025 Reviewer Guide criteria (novelty, soundness, experimental validity, significance, clarity) |
| Sample | 100 papers (50 accept, 50 reject), ICLR 2025, seed=42 |
| Categories | 5-way: Oral/Spotlight/Poster/Reject/Desk Reject; Withdrawn→Reject |
| Completed | 96/100 (4 failed due to Emergent LLM budget limit) |
| Tokens | 234K input, 156K output, 54K thinking |

### Sample Composition

| Tier | Count |
|---|---|
| Oral | 7 |
| Spotlight | 12 |
| Poster | 31 |
| Reject | 41 |
| Withdrawn | 8 |
| Desk Rejected | 1 |

---

## Results

### Binary Accept/Reject

| Method | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|
| **Human top-1% [paper]** | **92.4%** | — | — | — |
| **Human (our data, thresh=5.6)** | **88.0%** | 83.9% | 94.0% | 0.887 |
| **Human avg [paper]** | **83.9%** | — | — | — |
| ReviewerToo META (all) [paper] | 81.8% | — | — | — |
| **Opus 4.6 Thinking (this test)** | **76.0%** | 72.5% | 80.4% | 0.763 |

Confusion matrix (n=96):
```
              Predicted Accept    Predicted Reject
Actual Accept       37 (TP)           9 (FN)
Actual Reject       14 (FP)          36 (TN)
```

### 5-Way Categorical

**Overall: 62.5%** (60/96)

```
Actual \ Pred    Oral   Spotlight  Poster   Reject   Desk Reject
Oral              0        0         6        1         0
Spotlight         0        0         6        3         0
Poster            0        0        25        5         0
Reject            0        0        14       35         0
Desk Rejected     0        0         0        1         0
```

**Key observation:** The model **never predicts Oral or Spotlight**. All accept predictions are "Accept (Poster)". This is a known LLM calibration issue — models cluster toward safe/middle categories.

### Per-Tier Binary Accuracy

| Tier | Correct | Accuracy |
|---|---|---|
| Oral | 6/7 | 85.7% |
| **Spotlight** | **6/9** | **66.7%** |
| Poster | 25/30 | 83.3% |
| **Reject** | **27/41** | **65.9%** |
| Withdrawn | 8/8 | 100.0% |
| Desk Rejected | 1/1 | 100.0% |

### AI Score Distribution by Actual Decision

| Tier | Mean Score | Median | Range |
|---|---|---|---|
| Oral | 6.4 | 7 | 5–7 |
| Spotlight | 5.9 | 6 | 5–7 |
| Poster | 6.0 | 6 | 4–7 |
| Reject | 4.9 | 5 | 2–6 |
| Withdrawn | 4.8 | 5 | 4–6 |

### Confidence Calibration

| | Mean Confidence (1-5) |
|---|---|
| Correct predictions | 3.8 |
| Wrong predictions | 3.6 |

Confidence is poorly calibrated — nearly identical for correct and wrong predictions.

---

## Analysis

### Why 76% < 87.2% (pairwise)?

Single-item prediction is fundamentally harder than pairwise comparison:
- **Pairwise** gives you a direct comparison point — "Is paper A better than paper B?"
- **Single-item** requires absolute calibration — "Is this paper good enough for ICLR?"

The model's main failure mode is **accept bias**: 14 out of 50 rejected papers were predicted as accepted (28% FP rate). These rejected papers often had interesting ideas but insufficient empirical validation — exactly the papers that are hard even for human reviewers.

### Error Patterns

**False Positives (14 cases):** All predicted as "Accept (Poster)" with score=6. These are borderline papers that sound promising in abstract+summary form but lack the experimental rigor that ICLR demands. The model cannot assess reproducibility, statistical significance, or experimental gaps from summaries alone.

**False Negatives (9 cases):** All predicted as "Reject" with scores 4-5. Includes 1 Oral, 3 Spotlights, and 5 Posters. The model appears to penalize papers in niche areas (fairness, zeroth-order optimization) where the significance may not be obvious from the abstract alone.

### Comparison to ReviewerToo Paper

- ReviewerToo META (ensemble of personas) achieves 81.8% — our single Opus 4.6 at 76% is ~6% lower
- The paper uses **full manuscript** as input; we use abstract + summary
- The paper uses **multiple reviewer personas** and a metareviewer to synthesize — we use one pass
- Using full paper text and/or a multi-agent review process would likely close the gap

---

## Pairwise vs Single-Item Summary

| Evaluation Type | Opus 4.6 Thinking | Human Baseline |
|---|---|---|
| **Pairwise** (cross-tier) | **87.2%** | 82.9% (individual) / 95.4% (avg score) |
| **Single-item** (accept/reject) | **76.0%** | 88.0% (our data) / 83.9% (paper) |

Opus 4.6 Thinking **beats individual human reviewers in pairwise** but **trails in single-item**. This makes sense: relative comparison is easier than absolute judgment, and the model's score compression (Oral=6.4 vs Poster=6.0) shows poor absolute calibration.
