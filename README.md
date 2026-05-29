# Kurate — AI-Powered Scientific Paper Ranking

**[kurate.org](https://kurate.org)**

Kurate is an AI paper-judging platform that ranks academic papers using multiple LLM judges through pairwise tournaments and single-item assessments. It covers 30+ arXiv categories with daily paper ingestion, automated summarization, and TrueSkill-based ranking.

## How It Works

Papers are evaluated through two complementary methods:

- **Pairwise Tournament (PW)**: Three LLM judges (Claude Opus 4.6, GPT-5.2, Gemini 3 Pro) independently compare pairs of papers head-to-head. TrueSkill ratings are computed from win/loss records across ~45 matches per paper.
- **Single-Item Assessment (SI)**: Each model writes a detailed impact assessment and assigns numerical scores (significance, rigor, novelty, clarity) on a 1-10 scale.

Rankings are derived from the pairwise tournament, while single-item scores provide per-paper profiles and enable validation experiments.

## Architecture

```
├── backend/           FastAPI + MongoDB (Motor async)
│   ├── core/          Config, auth, category taxonomy
│   ├── routers/       API endpoints (leaderboard, admin, outreach, validation)
│   ├── services/      Scheduler, ranking, LLM integration, model analysis
│   ├── scripts/       Validation match pipelines
│   └── prompts/       Prompt templates (production + experimental)
├── frontend/          React + Shadcn/UI + Recharts
│   ├── components/    Reusable UI (InterModel, CategoryTabs, AdminCategories)
│   └── pages/         Leaderboard, Correlation, Validation Hub, Admin
├── tools/             Offline analysis scripts (embeddings, experiments, metrics)
└── memory/            Experiment results, match outputs, PRD
```

### Key Design Decisions

- **Dual-pod architecture**: Leader pod runs background loops (fetch, compare, summarize); follower pod handles HTTP only. Leader election via MongoDB lock with heartbeat.
- **Quality-based matchmaking**: Opponents selected by maximizing TrueSkill draw probability — papers are matched against similarly-ranked opponents for maximum information gain.
- **Round-robin judging**: Each match is assigned to one of three models in rotation, ensuring balanced coverage. Inter-model agreement is tracked continuously.
- **Resumable pipelines**: All batch operations (match generation, summarization, embedding) write results incrementally to JSONL and check for existing completions before running.

## Features

### Leaderboard
- Per-category paper rankings with confidence intervals
- Featured categories (admin-configurable homepage tabs) + "More" dropdown for all categories
- Paper detail pages with AI summaries, scores, and match history

### Model Analysis (`/correlation`)
- Inter-model agreement: match-level PW and SI agreement with Full/Controlled/Tiebreak modes
- PW and SI ranking correlations (Spearman) across all model pairs
- Score-Pairwise Coherence: does a model's SI score predict its PW pick?
- Simulated tournament: what ranking correlation would SI scores achieve through a pairwise tournament?

### Validation Hub (`/validation`)
- ICLR 2024-2026 benchmark: AI rankings vs human reviewer consensus
- Prompt stability experiments: baseline, with-reasons, extended (11 dimensions)
- Extended dimensions: difficulty, surprisingness, reproducibility, translational potential, evidence strength, generalisability
- Similarity Landscape: 2D UMAP projections with multiple embedding methods (OpenAI, SciNCL, SPECTER, Qwen3-0.6B)
- PMI-based multidisciplinarity scores

### Admin Panel (`/admin`)
- Category management: active/featured with drag-reorder
- Tournament controls: pause, archive frequency, convergence thresholds
- Statistics: daily timeseries (with date range + per-category), cost tracking, user registrations
- Outreach: X/Twitter pipeline, Gmail-based author notifications
- Contact messages, user export

## LLM Integration

All LLM calls route through the Emergent proxy with direct API key fallback:

| Model | Usage | Key |
|---|---|---|
| Claude Opus 4.6 | Summaries (thinking mode), pairwise judging | Emergent LLM Key |
| GPT-5.2 / 5.4 | Pairwise judging, summaries | Direct OpenAI Key |
| Gemini 3 Pro | Pairwise judging, summaries | Emergent LLM Key |

## Data Model

- **`papers`**: Metadata, abstracts, full text, per-model summaries with embedded JSON ratings
- **`rankings`**: TrueSkill scores (mu/sigma), per-model stats, SI ratings, comparisons count
- **`matches`**: Pairwise comparison results with winner, reasoning, model used, tokens
- **`validation_papers`** / **`validation_matches`**: ICLR benchmark datasets

## Development

### Prerequisites
- Python 3.11+, Node.js 18+, MongoDB
- Environment variables: `MONGO_URL`, `EMERGENT_LLM_KEY`, `OPENAI_API_KEY_DIRECT`, `ANTHROPIC_API_KEY`

### Running locally
```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001

# Frontend
cd frontend && yarn install && yarn start
```

### Key scripts
```bash
# Run ICLR validation matches
python3 backend/scripts/validation_match_pipeline.py --csv matches.csv --parallel 30

# Prompt stability experiment
python3 tools/prompt_stability_experiment.py --experiment 3 --n 100 --parallel 3

# Precompute SI vs PW simulation
python3 tools/precompute_si_pw_simulation.py

# Compute embedding quality metrics
python3 tools/compute_quality_metrics_embeddings.py
```

## Cost

At current scale (20K+ papers, 500K+ matches across 32 categories):
- **$0.16/paper** all-in (down from $0.75 at launch)
- Match costs: 54% | Summary costs: 46%
- Dominant cost: Claude Opus thinking summaries

## License

Proprietary. All rights reserved.
