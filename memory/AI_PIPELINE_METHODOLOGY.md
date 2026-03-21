# AI vs. Human Validation Pipeline — Methodology Report

## Overview

The AI vs. Human benchmark evaluates how well AI pairwise judges agree with human peer reviewers on paper quality rankings. The pipeline uses a two-stage architecture: first summarize, then judge.

## Stage 1: AI Impact Assessment (Summarizer)

**Model:** Claude Opus 4.6 with Extended Thinking (budget: 10,000 thinking tokens)

**Input:** Full paper PDF text + abstract. The summarizer reads the complete paper including title, author names (from PDF headers), and all sections. No truncation is applied unless the text exceeds the model's context window, in which case it is halved iteratively.

**Prompt:** The summarizer is instructed to write up to 1,000 words structured around five dimensions:
1. Core Contribution — novelty and problem solved
2. Methodological Rigor — soundness of approach and experiments
3. Potential Impact — real-world applications and breadth of influence
4. Timeliness & Relevance — current bottlenecks or emerging needs
5. Strengths & Limitations — standout qualities and gaps

After the narrative assessment, the model provides numerical ratings (1.0–10.0) for: overall score, significance, rigor, novelty, and clarity.

**Output:** A text assessment (~500–1,000 words) stored as `ai_impact_summary_thinking` on the paper document, plus structured ratings parsed from the JSON line.

**Note on author visibility:** The summarizer sees the full PDF which includes author names and affiliations in the header. This means the assessment could be influenced by author reputation — analogous to single-blind peer review.

## Stage 2: Pairwise Comparison (Judge)

**Models:** Round-robin rotation across three models:
- GPT-5.2 (OpenAI)
- Claude Opus 4.6 (Anthropic)
- Gemini 3 Pro Preview (Google)

Each comparison is assigned to one model via round-robin (1 judge per pair), ensuring equal contribution from all three.

**Input per paper:** Abstract (truncated to 1,500 chars) + the Opus 4.6 Thinking impact assessment from Stage 1. The content mode is `abstract_plus_summary:thinking`.

Specifically, each paper is presented as:
```
Abstract: [first 1,500 chars of abstract]

AI Impact Assessment:
[full Opus 4.6 Thinking assessment from Stage 1]
```

**Prompt:** The judge evaluates which paper has higher potential scientific impact across five criteria:
1. Novelty and innovation
2. Real-world applications
3. Methodological rigor
4. Breadth of impact across fields
5. Timeliness and relevance

**Output:** JSON with a binary winner (`paper1` or `paper2`) and brief reasoning (max 150 words). No ties are allowed in the standard comparison mode.

**Positional bias correction:** The presentation order of each pair is randomly flipped with 50% probability before sending to the judge, preventing the known tendency for models to prefer the first-presented paper.

