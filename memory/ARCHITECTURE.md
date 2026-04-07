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

---

## 3. Tournament Engine

### 3.1 Pairwise Comparison

The core ranking mechanism is pairwise comparison: two papers are presented to an LLM judge, which decides which has higher scientific impact. The judge sees both papers' AI-generated summaries (not raw PDFs) and returns a winner plus reasoning.

Each match is judged by one of three models, selected round-robin across matches:
- Claude Opus 4.6 (Anthropic)
- GPT-5.2 (OpenAI)
- Gemini 3 Pro (Google)

This multi-model approach serves two purposes: it distributes load across providers and generates per-model statistics used in the Model Correlation analysis page.

### 3.2 Scoring Methods

Three ranking methods run simultaneously on the same match data:

**Regularized Win-Rate (primary)**
The default leaderboard ranking. For each paper:
```
p_reg = (wins + 0.5) / (comparisons + 1.0)    # Laplace-smoothed win rate
score  = 400 × log10(p_reg / (1 - p_reg)) + 1200   # Elo-like scale
```
Wilson score confidence interval provides the uncertainty margin. A paper with 10 wins / 10 comparisons and one with 100/100 have the same win rate but very different confidence intervals — the second is much more certain.

**TrueSkill**
Microsoft's Bayesian rating system. Each paper has a mean (μ) and uncertainty (σ). After each match, both are updated using Bayesian inference. Papers with high uncertainty are more informative to match — this property could drive future matchmaking optimizations (see Roadmap: TrueSkill-first matchmaking).

**OpenSkill**
An open-source alternative to TrueSkill, computed with 1-phase, 3-phase, and 10-phase variants. Unlike WR and TrueSkill which are updated incrementally, OpenSkill requires replaying all matches through the algorithm. It's computed in the background and stored in `analysis_store`, then merged into the model-analysis API response.

### 3.3 Convergence Goals

The tournament runs until three convergence goals are met for each category:

**Goal 1 — General CI ≤ ci_target_general (default 15%)**
Every non-top-K paper's Wilson confidence margin must be ≤ 15 percentage points. This ensures the ranking order is statistically meaningful for the bulk of papers.

**Goal 2 — Top-K CI ≤ ci_target (default 10%)**
The top K papers (default K=10) must have tighter confidence — ≤ 10 percentage points. The top of the leaderboard needs more precision since users care most about which papers are #1 vs #2.

**Goal 3 — Top-K cross-matches**
Every pair of top-K papers must have been directly compared at least once. This prevents a scenario where paper A and paper B are both ranked highly but have never been compared head-to-head.

Goals are checked at the start of each compare loop cycle. The check is cached for 60 seconds to avoid DB load. When all goals are met, the compare loop sleeps until new data arrives (new papers, configuration change, or wake signal).

### 3.4 Matchmaking Algorithm

Pair selection is goal-directed — it prioritizes matches that maximally reduce uncertainty toward the convergence targets.

**Step 1: Urgency ranking**
Each paper gets an urgency score = `margin - target`. Papers with the widest gap between their current Wilson margin and their target CI are matched first. New papers (0 comparisons) get maximum urgency (999).

**Step 2: Opponent selection with calibration**
For each urgent paper, an opponent is selected:
- **Calibration matches** (controlled by `calibration_ratio`, default 50%): Pair with an *established* paper (already converged) whose score is closest to the needy paper's score. This calibrates the new paper against the known ranking.
- **Exploration matches**: Pair with another needy paper (highest mutual urgency).
- **Fallback**: Any paper that hasn't been compared against this one yet.

**Step 3: Top-K cross-match gap-filling**
After urgency-based pairs, any remaining capacity fills gaps in the top-K cross-match grid (Goal 3).

**Dedup guarantee**: Pairs are checked against the `dedup_pair` index on the `matches` collection. No pair is ever compared twice in the same category. The `dedup_pair` field is `category|min(id1,id2)|max(id1,id2)`.

**Positional bias mitigation**: Within each match, which paper is presented as "Paper 1" vs "Paper 2" is randomized with a fair coin flip (`secrets.randbelow(2)`).

### 3.5 Stall Detection

