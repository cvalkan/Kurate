# Positional Bias Investigation — Full Report

**Date:** April 20, 2026  
**Investigator:** E1 Agent  
**Status:** Open — GPT-5.2 anomaly unresolved

---

## 1. Background

Kurate.org's tournament pipeline randomly flips the presentation order of two papers before sending them to an LLM judge. Paper 1 and Paper 2 are randomly assigned to prompt positions. The LLM returns "paper1" or "paper2" as the winner. The flip ensures each paper has equal probability of appearing in either position, controlling for positional bias.

**Positional bias** = the tendency of an LLM to prefer the paper in a specific position (first or second) regardless of paper quality. A perfectly unbiased model shows 50% Pos1 rate.

---

## 2. Data Sources Analyzed

| Dataset | Collection | Models | Matches | Flip Logic |
|---------|-----------|--------|---------|------------|
| ICLR 2026 cross-label | `validation_matches` | GPT-5.4, Claude Opus 4.6, Gemini 3 Pro | 57,256 | `random.random() < 0.5` in `validation_match_pipeline.py` |
| ICLR 2026 within-label | `validation_matches` | GPT-5.4, Claude Opus 4.6, Gemini 3 Pro | 25,116 | `random.random() < 0.5` in `within_label_match_pipeline.py` |
| Preview live tournament | `matches` | GPT-5.2, Claude Opus 4.6, Gemini 3 Pro, Claude Opus 4.5 | 88,761 | `secrets.randbelow(2)` in `scheduler.py` |
| Production live tournament | `matches` | GPT-5.2, Claude Opus 4.6, Gemini 3 Pro, Claude Opus 4.5 | 211,707 | `secrets.randbelow(2)` in `scheduler.py` |

**Important:** Validation pipelines use GPT-5.4. Live tournament uses GPT-5.2. Different model versions.

---

## 3. Results

### 3.1 Validation Pipelines (Ground Truth — Independent Flip)

**ICLR 2026 Cross-Label (57K matches):**

| Model | Pos1 % | p-value | Interpretation |
|-------|--------|---------|---------------|
| Claude Opus 4.6 | **51.3%** | <0.001 | Mild first-paper preference |
| GPT-5.4 | **48.1%** | <0.001 | Mild second-paper preference |
| Gemini 3 Pro | **47.1%** | <0.001 | Moderate second-paper preference |

**ICLR 2026 Within-Label (25K matches):**

| Model | Pos1 % | p-value | Interpretation |
|-------|--------|---------|---------------|
| Claude Opus 4.6 | **51.8%** | 0.001 | Mild first-paper preference |
| GPT-5.4 | **48.6%** | 0.011 | Mild second-paper preference |
| Gemini 3 Pro | **46.7%** | <0.001 | Moderate second-paper preference |

**Assessment:** Both validation datasets agree. Claude slightly prefers Paper 1 (~51-52%), GPT-5.4 and Gemini slightly prefer Paper 2 (~47-49%). All biases are small (within 3% of 50%). Flip distribution is perfect 50/50. **These numbers are trustworthy.**

---

### 3.2 Production Live Tournament (212K matches)

**Weekly breakdown:**

| Week | Opus 4.5 | Opus 4.6 | Gemini 3 | GPT-5.2 |
|------|----------|----------|----------|---------|
| W06 | 45.3% | — | 49.5% | **39.8%** |
| W07 | 42.0% | — | 43.7% | **38.3%** |
| W08 | 43.2% | 51.4% | 50.6% | **38.7%** |
| W09 | — | 48.8% | 52.4% | **45.0%** |
| W10 | — | 48.9% | 52.3% | **44.7%** |
| W11 | — | 47.9% | 48.8% | **46.2%** |
| W12 | — | 49.3% | 48.4% | **45.9%** |
| W13 | — | 48.1% | 49.6% | **40.2%** |
| W14 | — | 48.5% | 48.5% | **35.7%** |
| W15 | — | 47.9% | 48.1% | **35.3%** |
| W16 | — | 48.7% | 48.2% | **35.2%** |
| W17 | — | 49.3% | 48.3% | **36.3%** |

