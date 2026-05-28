# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system using multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4-6 (Emergent key), GPT-5.2/5.4 (direct key), Gemini 3 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup

## What's Been Implemented (Latest Session)

### Inter-Model Agreement Overhaul (May 2026)
- PW Match Agreement: actual pair-level agreement (not median-split)
- SI Score Agreement: with Full/Controlled toggle
- Controlled = exact PW shared pairs (intersection of models' match pairs)
- Both tables work for all-categories and per-category views

### Prompt Stability Experiments (May 2026)
- 3 experiments on 88-206 papers: baseline, with-reasons, extended (11 dimensions)
- Extended prompt adds: difficulty, surprisingness, reproducibility, translational_potential, evidence_strength, generalisability
- 11×11 correlation matrix, per-dimension histograms, ranked paper lists
- Validation Hub pages: Rating Stability + Extended Dimensions

### Featured Categories System (May 2026)
- Separated "featured" (homepage tabs) from "active" (tournament participation)
- AdminCategories rewritten: drag-reorderable featured + unified dropdown

### ICLR Match Pipelines (May 2026)
- Ran 16,395 matches across 4 ICLR sub-datasets (2025/2026 LLMs + Optimization)
- Fetched abstracts + summaries for 911 new papers
- Robust resumable pipeline with direct Anthropic fallback

### Other Changes
- Prediction experiment cleanup + timeseries endpoint optimization
- Qwen3-0.6B embedding evaluation
- Contact form (/contact page, honeypot + rate limit, admin Messages tab)
- User export CSV, privacy policy update (Google Search Console)
- PMI surprise/multidisciplinarity scores for Similarity Landscape

### Extended-Metrics List View Prototypes (Feb 2026)
- 5 candidate list-view designs at `/test/list-views`:
  - A=Table, C=Sparkline, D=Heatmap (red→green absolute)
  - E=Heatmap·Editorial (per-metric hue, Core/Extended divider, click-row reasoning, column sparklines)
  - F=Heatmap·Quantile (column-local percentile + viridis, click-cell pinned side-panel)
- Surface only directly-extracted summary metrics (no tournament data)
- Hover tooltip exposes per-metric one-sentence reasoning for extended dims
- Shared toolbar: title search, category multi-filter, per-metric min sliders, column show/hide, include/exclude N/A, persistent state in localStorage
- All views share `/app/frontend/src/pages/ListViewsTest/_shared.jsx` (METRICS, colormaps, percentile/histogram helpers, FilterBar)

## Production Stats (May 27, 2026)
- 20K+ papers, 500K+ matches across 32 categories
- Inter-model PW agreement: 71-73% (pair-level)
- Inter-model SI agreement: 85-87% (full), 78-79% (controlled)
- $/paper: $0.16 (current), down from $0.75 in February

## Known Issues
- ChemRxiv papers: MOCKED
- Twitter/X mobile unfurling: BLOCKED (Cloudflare WAF)
- K8s liveness probes: BLOCKED (infrastructure)

## Pending Tasks
- P0: Deploy latest changes to production
- P0: Add 5 categorical metrics to extended prompt (paper_type, contribution_type, code_available, research_maturity, comparative_result)
- P1: Semantic Search & "Papers Like This"
- P1: Multiple Reviewer Personas
- P1: Live ChemRxiv Fetcher
- P1: All-arXiv category expansion (~$1,400 backfill)
- P2: Scholarly positioning metric (highest-value skipped numerical metric)
