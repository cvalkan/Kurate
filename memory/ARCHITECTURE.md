# Kurate.org — Platform Architecture

## 1. System Overview

### 1.1 Mission

Kurate.org is an AI-powered scientific paper ranking platform. It benchmarks how well AI judges agree with each other — and eventually with human peer reviewers — on the relative scientific impact of academic papers. Papers are compared pairwise by multiple LLM judges (GPT-5.2, Claude Opus 4.6, Gemini 3 Pro), and the tournament produces ranked leaderboards per research category.

The platform serves two audiences:
- **Researchers** browsing ranked leaderboards of recent papers in their field
- **Methodology researchers** studying how well AI ranking methods (Win-Rate, TrueSkill, OpenSkill) correlate with human judgments

### 1.2 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Cloudflare                               │
│                    (DNS, CDN, Bot Protection)                     │
└──────────────┬───────────────────────────────────┬───────────────┘
               │                                   │
               ▼                                   ▼
┌──────────────────────────┐     ┌──────────────────────────────────┐
│     React Frontend       │     │         FastAPI Backend           │
│  (Compiled production    │     │                                   │
│   bundle served by       │     │  ┌─────────────┐ ┌────────────┐  │
│   FastAPI static files)  │     │  │   Routers   │ │  Services  │  │
│                          │     │  │ leaderboard │ │ scheduler  │  │
│  Pages:                  │     │  │ admin       │ │ ranking    │  │
│  - Leaderboard           │     │  │ validation  │ │ llm        │  │
│  - Paper Detail          │     │  │ claims      │ │ model_     │  │
│  - Model Correlation     │     │  │             │ │ analysis   │  │
│  - Validation            │     │  └─────────────┘ └────────────┘  │
│  - Methodology           │     │          │              │         │
│  - Admin Panel           │     │          ▼              ▼         │
└──────────────────────────┘     │  ┌──────────────────────────┐    │
                                 │  │   Background Tasks        │    │
                                 │  │  - Compare loop           │    │
                                 │  │  - Fetch loop             │    │
                                 │  │  - Analysis cache loop    │    │
                                 │  │  - Archive loop           │    │
                                 │  └──────────────────────────┘    │
                                 └──────────────┬───────────────────┘
                                                │
                    ┌───────────────────────────┼───────────────────┐
                    │                           │                   │
                    ▼                           ▼                   ▼
           ┌──────────────┐          ┌──────────────┐    ┌──────────────┐
           │   MongoDB    │          │  ArXiv API   │    │  LLM APIs    │
           │              │          │  ChemRxiv    │    │  (Emergent   │
           │  papers      │          │              │    │   Proxy)     │
           │  rankings    │          └──────────────┘    │              │
           │  matches     │                              │  Claude 4.6  │
           │  settings    │                              │  GPT-5.2     │
           │  analysis_   │                              │  Gemini 3    │
           │    store     │                              │  Pro         │
           │  system_logs │                              └──────────────┘
           │  + 40 more   │
           └──────────────┘