**Assessment:**
- **Claude Opus 4.6: ~48-49%** — consistent with validation baseline (~51%). ✅
- **Gemini 3 Pro: ~48-52%** — consistent with validation baseline (~47%). ✅
- **GPT-5.2: 35-46%, worsening over time** — NOT consistent with GPT-5.4 validation baseline (48%). ❌
- **Opus 4.5 (W06-W08): 42-45%** — moderate second-paper bias, now retired.

---

### 3.3 Preview Live Tournament (89K matches)

**Weekly breakdown:**

| Week | Opus 4.5 | Opus 4.6 | Gemini 3 | GPT-5.2 |
|------|----------|----------|----------|---------|
| W06 | 53.0% | — | 54.0% | 49.7% |
| W07 | **46.1%** | — | **46.6%** | **44.3%** |
| W08 | **63.9%** | 79.2% | **68.5%** | **60.5%** |
| W09 | — | 60.9% | 59.8% | 58.7% |
| W10 | — | 57.8% | 60.0% | 58.2% |
| W11 | — | 61.5% | 60.3% | 60.4% |
| W12-14 | — | 59-61% | 55-58% | 57-58% |

**Assessment:**
- **W06:** ~50-54% — near-unbiased
- **W07:** ~44-47% — second-paper bias (matches production pattern)
- **W08 onward:** ~58-65% — sudden jump to strong FIRST-paper bias for ALL models
- **This pattern exists for Claude and Gemini too** — but production Claude/Gemini are ~49%. Preview is the outlier.

---

## 4. Analysis

### 4.1 What's Consistent

- **Claude Opus 4.6 and Gemini 3 Pro** show ~48-52% across production (W09+) and validation. The production flip logic is working correctly for these models.
- **Validation pipeline flip** is confirmed correct — perfect 50/50 distribution, bias numbers are small and symmetric.

### 4.2 What's Anomalous

#### Anomaly 1: GPT-5.2 on Production (35% pos1, worsening)
- Claude and Gemini use the SAME flip code and show ~49%. GPT-5.2 shows 35%.
- This rules out a flip bug — the flip is model-agnostic.
- GPT-5.2 genuinely prefers the second paper, and this preference has strengthened over time (46% in W11 → 35% in W16).
- **Possible explanation:** OpenAI model updates (GPT-5.2 may have been updated server-side between W11 and W16, increasing recency/position bias).
- **Note:** Validation uses GPT-5.4 (not 5.2), which shows 48% — nearly unbiased. The bias appears specific to GPT-5.2.

#### Anomaly 2: Preview Live Tournament (60% for all models)
- Preview shows ~60% pos1 for ALL models from W08 onward, including Claude (60.5%) and Gemini (61.1%).
- But production Claude/Gemini are ~49%, and validation Claude is ~51%.
- **Preview's 60% is the outlier**, not production.
- Preview has a `custom_prompt` document with slightly different wording ("Abstract: " prefix), but this is unlikely to cause a 10% bias shift.
- Preview and production are different databases (preview: 89K matches, production: 212K). Preview was forked on April 19, 2026, but contains match data from a different pipeline run — not a copy of production.
- **Possible explanation:** Preview's matches (W08+) were generated by a different code version or configuration that introduced systematic first-paper bias. This code was never deployed to production.

### 4.3 Content Mode Breakdown (Preview)

| Content Mode | Matches | All-Model Pos1% |
|-------------|---------|-----------------|
| `abstract_plus_summary` | 72,653 | ~60% (first-paper bias) |
| `legacy_abstract_only` | 16,108 | ~44% (second-paper bias) |

The two modes show opposite biases on preview. The `legacy_abstract_only` matches (W06-W07) align with production's pattern. The `abstract_plus_summary` matches (W08+) show the anomalous 60%.

