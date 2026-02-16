# AI Model Benchmark Lab — PRD

## Original Problem Statement
Build a comprehensive system for validating and comparing the performance of AI models on scientific papers.

## Datasets
- ICLR Protein Science (46 papers), ICLR LLMs (73), PeerRead ACL 2017 (80), Qeios, SciPost
- F1000Prime Alzheimer's (54 papers)
- **ResearchHub (994 papers)** — largest pairwise validation dataset

## Key Results: ResearchHub (2076 pairs, 994 papers)
| Metric | Abstract | Abstract + Summary |
|--------|----------|-------------------|
| **Aggregate AI vs Expert** | **67.2%** | **67.9%** |
| GPT-5.2 | 68.2% | 67.8% |
| Claude Opus 4.5 | 68.1% | 67.7% |
| Gemini 3 Pro | 65.2% | 68.0% |

### By Score Gap (Abstract + Summary)
| Gap | Agreement | N |
|-----|-----------|---|
| Small (1pt) | 63.8% | 1559 |
| Medium (2pts) | 77.4% | 420 |
| Large (3+pts) | **90.9%** | 99 |

## ResearchHub-50 (Well-Connected Subset)
- **50 papers**, single connected component, 115 discriminative human preference pairs, 24 evaluators
- Extracted from the 3-core of the largest connected component in full ResearchHub dataset
- Graph density 9.39%, avg degree 4.6 (29 papers single-review, 21 with ≥2)
- **Tournament results (767 AI matches, 30.7 avg/paper)**:
  - Spearman ρ = 0.440 (p=0.001), Kendall τ = 0.285, Pearson r = 0.443
  - AI vs Expert agreement: 74.3%
  - Convergence: ρ rises from 0.22 → 0.47 (clear upward trend)

## ResearchHub-62 (≥2 Reviews Subset)
- **62 papers**, every paper has ≥2 reviews, 94 discriminative human pairs, 55 evaluators
- Extracted from largest connected component of ≥2-review papers only
- Graph density 4.97%, avg degree 3.0, 35 pairs with ≥2 independent evaluators
- **Tournament results (918 AI matches, 29.6 avg/paper)**:
  - Spearman ρ = 0.266, Kendall τ = 0.176, Pearson r = 0.246
  - AI vs Expert agreement: 71.7%
  - Convergence: ρ ~0.25 (lower than RH-50 due to sparser graph)
- **Key insight**: ≥2 review constraint reduces graph density, weakening human ground truth ranking

## eLife Neuroscience (New Dataset)
- **100 papers**, all Neuroscience, from eLife's structured editorial assessments
- **Significance score** as ground truth (useful→landmark, 4 active levels in subset)
  - Strength excluded: measures methodological rigor unassessable from abstracts alone
- 53 editors, fully connected graph, **31.6% density**, avg degree 31.3 (min 20)
- **1,590 human discriminative pairs** from editor significance judgments
- **Tournament results**:

  | Mode | Spearman ρ | AI vs Expert | Convergence peak |
  |------|-----------|-------------|-----------------|
  | Abstract only | 0.268 | 64.9% | 0.28 |
  | **Abstract + AI Summary** | **0.404** | **69.6%** | **0.41** |
  
  Adding Claude Opus 4.5 impact summaries boosted correlation by +51% (0.27→0.40)
- **Key insight**: Coarse significance scale (only 4 levels) limits ranking precision — many papers share same label, weakening ground truth ranking compared to finer-grained review scores

## Graph Connectivity Analysis
- **ResearchHub-100** had 12 disconnected components → flat convergence (ρ ≈ 0.2)
- **ResearchHub-50** is fully connected → meaningful convergence to ρ ≈ 0.47
- Added graph connectivity diagnostic to convergence API + frontend indicator