**Note on author visibility:** The judge does NOT see author names. It receives only the abstract and the AI assessment (which itself doesn't include author names in its text, though it was informed by the full PDF).

## Stage 3: Benchmark Computation

### Datasets
- **8 ICLR topic subsets** (469 papers total): Code Generation, Fairness, LLMs, Molecules, Optimization, Optimal Transport, PDEs, Protein Science
- **PeerRead ACL 2017** (80 papers)

### Ground Truth
Human ground truth is derived from reviewer scores (ICLR: 1–10 scale with 6 distinct values; PeerRead: 1–5 scale). For each pair of papers scored by the same positional reviewer, if the scores differ, the higher-scored paper "wins." Ties (same score) are handled via coin-flip correction.

### Controlled Pairs
Only pairs where BOTH an AI match AND at least one human reviewer comparison exist are analyzed. This yields 3,956 controlled pairs across 9 datasets.

### Metrics Computed

**Pairwise Agreement:**
- AI vs. Human: does AI agree with each individual reviewer?
- Human vs. Human: do two reviewers agree with each other?
- AI vs. Majority: does AI agree with the majority vote of reviewers?
- Human vs. Majority (LOO): does a held-out reviewer agree with the remaining majority?
- AI/Human vs. Committee: does AI/reviewer agree with the actual ICLR tier decision?

All metrics are computed both with ties excluded and with coin-flip correction (ties resolved randomly at 50%).

**Ranking Correlation (Bradley-Terry):**
- Individual votes from all reviewers are fed as separate matches into a BT model to produce a human ranking
- AI pairwise matches produce an AI ranking
- Spearman ρ and Kendall τ measure correlation between the two rankings
- Multiple comparison targets: individual aggregate, majority, committee tiers, average score

**Difficulty Stratification:**
- Cross-tier (easy): papers from different ICLR tiers with gap ≥ 2 (e.g., Oral vs. Reject)
- Adjacent-tier (medium): tier gap = 1 (e.g., Spotlight vs. Poster)
- Within-tier (hard): same tier (e.g., Poster vs. Poster)

## Key Results

| Metric | AI | Human | Notes |
|---|---|---|---|
| Pairwise agreement (coin-flip) | 74.4% | 73.4% | AI matches human-level |
| BT ranking ρ (vs. individual aggregate) | **0.739** | 0.660 (LOO) | AI outperforms single expert (controlled pairs) |
| BT ranking ρ (vs. committee) | **0.762** | 0.681 | AI outperforms despite human circularity advantage |
| Ceiling utilization (vs. 0.878 max) | **87%** | 78% | AI captures more ranking signal |

## Known Limitations and Methodological Issues

### 1. Cross-Tier Pair Selection Bias (Fixed Mar 2026)

**Issue discovered:** The validation matchmaking algorithm was filtering pair selection to **cross-tier pairs only** — papers with different human ground truth scores (h1_avg_rating). This meant AI was never tested on within-tier comparisons (e.g., Poster vs. Poster), which account for ~26% of all expert pairs.

**Impact on existing data:**

| | AI's pairs (pre-fix) | All expert pairs |
|---|---|---|
| Mean score gap | **2.16** | 1.84 |
| Easy (cross-tier) | **46%** | 30% |
| Medium (adjacent) | **54%** | 44% |
| Hard (within-tier) | **0%** | **26%** |

The controlled benchmark values (ρ = 0.739) are measured on a systematically easier pair set. The head-to-head AI-vs-human comparison remains internally fair (same bias for both sides), but the absolute ρ values overstate ranking quality on the general population of pairs.

**Fix applied:** The cross-tier filter has been removed from the matchmaking algorithm. Future validation runs will sample from ALL possible pairs regardless of tier. Existing data cannot be retroactively fixed — the 3,956 controlled pairs in the current benchmark reflect the biased selection.

**How to detect:** On the "AI Ranking Quality" page, the "Overlap" column shows what fraction of expert pairs were also evaluated by AI. For most ICLR datasets, overlap is 12–39% (AI only sampled a subset), and AI's subset contains zero within-tier pairs.

### 2. Controlled Pairs vs. Full Data

The benchmark uses two distinct methodologies for different purposes:

**Controlled comparison (Human vs AI Benchmark page):**
Both AI and human rankings are built from the **same pair set** (the intersection of AI matches and expert pairs with ≥2 non-tying opinions). This ensures a fair head-to-head comparison: same evidence, same conditions. The ρ values are comparable between AI and the human ceiling.

**Standalone quality (AI Ranking Quality page):**
AI ranking from ALL its thinking-mode matches; human ground truth from ALL expert pairs. Each method uses its full available data independently. This measures absolute ranking quality without coupling the two datasets.

The difference matters because for ICLR datasets, experts cover ~99% of all possible pairs, while AI only evaluates ~25–35%. On the controlled page, the human BT is artificially restricted to AI's sparse pair set (losing 65–75% of available expert data). The standalone page uses the full human data as ground truth.

| Dataset | ρ (controlled) | ρ (standalone) | Δ |
|---|---|---|---|
| Code Gen | 0.826 | 0.731 | −0.095 |
| LLMs | 0.807 | 0.787 | −0.020 |
| Protein | 0.897 | 0.857 | −0.040 |
| Optimization | 0.827 | 0.697 | −0.130 |
| PeerRead | 0.453 | 0.470 | +0.017 |

The controlled ρ is consistently higher (except PeerRead) because the shared pair set is systematically easier (see §1 above: no within-tier pairs).

### 3. Structural BT Score Coupling

When both AI and human majority are computed from the **same pair set** with **1 vote per pair each**, papers where both methods agree unanimously produce identical win/loss records → identical win-rate scores. For Protein Science, 19/46 papers (41%) have exactly matching AI and human-majority BT scores, concentrated at the bottom of the ranking (all 0-win papers).

This is a mathematical guarantee, not a meaningful finding. The Human Individual BT (using per-expert-vote granularity: multiple matches per pair) breaks this coupling completely (0% exact matches).

### 4. Author Visibility in Stage 1

The summarizer reads author names from the PDF. Prestige bias could leak into the assessment, which then influences the judge.

### 5. Positional Reviewer Labels

All reviewer identities are positional (Reviewer 1, 2, ...) — "Reviewer 1" on different papers is a different person. Concordance between positional reviewers approximates random-pair agreement but cannot capture individual reviewer effects.

### 6. Coarse Human Rating Scale

ICLR uses only 6 distinct values (1, 3, 5, 6, 8, 10) on a 1–10 scale, with 67% of ratings being 5 or 6. This produces a ~39% tie rate, limiting the human signal available for comparison.

### 7. Self-Referential Architecture

The same LLM family (Opus 4.6) both summarizes (Stage 1) and judges (Stage 2, as one of three round-robin models). This could create systematic biases that inflate agreement metrics.

### 8. Conservative Coin-Flip Correction

Treating ties as 50/50 underestimates AI agreement because AI has real signal on tie pairs (73.5% agreement with non-tying experts on the same pairs, vs the 50% coin-flip assumption).


## Matchmaking & Pair Selection

### Live Tournament (Leaderboard)

The live leaderboard tournament uses goal-directed adaptive matchmaking. The system selects which papers to compare next based on convergence targets.

**Convergence Targets (Two-Tier):**

| Tier | Target | Meaning |
|---|---|---|
| **General papers** | Wilson 95% CI margin ≤ 15% | Every paper's win rate should be known within ±15% |
| **Top-K papers** (default K=10) | Wilson 95% CI margin ≤ 10% | The best papers need tighter confidence |
| **Top-K cross-matching** | All C(K,2) pairs compared | Every top paper must have been directly compared against every other top paper |

The tournament runs until all three goals are met, then idles.

**Pair Selection Algorithm:**

Each round selects pairs using a priority system:

*Rule 1 — Match neediest papers first:*
- Compute "urgency" for each paper: `margin - target` (how far from convergence)
- Papers with 0 matches have urgency 999 (highest priority)
- Sort all papers by urgency, descending
- For each needy paper, pick an opponent via calibration split:
  - `calibration_ratio`% of matches (default 50%) pair needy papers against **established** papers (already converged), chosen by **score proximity** — matching similar-strength papers produces more informative comparisons.
  - The remaining matches pair **needy vs. needy** — both papers benefit from the same match.
  - New papers (0 matches) target the **median score** when selecting an established opponent.

*Rule 2 — Top-K cross-matches:*
After Rule 1, remaining slots are filled with missing top-K pairwise comparisons.

*Rule 3 — Repeat matches for validation:*
Only after ALL convergence goals are met: re-compare score-adjacent papers to validate close ranking boundaries.

### Validation Benchmark (AI vs. Human)

The validation benchmark uses a **different, simpler** matchmaking strategy:

1. Generate all possible paper pairs
2. Select pairs using a round-robin strategy that ensures minimum coverage per paper (~15–20 matches each)
3. Remaining slots are filled with weighted-random selection (biased toward under-matched papers)

No score-proximity, no CI targets, no calibration split.

**Historical note (pre–Mar 2026):** The original matchmaking code filtered pairs to only cross-tier comparisons (papers with different h1_avg_rating), excluding all within-tier pairs. This was an erroneous optimization introduced by a previous agent — not a deliberate design choice. It has been removed. All existing thinking-mode matches were generated under the old filter and therefore contain no within-tier comparisons. New validation runs will sample from all pairs.

**Match counts per dataset (using Opus 4.6 Thinking summaries as input):**

| Dataset | Papers | Matches | Avg matches/paper | Within-tier matches |
|---|---|---|---|---|
| ICLR Code Generation | 62 | 625 | 20.2 | 0 (pre-fix) |
| ICLR Fairness | 68 | 264 | 7.8 | 0 (pre-fix) |
| ICLR LLMs | 73 | 837 | 22.9 | 0 (pre-fix) |
| ICLR Molecules | 46 | 158 | 6.9 | 0 (pre-fix) |
| ICLR Optimization | 42 | 162 | 7.7 | 0 (pre-fix) |
| ICLR Optimal Transport | 52 | 503 | 19.3 | 0 (pre-fix) |
| ICLR PDEs & Dynamical Systems | 80 | 641 | 16.0 | 0 (pre-fix) |
| ICLR Protein Science | 46 | 259 | 11.3 | 0 (pre-fix) |
| PeerRead ACL 2017 | 80 | 1,118 | 27.9 | 0 (pre-fix) |
| **Total** | **549** | **4,567** | **16.6 avg** | **0** |

These are matches where the judges read the **Opus 4.6 Thinking assessment** (content_mode `abstract_plus_summary:thinking`). The judges themselves (GPT-5.2, Opus 4.6, Gemini 3 Pro) run in standard mode — the `:thinking` tag refers to which summarizer produced the input, not the judge's reasoning mode.

## Ceiling Analysis

### What Limits the Maximum Achievable ρ?

The Spearman rank correlation between any ranking and the ICLR committee decisions is bounded by the **coarseness of the committee's 4-tier system** (Oral/Spotlight/Poster/Reject).

**The ceiling:** A perfect predictor that assigns every paper to the correct tier but randomly orders papers within each tier achieves ρ ≈ 0.878. This is the theoretical maximum — no method can exceed it using committee decisions as ground truth, because the committee provides no within-tier ordering information.

**Derivation:** With the actual tier distribution (20 Oral, 31 Spotlight, 126 Poster, 252 Reject = 429 papers with tiers), Spearman ρ between a perfect tier-sorted ranking and the committee's tied-rank ranking converges to exactly 0.878 regardless of within-tier ordering. This was verified empirically across 1,000 random within-tier permutations — the value is deterministic because Spearman handles ties by averaging ranks.

### Results in Context

| Method | ρ vs Committee | % of ceiling | What it means |
|---|---|---|---|
| Perfect tier predictor | 0.878 | 100% | Knows every paper's exact tier |
| **AI (actual)** | **0.762** | **87%** | Captures most of the tier signal + meaningful within-tier ordering |
| Random at 83% accuracy | 0.584 | 66% | Same cross-tier accuracy as AI but random within-tier |
| Single human expert | 0.681 | 78% | Limited by coarse 6-value scale producing noisy within-tier ordering |

### Key Finding: AI Has Within-Tier Signal

AI's ρ (0.762) significantly exceeds what its 82.9% cross-tier accuracy alone would predict (ρ ≈ 0.584 for random within-tier ordering at that accuracy). The gap (0.762 − 0.584 = 0.178) demonstrates that AI produces **meaningful within-tier ranking** — not just correct tier classification.

**Important caveat:** This within-tier signal was inferred entirely from cross-tier matches (see §Known Limitations, item 1). AI was never directly tested on within-tier pairs. The BT model extrapolates within-tier ordering from how papers perform against cross-tier opponents. Future validation runs with the corrected matchmaking will include direct within-tier comparisons.

This is a **conservative win for AI** over single human experts (0.762 vs 0.681):
- The human's higher pairwise accuracy (87.9% vs 82.9%) comes from **circularity** (their scores influenced the committee decisions)
- AI's ranking advantage is earned **without circularity** — it never saw the committee decisions or reviewer scores
- The human's within-tier ordering is near-random (constrained by the 6-value rating scale), while AI reads full papers and can make finer distinctions

### Selection Bias in Committee Comparison

A subtle bias inflates the Human vs Committee accuracy: when a reviewer ties on a paper pair (gives both the same score), those papers are more likely to be in the same tier — and same-tier pairs are excluded from the Committee comparison. This disproportionately drops "easy-to-agree-on" pairs (where both reviewer and committee would agree the papers are similar), enriching the remaining pairs with cases where the reviewer saw a difference. AI faces no such selection because it always produces a verdict. The effect is small relative to the circularity advantage but works in the same direction (favoring the human metric).