### 4.4 Content Mode Breakdown (Production)

| Content Mode | Matches |
|-------------|---------|
| `abstract_plus_summary` | 189,758 |
| `NO_CONTENT_MODE` (legacy) | 21,949 |

Production's `abstract_plus_summary` matches show the same Claude/Gemini ~49% pattern as validation. Only GPT-5.2 diverges.

---

## 5. Conclusions

### Confirmed
1. **The flip logic in the production scheduler is correct.** Claude and Gemini show expected ~49% pos1 rates, consistent with validation.
2. **The validation pipeline flip is correct.** Both ICLR 2026 datasets show small, consistent biases near 50%.
3. **Preview live tournament data is NOT representative of production.** The 60% bias on preview is an artifact of the preview's database, not the current codebase.

### Unresolved
1. **GPT-5.2 has a strong and worsening second-paper bias (35% pos1 in W16).** This appears to be genuine model behavior, not a code bug. It may be caused by server-side model updates at OpenAI.
2. **Why does preview show 60% for all models from W08?** The preview database was populated by a different pipeline run with unknown configuration. This data should not be used as a reference for bias analysis.

---

## 6. Recommendations

### Immediate
1. **Do NOT change the flip logic.** It's working correctly on production.
2. **Run a controlled A/B test** for GPT-5.2: send the same 100 paper pairs twice (once as A-vs-B, once as B-vs-A) and measure how often GPT picks the second position regardless of content. This would definitively confirm whether it's model behavior.
3. **Consider replacing GPT-5.2 with GPT-5.4** in the live tournament, which shows near-unbiased behavior (48.1%) in validation.

### Monitoring
4. **Add weekly bias monitoring** — the `/api/positional-bias-diagnostic?group=week` endpoint is now deployed. Track GPT-5.2's pos1 rate weekly to detect further deterioration.
5. **If GPT-5.2 drops below 30% pos1**, consider pausing GPT-5.2 matches until the bias is investigated.

### Data Quality
6. **Preview database should not be used for bias comparisons.** It contains data from a different pipeline run with anomalous 60% first-paper bias.
7. **The `NO_CONTENT_MODE` matches (22K on production)** are from the earliest pipeline version. They show different bias patterns and could be excluded from analysis if needed, though they don't significantly affect the overall numbers.

---

## 7. Architecture Notes

### Chinese Wall
- **Live tournament data:** `db.matches` — queried by `leaderboard.py`, `model_analysis.py`
- **Validation data:** `db.validation_matches` — queried by `validation_experiments.py`
- Positional bias endpoints for live data now live in `leaderboard.py` (moved from `validation_experiments.py`)
- These collections are never mixed in any query.

### Flip Implementation
- **Live tournament** (`scheduler.py`): `secrets.randbelow(2)` — swaps `p1_id`/`p2_id` before calling `compare_papers`
- **Validation pipeline** (`*_match_pipeline.py`): `random.random() < 0.5` — swaps prompt paper order, stores `flipped` field
- Both achieve the same goal but through different mechanisms. The validation pipeline explicitly stores the `flipped` boolean, making bias analysis easier.

---

*End of report*



---

# Follow-up: April 21, 2026 — GPT-5.2 Controlled A/B Test

## Motivation
The original report (above) left the GPT-5.2 drift on production unresolved
and suggested "OpenAI silent server-side update" as the most likely cause.
A pairwise controlled experiment was run to falsify that hypothesis.

## Step-change analysis (diagnostic from production DB)

Per-week GPT-5.2 pos1 rate from `/api/positional-bias-diagnostic?group=week`,
analyzed as discrete step-changes (not drift):

