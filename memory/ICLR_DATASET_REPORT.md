# ICLR Dataset Quality & Suitability Report

## 1. Selection Methodology

### Source
The berenslab/iclr-dataset (GitHub) provides ICLR 2017–2024 submissions in Parquet format. Our import uses a locally extended version (iclr26v1) that also covers 2025.

### How subsets were selected
Each of our 8 topic subsets was imported separately using the `label_filter` parameter, which matches the berenslab 45-topic classification (derived from author keywords; 53.4% of papers labeled).

**Import filters applied per subset:**
- Year: 2024 + 2025
- Min reviews: 4 (requires ≥4 reviewer scores)
- Max papers: 80 (stratified sample if pool exceeds this)
- **Note:** The current import code also filters out Withdrawn and Desk Rejected papers, but our existing data was imported before this filter was added, so it includes 40 Withdrawn and 2 Desk Rejected papers.

**Stratified sampling:** When the filtered pool exceeds `max_papers`, papers are binned by avg score into 8 bins [0, 3, 4, 5, 5.5, 6, 7, 8, 11] and sampled equally from each bin (random_state=42). This ensures the full score range is represented, not just the modal 4–6 range.

### Topics chosen

| Topic | Papers | Why chosen |
|---|---|---|
| Code Generation | 62 | ML + software engineering intersection |
| Fairness | 68 | Safety/ethics — normatively complex for AI judges |
| LLMs | 73 | Core ICLR topic; highest volume |
| Molecules | 46 | Domain science (chemistry/drug discovery) |
| Optimization | 42 | Pure math/theory — tests AI on formal reasoning |
| Optimal Transport | 52 | Niche math topic — tests domain depth |
| PDEs & Dynamical Systems | 80 | Physics-informed ML — interdisciplinary |
| Protein Science | 46 | Biology/structural biology — domain-specific |

**Total: 469 papers from 8 topics**

## 2. Representativeness

### Coverage of full ICLR

| | Full ICLR 2024 | Full ICLR 2025 | Our subset |
|---|---|---|---|
| Total submissions | ~7,300 | ~11,600 | 469 |
| Our coverage | ~2.5% | ~2.4% | — |
| Accept rate | 31% | 32% | 37.7% |
| Avg reviews/paper | 3.7 | ~4 | 4.2 |
| Label coverage | 45 topics | 45 topics | 8 topics (18%) |

**Known biases in our selection:**

1. **Topic bias:** 8 out of 45 topics. We're missing major areas like Computer Vision, Reinforcement Learning, Graph Neural Networks, NLP (non-LLM), Generative Models, etc. Our topics skew toward math-heavy domains (OT, PDEs, Optimization) and domain sciences (Molecules, Protein), underrepresenting empirical/engineering-heavy work.

2. **Inflated accept rate (37.7% vs. 31–32%):** Our min_reviews=4 filter preferentially includes accepted papers (which tend to get more reviews). The Withdrawn/Desk Rejected papers in our data further inflate this to some degree.

3. **4+ review requirement:** ICLR averages 3.7 reviews/paper; requiring 4 skews toward papers that went through full review (not desk-rejected or early-withdrawn). This is desirable for benchmark quality but means our sample over-represents "serious" submissions.

4. **Score stratification:** The binned sampling ensures we have low-scoring papers (rejects), but the bin boundaries may slightly distort the natural score distribution.

## 3. Per-Topic Analysis

### 3a. Dataset Sizes

| Topic | Papers | 2024 | 2025 | Oral | Spotlight | Poster | Reject | Withdrawn |
|---|---|---|---|---|---|---|---|---|
| Code Gen | 62 | 21 | 41 | 5 | 2 | 14 | 32 | 9 |
| Fairness | 68 | 32 | 36 | 2 | 6 | 21 | 39 | 0 |
| LLMs | 73 | 22 | 51 | 6 | 7 | 14 | 28 | 17 |
| Molecules | 46 | 21 | 25 | 2 | 1 | 12 | 31 | 0 |
| Optimization | 42 | 20 | 22 | 1 | 5 | 9 | 27 | 0 |
| OT | 52 | 24 | 28 | 0 | 3 | 17 | 26 | 6 |
| PDEs | 80 | 30 | 50 | 2 | 3 | 27 | 48 | 0 |
| Protein | 46 | 15 | 31 | 2 | 4 | 12 | 19 | 8 |
| **Total** | **469** | **185** | **284** | **20** | **31** | **126** | **252** | **40** |

### 3b. Tier Score Separation

| Tier | n | Avg score | Std | Median | Range |
|---|---|---|---|---|---|
| Oral | 20 | 7.74 | 0.63 | 8.0 | 6.4–9.0 |
| Spotlight | 31 | 7.31 | 0.35 | 7.2 | 6.0–8.0 |
| Poster | 126 | 6.30 | 0.54 | 6.2 | 4.8–7.5 |
| Reject | 252 | 4.66 | 1.05 | 4.8 | 1.5–6.8 |
| Withdrawn | 40 | 3.99 | 1.03 | 4.0 | 2.0–6.0 |