## Recent Changes (Feb 15, 2026)
### Summary Bias Experiment
- Built full pipeline to test whether the LLM that wrote a summary biases the judge
- **Biomolecules (q-bio.BM)**: 50 papers, 150 summaries, 1800 evaluations, 600 full-PDF baseline
- **Economics (econ.GN)**: 51 papers, 153 summaries, 1799 evaluations, 600 full-PDF baseline
- Key finding: Against full-PDF baseline, all 3 summary models perform within ~2pp (79-82%)
- Claude summaries produce highest inter-judge consistency in both categories (83-85%)
- GPT 5.2 shows strongest self-consistency (84-88% own summary vs own full-PDF)
- Self-bias is mild for Claude (~0-4.5pp), but GPT 5.2 shows +10.3pp in Economics
- New collections: `summary_bias_summaries`, `summary_bias_matches`
- Frontend: "Experiments" section with per-category views, 3×3 heatmaps, self-bias cards, consistency bars

### Previous session
- Removed ResearchHub-100 (12 disconnected components, poor convergence)
- Created `researchhub-62` dataset: ≥2 reviews per paper, connected, 62 papers, 918 AI matches
- Created `researchhub-50` dataset: densest connected subset, 50 papers, 767 AI matches
- Ran 30-match/paper tournaments on both new datasets
- Added graph connectivity diagnostics to `/api/validation/convergence` endpoint
- Added human evaluator count to convergence summary panel
- Frontend shows connectivity status (green/amber) and expert count in convergence summary
- Rebuilt frontend with correct REACT_APP_BACKEND_URL (was serving stale build)
- Previous: Expanded ResearchHub to 4 pairs/reviewer, human pairwise ground truth, score gap chart

## SciPost Pairwise
- Restructured to match other pairwise views (bar charts, dimension cards, per-model chart)
- Added Abstract + Summary mode with full-text-based Claude Opus 4.5 AI impact summaries
- 33 papers, 872 pairs per mode, 3 input formats (Abstract, Extract, Abstract + Summary)
- Full text obtained via arXiv PDFs for all 33 papers
- Per-dimension results (Abstract + Summary): Validity 62.9%, Significance 51%, Originality 50%, Clarity 42.5%

## Key Files
- `backend/routers/summary_bias.py` — Summary bias experiment pipeline and results
- `frontend/src/pages/SummaryBiasSection.jsx` — Summary bias results UI
- `backend/routers/validation.py` — Core validation, convergence (now with graph connectivity + expert count)
- `frontend/src/components/ConvergenceSection.jsx` — Convergence charts with connectivity + expert indicator
- `backend/services/rh_scraper.py` — ResearchHub API scraper
- `frontend/src/pages/PairwiseAgreementSection.jsx` — Score gap chart, per-model fix
- `/tmp/elife_neuro.json` — Cached eLife Neuroscience scan data (769 articles)

## Pending
- P1: Phase 4 — Backfill summaries for existing papers, migration testing
- P1: Add "View Prompts" modal to SciPost page
- P2: Resume ICLR LLMs multi-model runs

## Architecture Update: Summary-First Pipeline (Phases 1-3 Complete)
- Replaced section extraction with pre-generated AI impact summaries as tournament input
- On paper fetch: download PDF → generate 3 AI summaries (Claude, Gemini, GPT) → store in `papers.summaries`
- Tournament now uses `content_mode="abstract_plus_summary"` with admin-configurable summary source
- New admin setting: `summary_source` ("claude", "gemini", "gpt", "round_robin")
- Convergence-based stopping: Spearman ρ stability check replaces CI-based stopping
- New settings: `convergence_threshold` (0.95), `convergence_rounds` (3), reduced `max_matches_per_paper` (20)
- **Phase 2 (Feb 16)**: Replaced complex UCB/CI-based pair selection with simplified round-robin (top-K cross-matches → deficit papers → general round-robin)
- **Phase 3 (Feb 16)**: Paper Detail page now shows tabbed AI summaries (Claude/Gemini/GPT) with fallback to legacy `impact_summary`
- Removed: `ci_target`, `section_char_limit` settings, `wilson_margin_pct` dependency in scheduler
- Prompts page now shows pre-comparison IMPACT_ASSESSMENT_PROMPT instead of post-hoc summary prompt

## Backlog
- Explore eLife as complementary dataset
- Experiment with different LLMs (Gemini 3 Flash)
- Refactor data processing into services layer
- Add missing HTTP security headers
- Full security scan review