```

### 1.3 Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Tailwind CSS, Shadcn/UI, compiled production bundle |
| Backend | FastAPI (Python 3.11), async throughout |
| Database | MongoDB (Motor async driver) |
| LLM Gateway | Emergent Universal Key via litellm proxy |
| Paper Sources | ArXiv API, ChemRxiv API |
| PDF Extraction | PyMuPDF (fitz) in thread pool |
| Hosting | Kubernetes container (2GB RAM), Cloudflare DNS/CDN |

### 1.4 Current Scale (April 2026)

| Metric | Value |
|--------|-------|
| Active categories | 14 (spanning CS, Physics, Chemistry, Economics, Biology, Cosmology) |
| Total papers | ~5,100 across all categories |
| Total tournament matches | ~146,000 |
| Validation matches | ~150,000 (benchmark experiments) |
| Match throughput | ~50 matches/min (20 parallel LLM agents) |
| Peak RSS memory | ~550 MB (in 2 GB container) |
| LLM cost to date | ~$690 |

**Per-category breakdown (production, April 7 2026):**

| Category | Papers | Matches | Goals Met |
|----------|--------|---------|-----------|
| cs.RO (Robotics) | 1,736 | 43,347 | ✓ |
| cs.CR (Cryptography) | 823 | 23,140 | ✓ |
| cs.DC (Distributed Computing) | 424 | 14,199 | ✓ |
| physics.chem-ph (Chemical Physics) | 303 | 11,116 | ✓ |
| quant-ph (Quantum Physics) | 445 | 10,303 | ✓ |
| cs.GT (Game Theory) | 288 | 9,224 | ✓ |
| econ.GN (Economics) | 204 | 7,021 | ✓ |
| cs.IT (Information Theory) | 288 | 6,807 | ✓ |
| physics.comp-ph (Computational Physics) | 192 | 6,398 | ✓ |
| q-bio.BM (Biomolecules) | 92 | 4,944 | ✓ |
| chemrxiv.IC (Inorganic Chemistry) | 50 | 4,048 | ✓ |
| cond-mat.mtrl-sci (Materials Science) | 94 | 2,286 | ✓ |
| astro-ph.CO (Cosmology) | 71 | 1,849 | ✓ |
| cs.SI (Social Networks) | 55 | 1,180 | ✓ |

---

## 2. Data Model

All data lives in a single MongoDB database. Collections fall into four groups: **core tournament data**, **caching/materialized views**, **validation experiments**, and **user/admin state**.

### 2.1 Core Collections

#### `papers`
The source of truth for all paper metadata and content. One document per paper.

```
{
  id:           "uuid-v4",              // Primary key (not MongoDB _id)
  arxiv_id:     "2604.03121v1",         // Source identifier (ArXiv)
  chemrxiv_id:  "...",                  // Source identifier (ChemRxiv), if applicable
  doi:          "10.xxxx/...",          // DOI, if available
  title:        "Paper Title",
  authors:      ["Author 1", ...],      // Capped at 8
  abstract:     "...",                  // Capped at 2000 chars
  categories:   ["cs.CR", "cs.AI"],     // categories[0] = primary category
  published:    "2026-04-01T...",       // ISO 8601
  link:         "https://arxiv.org/abs/...",
  pdf_link:     "https://arxiv.org/pdf/...",
  added_at:     "2026-04-01T...",       // When ingested by Kurate

  // Content
  full_text:    "...",                  // Extracted PDF text (null if not yet downloaded)
  needs_pdf:    false,                  // True = new paper, needs PDF download
  pdf_failed:   true,                   // True = PDF download failed (won't auto-retry)
  pdf_fail_reason: "timeout",           // Failure classification
  dedup_hash:   "a1b2c3d4e5f6g7h8",    // SHA-256(normalized_title|first_author)[:16]

  // AI Summaries (one per model)
  summaries: {
    "anthropic:claude-opus-4-6:thinking": "...",   // Claude with extended thinking
    "openai:gpt-5_2":                    "...",   // GPT-5.2
    "gemini:gemini-3-pro-preview":       "...",   // Gemini 3 Pro
  },
  summary_dates: {                                 // When each summary was generated
    "anthropic:claude-opus-4-6:thinking": "2026-04-01T...",
    ...
  },
  summary_tokens: {                                // Token usage per model
    "openai:gpt-5_2": {"input": 45000, "output": 1200},
    ...
  },

  // AI Ratings (extracted from summary JSON block)
  ai_rating:    7.6,                    // Primary rating (from Claude Thinking)
  ai_ratings_by_model: {                // Per-model structured ratings
    "claude": {"score": 7.6, "significance": 8, "rigor": 7, "novelty": 8, "clarity": 7},
    "gpt":    {"score": 7.2, ...},
    "gemini": {"score": 7.4, ...},
  },
}
```

**Indexes:**
- `id_1` — primary lookup
- `arxiv_id_1` — dedup on fetch
- `chemrxiv_id_1` — dedup for ChemRxiv
- `dedup_hash_unique` — content-based dedup (unique)
- `categories_summaries` — compound: filter by category + summary existence (matchability check)
- `published_1` — date-range queries

#### `rankings`
Materialized leaderboard entries. One document per paper per category. Updated incrementally when matches complete — never recomputed from scratch during normal operation.

```
{
  paper_id:     "uuid-v4",              // FK to papers.id
  category:     "cs.CR",               // Primary category

  // Ranking scores
  score:        1876,                   // Regularized Win-Rate score
  rank:         1,                      // Position in category (by score desc)
  win_rate:     98.9,                   // Raw win percentage
  ci:           130,                    // Confidence interval (display)
  wilson_margin: 1.2,                   // Wilson score interval margin (%)
  wins:         347,
  losses:       4,
  comparisons:  351,

  // TrueSkill scores
  ts_score:     1850,                   // Display score = mu * 100
  ts_mu:        32.1,                   // TrueSkill mu (mean)
  ts_sigma:     1.2,                    // TrueSkill sigma (uncertainty)
  rank_ts:      2,                      // Rank by TrueSkill
  rank_wr:      1,                      // Rank by Win-Rate

  // Per-model stats (for inter-model correlation analysis)
  model_stats: {
    "anthropic/claude-opus": {"wins": 120, "losses": 2, "total": 122},
    "openai/gpt-5_2":       {"wins": 115, "losses": 1, "total": 116},
    "gemini/gemini-3-pro-preview": {"wins": 112, "losses": 1, "total": 113},
  },
  model_ts: {
    "anthropic/claude-opus": 1860,      // Per-model TrueSkill score
    ...
  },

  // Denormalized paper metadata (serves leaderboard without joins)
  title:        "...",
  authors:      [...],
  arxiv_id:     "2604.03121v1",
  link:         "...",
  published:    "...",
  added_at:     "...",

  // Enrichments
  ai_rating:    7.6,                    // From paper's Claude rating
  gap_score:    1.5,                    // Score - AI rating divergence
  community_likes: 42,                 // From AlphaXiv integration

  // Materialized fields
  unique_opponents: 287,                // Count of distinct opponents faced (O(1) stall check)
  updated_at:   "2026-04-07T...",
}
```

**Key indexes:**
- `category_1_rank_1` — primary leaderboard query
- `category_1_score_-1` — re-ranking after score updates
- `paper_id_1` — lookup by paper ID
- `category_1_ts_score_-1` — TrueSkill-sorted leaderboard
- `category_1_wilson_margin_1` — convergence goal checks
- `category_1_ts_sigma_1` — uncertainty-based matchmaking

The `unique_opponents` field is critical: it enables O(1) stall detection per paper. Without it, determining whether a paper has faced all possible opponents requires an expensive aggregation over the matches collection.

#### `matches`
Every pairwise comparison judged by an LLM. One document per match.

```
{
  id:               "uuid-v4",
  paper1_id:        "uuid-v4",
  paper2_id:        "uuid-v4",
  winner_id:        "uuid-v4",         // Which paper won
  model_used:       {"provider": "anthropic", "model": "claude-opus-4-6"},
  reasoning:        "Paper 1 proposes...",   // LLM's explanation

  completed:        true,
  failed:           false,              // True if LLM call failed
  primary_category: "cs.CR",           // For category-scoped queries
  shared_categories: ["cs.CR", "cs.AI"],

  // Deduplication
  dedup_pair:       "cs.CR|uuid-a|uuid-b",  // Sorted pair key (prevents duplicate matches)

  created_at:       "2026-04-07T...",
}
```

**Key indexes:**
- `primary_category_1_completed_1_failed_1_mode_1` — compound: the workhorse query for loading category matches
- `pair_dedup_idx` on `(primary_category, dedup_pair)` — unique constraint preventing duplicate comparisons
- `paper1_id_1`, `paper2_id_1` — per-paper match lookup

The `dedup_pair` field is constructed as `category|min(id1,id2)|max(id1,id2)` to guarantee each pair is compared at most once per category.

### 2.2 Caching & Materialized Views

#### `analysis_store`
Precomputed OpenSkill correlation data. Expensive to compute (requires replay of all matches through the OpenSkill algorithm), so it's stored persistently and only refreshed on admin request.

```
{
  _type:  "openskill-cache",
  key:    "cs.CR",                     // Category or "__all__"
  os_global: {                         // Global OpenSkill scores
    os1:  {"paper-uuid": 1850, ...},   // 1-phase OpenSkill
    os3:  {"paper-uuid": 1820, ...},   // 3-phase
    os10: {"paper-uuid": 1790, ...},   // 10-phase
  },
  os_per_model: {                      // Per-model OpenSkill scores
    "anthropic/claude-opus": {"os1": {...}, "os3": {...}, "os10": {...}},
    ...
  },
  computed_at: "2026-04-07T...",
}
```

#### `convergence_cache`
Precomputed convergence curves (ranking stability as matches accumulate). One document per category.

#### `system_logs`
Time-series memory/event tracking with a 7-day TTL index. Used for the admin memory usage chart.

```
{
  ts:     "2026-04-07T15:00:00Z",      // TTL-indexed
  type:   "memory",                    // or "event"
  rss_mb: 450,                         // Process RSS in MB
  event:  "scheduler_restart",         // Optional event marker
}
```

### 2.3 Settings

#### `settings`
Global configuration. The document with `key: "global"` holds all admin-configurable settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `parallel_agents` | 20 | Concurrent LLM calls per category per round (hard cap: 20) |
| `parallel_categories` | 10 | Categories processed simultaneously in compare loop |
| `max_pairs_per_round` | 100 | Max pairs selected per category per round |
| `compare_loop_interval` | 60 | Seconds between compare loop cycles when goals are met |
| `ci_target` | 10 | Top-K convergence threshold (Wilson margin %) |
| `ci_target_general` | 15 | General convergence threshold (Wilson margin %) |
| `top_k_focus` | 10 | Number of top papers to prioritize |
| `summary_source` | "claude" | Which model's summary to use in tournament comparisons |
| `summary_parallel` | 10 | Concurrent summary generation calls |
| `max_papers_per_fetch` | 50 | Papers to fetch per ArXiv API call |
| `fetch_interval_hours` | 2 | Hours between auto-fetch cycles |
| `calibration_ratio` | 50 | % of matches allocated to uncertain papers vs top-K cross-matches |

### 2.4 Validation & Experiment Collections

These support the Validation page (benchmarking AI judges against human reviewers):

- **`validation_datasets`** (26) — registered benchmark datasets (ICLR, SciPost, eLife, etc.)
- **`validation_matches`** (150K) — pairwise comparisons on benchmark papers
- **`validation_papers`** (3.4K) — papers from benchmark datasets
- **`pairwise_comparisons`**, **`scipost_pairwise`**, **`qeios_pairwise_*`** — source-specific benchmark data
- **`deep_dive_*_replays`** — replayed tournament experiments for specific subfields

### 2.5 User & Admin State

- **`users`** (27) — registered users (Google OAuth)
- **`user_sessions`** (78) — active sessions
- **`admin_sessions`** — admin panel sessions (password-based)
- **`bookmarks`**, **`reading_lists`**, **`suggestions`** — user engagement features
- **`leaderboard_archives`** (112) — daily snapshots for historical tracking
- **`ranking_snapshots`** (744) — finer-grained snapshots for convergence analysis