**Tier gaps:**
- Oral vs Spotlight: +0.43 (Cohen's d = 0.85) — moderate, significant overlap (97% of Spotlights fall within Oral range)
- Spotlight vs Poster: +1.01 (Cohen's d = 2.24) — large, clean separation
- Poster vs Reject: +1.64 (Cohen's d = 1.97) — large, 56% of Rejects overlap with Poster range

### 3c. Rating Scale Properties

**Scale:** 1, 3, 5, 6, 8, 10 (6 distinct values on a 1–10 scale)

| Rating | Count | Fraction |
|---|---|---|
| 6 | 637 | 32.2% |
| 5 | 499 | 25.2% |
| 3 | 429 | 21.7% |
| 8 | 344 | 17.4% |
| 1 | 53 | 2.7% |
| 10 | 17 | 0.9% |

**67% of all ratings are 5 or 6** — the scale is severely concentrated in the middle, which directly causes the high tie rate.

### 3d. Tie Rates (Intra-Paper)

| Topic | Tie rate |
|---|---|
| Code Gen | 35.6% |
| Fairness | 37.4% |
| Optimization | 37.2% |
| Molecules | 38.0% |
| OT | 38.2% |
| Protein | 41.3% |
| LLMs | 41.7% |
| PDEs | 42.1% |
| **Average** | **~38.9%** |

Note: These are intra-paper tie rates (how often two reviewers on the same paper give the same score). The benchmark's tie rate is measured on pairwise comparisons across papers, which is different.

### 3e. AI Coverage

| Topic | Full text | AI thinking | AI plain | Single-item |
|---|---|---|---|---|
| Code Gen | 62/62 | 62/62 | 62/62 | 62/62 |
| Fairness | 68/68 | 68/68 | 68/68 | 68/68 |
| LLMs | 73/73 | 73/73 | 73/73 | 73/73 |
| Molecules | 46/46 | 46/46 | 46/46 | 46/46 |
| Optimization | 42/42 | 42/42 | 42/42 | 42/42 |
| OT | 52/52 | 52/52 | 52/52 | **0/52** |
| PDEs | 80/80 | 80/80 | 80/80 | 80/80 |
| Protein | 46/46 | 46/46 | 46/46 | 46/46 |

**All datasets have 100% full text and AI summary coverage.** OT is the only one missing single-item scores.

## 4. Key Quality Issues

### 4a. Positional Reviewer Labels
All reviewer identities are positional (`Reviewer_1`, `Reviewer_2`, ...). "Reviewer_1" on paper A is a different person than "Reviewer_1" on paper B. This means:
- Inter-rater analyses treat positional labels as real identities — concordance between "Reviewer_1" and "Reviewer_2" measures agreement between the 1st-listed and 2nd-listed reviewers (essentially random pairs)
- "Equal-weighted per reviewer pair" is effectively "equal-weighted per dataset"
- Cannot identify individual reviewer effects (lenient/harsh graders)

Within our small topic subsets (42–80 papers each), the real overlap between reviewers is low — a given ICLR reviewer typically handles 4–6 papers from a pool of thousands, so the chance of reviewing 2+ papers within one of our 42–80 paper subsets is small. The positional approximation is therefore reasonable.

### 4b. Coarse Rating Scale
Only 6 distinct values (1, 3, 5, 6, 8, 10) produce a ~39% tie rate. The coin-flip correction addresses this for the benchmark, but it means ~39% of all pairwise human preferences are randomly assigned rather than real signal.

### 4c. Decision Label Inconsistency
The berenslab data uses mixed casing: `Accept (Poster)` vs `Accept (poster)`, `Accept (Oral)` vs `Accept (oral)`. Both forms appear in our data and need normalization for tier-based analyses.

### 4d. Year Imbalance
2025 papers (284) outnumber 2024 papers (185) by ~1.5:1. If review standards or the rating scale shifted between years, this could introduce confounding. However, the same 1–10 scale was used in both years.

## 5. Suitability Assessment

### Strengths
1. **Clean tier separation** — particularly Poster vs Reject (d=1.97) and Spotlight vs Poster (d=2.24). This provides unambiguous ground truth for most pairwise comparisons.
2. **100% AI coverage** — all papers have full text, AI summaries (plain + thinking), and pairwise matches.
3. **Good sample size** — 469 papers with 3,956 controlled pairs provides strong statistical power.
4. **Topic diversity** — 8 topics spanning theory (OT, Optimization), applications (Molecules, Protein), and systems (Code Gen, LLMs) test AI judgment across different research styles.
5. **4+ reviews per paper** — higher review coverage than the ICLR average, giving more reliable per-paper consensus.

### Weaknesses
1. **Topic coverage is narrow** — 8 of 45 topics, skewing toward math/science domains. Major areas like CV, RL, and NLP are absent.
2. **No true reviewer identity** — limits per-reviewer analysis and makes the "equal-weighted" metric less interpretable.
3. **Coarse scale + high tie rate** — ~39% of preferences are noise, addressed but not eliminated by coin-flip correction.
4. **Oral/Spotlight overlap** — Oral and Spotlight are barely distinguishable by score (d=0.85), so treating them as separate tiers adds noise. The difficulty stratification already accounts for this (gap=1 → "medium" difficulty).
5. **Withdraw inclusion** — 40 Withdrawn papers provide extra negative signal but may have incomplete reviews or atypical characteristics.

### Overall Verdict
**Strong dataset for comparative GT benchmarking.** The Poster-Reject and Spotlight-Poster separations are clean enough for meaningful tier accuracy measurement. The main limitations (positional labels, coarse scale) are shared with essentially all available peer review datasets and are methodologically handled (coin-flip, difficulty stratification). The topic selection provides reasonable diversity but would benefit from expansion into empirical ML domains (CV, RL, NLP).