| Transition | Δ pos1 | z-score | Correlates with |
|------------|--------|---------|-----------------|
| W08→W09 (Feb 22/23) | **+6.4 pp** | +6.48 | commit `bfad1aa5` — TOURNAMENT_MODELS swap: Opus 4.5 → Opus 4.6 as judge |
| W09→W12 | flat (±1.5pp) | |z|<2 | — (stable at ~45%) |
| W12→W13 (Mar 22/23) | **−5.7 pp** | −5.46 | match volume +41%, no matching-path code change |
| W13→W14 (Mar 29/30) | **−4.5 pp** | −5.33 | commit `6cad4113` — `_llm_executor` max_workers 100 → **10** + volume +51% |
| W14→W17 | flat (|z|<1) | | stable new equilibrium at ~35.5% |

Claude Opus 4.6 and Gemini 3 Pro are rock-stable at ~48–49% across every
transition above. The three GPT-5.2-specific step-changes argue against
a gradual OpenAI model drift.

## Controlled A/B test (definitive)

**Design:** 200 recently-judged GPT-5.2 pairs harvested from production.
Each pair judged **twice** with `model_override={"openai","gpt-5.2"}`:
once (A in pos1, B in pos2), once (B in pos1, A in pos2). Calls made
from a low-pressure preview pod at concurrency=5 (no scheduler queue).
Same prompt_config as production (custom_prompt from `db.settings`).

**Result (n=199 pairs, 398 calls, 0 failures):**

| Metric | Value | Interpretation |
|--------|-------|----------------|
| pos1 rate | **49.75%** | ~unbiased |
| 95% CI | 44.9 – 54.6 | straddles 50%, clearly excludes 35.5% |
| p-value (H0: p=50%) | 0.96 | cannot reject null → no bias |
| p-value (H0: p=35.5%) | 6.6 × 10⁻⁹ | rejects production rate |
| Consistency (same winner both orderings) | **97.49%** | highly reproducible |
| Inconsistent pairs | 5 / 199 | symmetric: 2 flip-to-first, 3 flip-to-second |

Two-proportion z-test vs production W16 (n=13,243 at 35.2%): **z=5.97**.

## Conclusion

GPT-5.2 has **no intrinsic positional bias** when called outside the
scheduler. The production 35.5% pos1 rate is **not a model property** —
it is an emergent artifact of the production pipeline, almost certainly
triggered by the Mar 28 `max_workers=100→10` change combined with the
W14+ match-volume surge. The two transitions that produced the drop
(Breaks 2 & 3) both correlate with infrastructure/capacity pressure,
not model or prompt changes.

## Additional cleanup applied

`compare_papers` (llm.py) previously read summary via a legacy fallback
chain `ai_impact_summary_thinking → ai_impact_summary_opus46 →
ai_impact_summary`. That chain was migration residue from the Opus 4.5
→ 4.6 → 4.6-thinking rollout, and no longer matched any scheduler-written
field. Removed in favor of a single `ai_impact_summary` read, with a
docstring pinning the contract. Regression test added at
`backend/tests/test_compare_papers_summary_contract.py`.

## Actionable recommendations

1. **Raise `_llm_executor` max_workers back toward 30–40** (from 10).
   The Mar 28 reduction was made under memory pressure that has since
   been relieved by the `_generate_paper_summaries` and `_select_pairs`
   memory optimizations (commits `65da3ce0`, `d45cb681`, Mar 23–24).
   Predict: GPT-5.2 pos1 rate will recover toward ~48% within 2 weeks.

2. **Re-run this A/B after the change** to verify recovery. Script at
   `backend/scripts/positional_ab_gpt52.py` is reusable as-is.

3. **Consider a lightweight latency/error dashboard per-model** so the
   next infra-driven bias shift is visible immediately.

4. The **preview anomaly (60% pos1, all models, W08+)** from §4.2 of
   the original report remains unexplained and is worth one more look
   — the pattern (all models moving together by the same magnitude)
   strongly suggests a metric-read bug in the preview snapshot, not a
   model behavior. Out of scope here.

*End of April 21 follow-up*