A paper is "stalled" when it needs a tighter CI but has already been compared against every other matchable paper in the category. Since each pair can only be compared once, no further matches are possible for that paper.

Detection uses the materialized `unique_opponents` field on rankings:
```
stalled = (wilson_margin > target) AND (unique_opponents >= matchable_count - 1)
```

This is O(1) per paper. The alternative — aggregating over the matches collection to count distinct opponents — would be O(matches) and prohibitively expensive at scale.

When enough papers are stalled that no new pairs can be generated, the category displays "Stalled" in the admin UI. The threshold for the UI indicator is time-based: if no new match has been recorded in 10+ minutes while the system is running, it shows "Stalled".

### 3.6 Incremental Ranking Updates

Rankings are updated incrementally — not recomputed from scratch after each match.

When a match completes (`update_rankings_for_match`):
1. Winner's `wins` and `comparisons` are incremented via `$inc`
2. Loser's `losses` and `comparisons` are incremented
3. Both papers' WR scores are recomputed from their new win/comparison counts
4. TrueSkill ratings are updated using the trueskill library
5. Per-model stats are updated
6. `unique_opponents` is incremented for both papers

If the ranking document doesn't exist (race condition: compare loop ran before fetch loop created the ranking), it's created on the fly and the update retried. If the retry fails, the paper is queued for background repair.

This makes each match update O(1) — independent of category size. A full recomputation from all matches is only used as a daily consistency reconciliation (not yet implemented; see Roadmap).

---

## 4. Background Scheduler

The scheduler consists of four independent async tasks launched at server startup. They run in the same FastAPI process but never block each other or HTTP request handling.

### 4.1 Compare Loop

**Purpose**: Run tournament comparison rounds for categories with unmet convergence goals.

**Lifecycle**:
```
Server starts
  → asyncio.create_task(_compare_loop())
    → _compare_loop_inner() runs in a while loop
      → For each cycle:
        1. Load settings, check pause state
        2. Update per-category paper/match counts
        3. For each active category, check if goals are met
        4. Batch unmet categories (parallel_categories at a time)
        5. For each batch: asyncio.gather(run_comparison_round(cat) for cat in batch)
        6. GC between batches
        7. If goals unmet → loop immediately (2s delay between batches)
        8. If all goals met → sleep until wake_event or compare_loop_interval (60s)
```

**Auto-restart with exponential backoff**: If the compare loop crashes, it restarts automatically with increasing delay: 10s → 20s → 40s → 80s → 160s → 300s (max). The crash is logged to `_compare_loop_diag` and visible in the admin scheduler diagnostics endpoint. This prevents a bug in one comparison round from permanently stopping all tournaments.

**Concurrency model**: Within a single comparison round, `parallel_agents` (default 20, hard cap 20) LLM calls run concurrently via `asyncio.Semaphore`. Each call is an async task that:
1. Loads both papers' summaries from DB
2. Calls the LLM via litellm (in a thread pool executor)
3. Parses the response
4. Saves the match to DB
5. Calls `update_rankings_for_match` to incrementally update both papers' scores

**Throughput**: With `parallel_agents=20` and ~10s per LLM call, a single category processes ~100-120 matches per round. With `parallel_categories=10`, multiple categories run their rounds concurrently. Observed throughput: ~50 matches/min sustained across all active categories.

### 4.2 Fetch Loop

**Purpose**: Periodically fetch new papers from source APIs (ArXiv, ChemRxiv), download PDFs, generate summaries, and insert rankings.

**Lifecycle**:
```
Server starts
  → asyncio.create_task(_fetch_loop())
    → 8s initial delay (let compare loop start first)
    → While running:
      1. For each active category, check last_fetch_at vs fetch_interval_hours
      2. If due: run_fetch_cycle(category)
      3. GC between categories
      4. Sleep until next fetch is due (minimum 60s)
```

**`run_fetch_cycle` — 4 independent steps**:

