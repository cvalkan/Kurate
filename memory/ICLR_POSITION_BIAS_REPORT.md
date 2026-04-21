# ICLR 2026 Positional-Bias Analysis

_Generated: 2026-04-21T20:25:46.989855+00:00 — source: JSONL `/app/memory`_

## Dataset summary

- **iclr-2026-validation**: 57,256 completed matches
  - models: {'gemini-3-pro-preview': 19467, 'claude-opus-4-6': 19109, 'gpt-5.4': 18680}
  - pairs with tier ground-truth: 53,076
- **iclr-2026-within-label**: 25,116 completed matches
  - models: {'gpt-5.4': 8509, 'gemini-3-pro-preview': 8403, 'claude-opus-4-6': 8204}
  - pairs with tier ground-truth: 23,062

## Test 1 — Position Consistency / Accuracy-asymmetry by gap decile  _(dataset: `iclr-2026-validation`)_

### By `score_gap`

_Dual-ordering coverage: 0.0% of rows_

**Accuracy-asymmetry fallback** (dual orderings scarce).
Measures: for pairs with clear human winner, is AI accuracy higher when human winner is in pos1 vs pos2? Gap = **2 × positional bias** in %.


**claude-opus-4-6** — Spearman ρ(decile, |asymmetry|) = +0.067, p = 0.865
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.364 |  61.9% |  60.1% |  +1.8 | +1.24 | 0.215 |
| 1      | 0.656 |  60.6% |  60.4% |  +0.3 | +0.07 | 0.943 |
| 2      | 0.966 |  64.6% |  61.3% |  +3.3 | +1.97 | 0.0491 |
| 3      | 1.139 |  64.6% |  62.3% |  +2.3 | +0.36 | 0.72 |
| 4      | 1.436 |  70.4% |  70.7% |  -0.3 | -0.16 | 0.871 |
| 5      | 1.712 |  73.8% |  70.8% |  +3.0 | +0.79 | 0.428 |
| 6      | 1.989 |  78.8% |  72.6% |  +6.2 | +2.98 | 0.00285 |
| 7      | 2.452 |  79.0% |  77.5% |  +1.5 | +0.75 | 0.456 |
| 8      | 3.509 |  86.5% |  87.0% |  -0.5 | -0.32 | 0.751 |

**gemini-3-pro-preview** — Spearman ρ(decile, |asymmetry|) = +0.050, p = 0.898
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.368 |  59.4% |  60.7% |  -1.3 | -0.87 | 0.385 |
| 1      | 0.655 |  57.5% |  59.8% |  -2.3 | -0.62 | 0.538 |
| 2      | 0.965 |  61.3% |  67.3% |  -6.0 | -3.64 | 0.00027 |
| 3      | 1.139 |  71.0% |  66.1% |  +4.9 | +0.84 | 0.401 |
| 4      | 1.436 |  66.3% |  74.1% |  -7.7 | -4.54 | 5.62e-06 |
| 5      | 1.707 |  66.2% |  77.3% | -11.1 | -3.11 | 0.00188 |
| 6      | 1.989 |  76.2% |  77.8% |  -1.6 | -0.79 | 0.429 |
| 7      | 2.448 |  77.6% |  83.8% |  -6.2 | -3.35 | 0.000807 |
| 8      | 3.502 |  89.3% |  90.3% |  -1.0 | -0.73 | 0.464 |

**gpt-5.4** — Spearman ρ(decile, |asymmetry|) = -0.117, p = 0.765
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.369 |  56.9% |  60.3% |  -3.3 | -2.23 | 0.0256 |
| 1      | 0.655 |  65.1% |  64.2% |  +0.9 | +0.24 | 0.809 |
| 2      | 0.966 |  60.0% |  66.9% |  -6.8 | -4.06 | 4.94e-05 |
| 3      | 1.144 |  64.0% |  73.9% |  -9.9 | -1.59 | 0.111 |
| 4      | 1.436 |  68.8% |  71.0% |  -2.2 | -1.27 | 0.203 |
| 5      | 1.704 |  71.8% |  70.0% |  +1.8 | +0.48 | 0.633 |
| 6      | 1.989 |  75.4% |  77.8% |  -2.4 | -1.18 | 0.24 |
| 7      | 2.447 |  77.8% |  82.6% |  -4.9 | -2.56 | 0.0104 |
| 8      | 3.501 |  87.2% |  89.1% |  -1.9 | -1.19 | 0.236 |

### By `tier_gap`

_Dual-ordering coverage: 0.0% of rows_

**Accuracy-asymmetry fallback** (dual orderings scarce).
Measures: for pairs with clear human winner, is AI accuracy higher when human winner is in pos1 vs pos2? Gap = **2 × positional bias** in %.


**claude-opus-4-6** — Spearman ρ(decile, |asymmetry|) = -0.500, p = 0.667
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.648 |  69.0% |  64.2% |  +4.9 | +5.73 | 1.02e-08 |
| 1      | 2.000 |  82.0% |  82.1% |  -0.1 | -0.09 | 0.925 |
| 2      | 3.401 |  87.3% |  89.3% |  -2.1 | -0.56 | 0.573 |

**gemini-3-pro-preview** — Spearman ρ(decile, |asymmetry|) = +0.500, p = 0.667
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.640 |  64.7% |  66.7% |  -2.0 | -2.38 | 0.0171 |
| 1      | 2.000 |  82.1% |  87.7% |  -5.5 | -4.33 | 1.51e-05 |
| 2      | 3.425 |  87.0% |  92.2% |  -5.1 | -1.56 | 0.118 |

**gpt-5.4** — Spearman ρ(decile, |asymmetry|) = +0.500, p = 0.667
| Decile | Gap | Acc (human→pos1) | Acc (human→pos2) | Asymm pp | z | p |
|--------|-----|------------------|------------------|---------|----|----|
| 0      | 0.641 |  66.0% |  66.2% |  -0.2 | -0.25 | 0.8 |
| 1      | 2.000 |  78.5% |  81.9% |  -3.4 | -2.37 | 0.0179 |
| 2      | 3.416 |  91.1% |  91.4% |  -0.2 | -0.08 | 0.938 |

## Test 2 — Inconsistency direction (primacy vs recency)

⚠️  **Only 0 dual-ordering rows available** — this test requires each pair to be judged by the SAME model in BOTH prompt orders. The validation pipeline judges each pair once per model, so this test cannot be run on the current dataset.

**To enable:** rerun a sample (e.g., 500 pairs) a second time per model with random-flip. This is the controlled-AB-test pattern we used on live traffic.

## Test 4 — Within-label vs cross-label agreement

Per-model `ai_correct` rate on pairs with clear human signal:

| Model | Cross-label acc (n) | Within-label acc (n) | Δ (pp) | z | p |
|-------|--------------------|----------------------|--------|----|----|
| claude-opus-4-6 |  68.9% (17754) |  70.8% (7522) |  -1.8 | -2.86 | 0.00427 |
| gemini-3-pro-preview |  69.8% (18000) |  69.8% (7725) |  +0.0 | +0.04 | 0.971 |
| gpt-5.4 |  69.1% (17322) |  69.1% (7815) |  -0.0 | -0.05 | 0.964 |

_Expected pattern: accuracy is lower on within-label pairs (same tier ⇒ harder). A larger drop for one model = more gap-sensitive judge. This parallels the Shi et al. 2025 'quality gap dominates position consistency' finding._

## Test 10 — Temporal drift within `iclr-2026-validation`

_(no created_at info)_

## Test 10 — Temporal drift within `iclr-2026-within-label`

_(no created_at info)_