| Step | Action | Failure behavior |
|------|--------|-----------------|
| 1. Fetch | Query ArXiv/ChemRxiv API, dedup, insert new papers | Log error, continue to step 2 |
| 2. PDF Download | Download PDFs for papers missing `full_text` | Log error, continue to step 3 |
| 3. Summary Gen | Generate 3 AI summaries per paper with `full_text` | Log error, continue to step 4 |
| 4. Rankings | Insert ranking entries for papers with summaries | Log error, return partial result |

Each step runs even if a previous one fails. This is critical because ArXiv aggressively rate-limits (429) when multiple categories are fetched in quick succession — without step independence, a 429 on step 1 would prevent PDF downloads and summary generation for existing papers.

**Force mode**: When triggered by the admin button (`force=True`):
- Step 2 retries previously failed PDF downloads (`pdf_failed=True` papers)
- Step 3 bypasses the system pause check for summary generation
- Step 4 inserts rankings for ALL unranked papers with summaries (not just newly fetched ones)

### 4.3 Analysis Cache Loop

**Purpose**: Keep the model-analysis endpoint fast by precomputing the "All Categories" correlation data in the background.

**Lifecycle**:
```
Server starts
  → asyncio.create_task(_bg_refresh_all_categories())
    → 30s initial delay (warm-up)
    → Compute All Categories analysis, store in _live_analysis_cache
    → While running:
      1. Wait for _live_analysis_dirty flag (set by notify_data_changed)
      2. Debounce 10s (batch rapid match completions)
      3. Recompute and cache
```

The `_live_analysis_cache` has a 1-hour TTL safety net, but in practice it's always fresh because `notify_data_changed()` is called after every comparison round and triggers an immediate background refresh.

**Cost**: Computing the All Categories analysis loads all rankings (~5K documents), computes correlations per model pair, per scoring method, and per category. On production with ~5K papers this takes ~6 seconds. Users never see this — they always read from cache (~0.15s).

**Critical bug found April 2026**: The `logger` was not imported in `model_analysis.py`, causing the background task to crash silently on every server startup. The cache was never populated, and every page view triggered a 6.6s cold computation. Fixed by adding `from core.config import logger`.

### 4.4 Archive Loop

**Purpose**: Daily leaderboard snapshots for historical tracking.

Runs once at startup, then daily at 00:05 UTC. Saves current rankings to `leaderboard_archives` and `ranking_snapshots` collections. Lightweight — reads from DB-backed rankings (no computation).

### 4.5 Event System

Background tasks communicate through two mechanisms:

**`notify_data_changed()`**: Called after any data mutation (new matches, new papers, settings change). Sets `_live_analysis_dirty = True` and triggers the leaderboard cache refresh. This is the "event bus" that keeps all caches consistent.

**`wake_scheduler()`**: Signals the compare loop to wake up immediately (instead of waiting for the sleep timer). Used when new papers are added (they need tournament matches) or when the system is unpaused.

**`invalidate_goals_cache(category)`**: Clears the goals-met cache for a category. Called when new papers or matches change the convergence state. Prevents the compare loop from sleeping when there's new work to do.

### 4.6 Task Interaction Diagram

```
                  ┌──────────────┐
                  │  Admin UI    │
                  │  Button Click│
                  └──────┬───────┘
                         │
              ┌──────────▼──────────┐
              │  run_fetch_cycle()  │
              │  (force=True)       │
              └──┬────┬────┬────┬──┘
                 │    │    │    │
    Step 1       │    │    │    │  Step 4
    ArXiv ◄──────┘    │    │    └──────► insert_ranking_for_paper()
                      │    │
         Step 2       │    │  Step 3
         PDFs ◄───────┘    └──────► _generate_paper_summaries(force=True)
                                          │
                                          ▼
                                   LLM calls (Claude/GPT/Gemini)
                                          │
                                          ▼
                                   notify_data_changed()
                                     │           │
                    ┌────────────────┘           └────────────────┐
                    ▼                                             ▼
          _live_analysis_dirty=True                    wake_scheduler()
                    │                                             │
                    ▼                                             ▼
          _bg_refresh_all_categories()              _compare_loop_inner()
          (recomputes model analysis)               (runs new matches)
                                                          │
                                                          ▼
                                                 update_rankings_for_match()
                                                          │
                                                          ▼
                                                 notify_data_changed()
                                                   (cycle continues)
```
