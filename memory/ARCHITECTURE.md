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

---

## 5. Paper Ingestion Pipeline

### 5.1 Overview

Papers enter the system through a 4-step pipeline. Each step is independent — failure at any step doesn't block subsequent steps.

```
ArXiv/ChemRxiv API
       │
       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Step 1: Fetch  │───▶│ Step 2: PDF     │───▶│ Step 3: Summary │───▶│ Step 4: Ranking │
│  New Papers     │    │ Download        │    │ Generation      │    │ Insert          │
│                 │    │                 │    │                 │    │                 │
│ ArXiv API call  │    │ Download PDF    │    │ 3 LLM calls per │    │ Create ranking  │
│ Dedup by        │    │ Extract text    │    │ paper (Claude,  │    │ doc in rankings │
│ arxiv_id +      │    │ via PyMuPDF     │    │ GPT, Gemini)    │    │ collection      │
│ content hash    │    │                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
     May fail:              May fail:              May fail:              May fail:
     429 rate limit         Timeout, 404,          Budget exceeded,       DB error
                            paywall                content filter         (rare)
```

### 5.2 Step 1: Fetch New Papers

**Source routing**: Categories prefixed with `chemrxiv.` use the ChemRxiv API; all others use ArXiv.

**ArXiv pagination**: The API is queried with `sortBy=submittedDate&sortOrder=descending`. For niche categories where primary papers are sparse, it paginates up to 5 pages (batch size = `max_papers_per_fetch × 3`, default 150) to find enough primary-category papers.

**Dedup strategy** (two layers):
1. **Source ID dedup**: Skip if `arxiv_id` already exists in DB
2. **Content hash dedup**: `SHA-256(normalized_title | first_author)[:16]` stored as `dedup_hash` with a unique index. Catches re-submissions and cross-postings with different arxiv_ids but identical title/author.

### 5.3 Step 2: PDF Download & Text Extraction

**Query**: Papers are selected for download when `full_text` is None and either `needs_pdf=True` (new paper) or `pdf_failed` is not True (hasn't permanently failed).

**Force mode**: Admin button clicks retry ALL papers with `full_text=None`, including previously failed ones (`pdf_failed=True`).

**Extraction**: PDFs are downloaded via httpx and extracted using PyMuPDF (fitz) in a thread pool executor (non-blocking). The full extracted text is stored in `papers.full_text`.

**Failure handling**: Failed papers are marked with:
- `pdf_failed: True` — excluded from automatic retry cycles
- `pdf_fail_reason`: classified as `timeout`, `rate_limit`, `not_found`, `connection`, or `extraction_error`
- `pdf_failed_at`: timestamp for diagnostic purposes

Rate between 1-second between downloads to avoid hammering ArXiv.

### 5.4 Step 3: AI Summary Generation

Each paper with `full_text` gets summaries from three models:

| Model | Key in DB | Config |
|-------|-----------|--------|
| Claude Opus 4.6 | `anthropic:claude-opus-4-6:thinking` | Extended thinking enabled (10K budget tokens) |
| GPT-5.2 | `openai:gpt-5_2` | Standard completion |
| Gemini 3 Pro | `gemini:gemini-3-pro-preview` | Standard completion |

**Two-phase scan**:
1. **Lightweight scan**: Load only `{id, summaries}` for all papers — check which model keys are missing
2. **On-demand load**: Only load `full_text` for papers that actually need generation (avoids loading ~100MB of text for papers that are already complete)

**Concurrency**: Controlled by `summary_parallel` (default 10) via `asyncio.Semaphore`.

**Content handling**: The full paper text is sent with no truncation. If the LLM returns a token-limit error, the content is halved and retried (up to 4 attempts). A truncation note is appended to the summary when this happens.

**Rating extraction**: Claude Thinking summaries include a JSON ratings block at the end (`{"score": 7.5, "significance": 8.0, ...}`). This is parsed and stored in `papers.ai_rating` and `papers.ai_ratings_by_model`.

**Force mode**: Bypasses the system pause check, allowing summary generation even when the tournament is paused.

### 5.5 Step 4: Ranking Insert

For every paper that has at least one summary but isn't yet in the `rankings` collection, a new ranking document is created with default scores (score=1200, 0 wins, 0 comparisons).

In force mode (admin button), this runs for ALL categories — not just newly fetched papers. This catches papers that got summaries in a previous run but weren't ranked due to a bug or timing issue.

### 5.6 Summary Fallback Chain

Tournament matchability requires a specific summary key. The default source is Claude Thinking (`anthropic:claude-opus-4-6:thinking`). If unavailable, the system walks a fallback chain:

```
anthropic:claude-opus-4-6:thinking     (preferred — extended thinking)
  → anthropic:claude-opus-4-6          (non-thinking Opus 4.6)
  → anthropic:claude-opus-4-5-20251101 (legacy Opus 4.5)
  → openai:gpt-5_2                    (GPT fallback)
  → gemini:gemini-3-pro-preview       (Gemini fallback)
```

The GPT/Gemini fallbacks were added because Claude's content policy refuses to summarize certain papers (notably AI safety/adversarial research papers like jailbreaking studies). Without fallbacks, these papers would be permanently excluded from tournament rankings despite having valid summaries from other models.

---

## 6. LLM Integration

### 6.1 Emergent Universal Key

All LLM calls route through the Emergent proxy using a single Universal Key (`sk-emergent-...`). This key works with OpenAI, Anthropic, and Google models without needing separate API keys.

```python
from emergentintegrations.llm.utils import get_integration_proxy_url

params = {
    "model": "claude-opus-4-6",           # or "gpt-5.2", "gemini/gemini-3-pro-preview"
    "api_key": EMERGENT_LLM_KEY,
    "api_base": get_integration_proxy_url() + "/llm",
    "custom_llm_provider": "openai",       # Emergent proxy speaks the OpenAI protocol
}
response = litellm.completion(**params)
```

The `litellm` library handles model routing. For Gemini models, the model name is prefixed with `gemini/` when going through the Emergent proxy.

### 6.2 Two Prompt Architectures

The platform uses two distinct LLM interactions:

**1. Tournament Comparison (pairwise judgment)**
- **When**: During `run_comparison_round`, for each match
- **Input**: Two papers' pre-generated summaries (not raw PDFs)
- **Output**: JSON with `winner` and `reasoning`
- **Models**: Round-robin across GPT-5.2, Claude Opus 4.6, Gemini 3 Pro
- **Prompt**: Configurable via admin panel (stored in `settings.custom_prompt`)

```
System: "You are a scientific paper evaluator..."
User: "Compare these two papers for scientific impact:
       Paper 1: {title}\n{summary}
       Paper 2: {title}\n{summary}
       Which paper has higher estimated scientific impact?"
→ Response: {"winner": "paper1", "reasoning": "..."}
```

**2. Impact Assessment (summary generation)**
- **When**: During paper ingestion (Step 3), once per paper per model
- **Input**: Full paper text (abstract + extracted PDF content)
- **Output**: ~1000 word assessment + JSON ratings block
- **Models**: All three, independently (stored under separate keys)
- **Prompt**: Fixed (not admin-configurable)

```
System: "You are a scientific impact analyst..."
User: "Write a scientific impact assessment for:
       Title: {title}
       Content: {abstract + full_text}
       Write your assessment, then provide ratings as JSON..."
→ Response: "This paper introduces... [assessment] ...
             {"score": 7.5, "significance": 8.0, "rigor": 7.0, ...}"
```

### 6.3 Model Selection

**Tournament comparisons**: Models are selected round-robin via a global counter (`_model_counter`). This ensures even distribution — each model judges approximately 1/3 of all matches. The per-model statistics are then used in the Model Correlation analysis to measure inter-model agreement.

**Summary generation**: All three models generate summaries independently for every paper. Only the Claude Thinking summary is used in live tournament comparisons (as it includes extended reasoning). GPT and Gemini summaries are generated for:
- Fallback matchability (when Claude refuses)
- SI (Single-Item) rating correlation analysis
- Inter-model agreement statistics

### 6.4 Error Handling

| Error Type | Detection | Behavior |
|------------|-----------|----------|
| Budget exceeded | Keywords: "budget", "balance", "insufficient", "credit", "quota" | Wait 15s, retry (up to 4 attempts) |
| Token limit | Keywords: "context_length", "maximum.*tokens", "too long" | Halve content, retry with truncated text |
| Rate limit | HTTP 429 or "rate" keyword | Exponential backoff |
| Content filter | Empty response or refusal | Count as failure; fallback chain handles matchability |
| Network error | Connection timeout, DNS failure | Retry with exponential backoff (2^attempt seconds) |

Budget errors are the most common failure mode. The Emergent Universal Key has a spending cap that auto-tops up in small increments. During high-throughput periods (20 concurrent agents), the spending can briefly exceed the cap before auto-top-up kicks in.

### 6.5 Token Tracking

Every LLM call records actual token usage from the response:
```python
tokens = {
    "input": usage.prompt_tokens,
    "output": usage.completion_tokens,
    "thinking": usage.completion_tokens_details.reasoning_tokens,  # Claude only
}
```

For summaries, this is stored per-model in `papers.summary_tokens`. For matches, it's stored on the match document. The admin Statistics page aggregates these for cost monitoring.

### 6.6 Content Truncation

When a paper's full text exceeds a model's context window, the system:
1. Catches the token-limit error
2. Halves `char_limit` (minimum 20,000 chars)
3. Rebuilds the content: `Abstract: {abstract}\n\nFull Paper Text:\n{full_text[:char_limit]}`
4. Retries (up to 4 attempts)
5. Appends a note to the generated summary:
   `[Note: This summary was generated from 47% of the paper (85,000 of 180,000 characters) due to anthropic/claude-opus-4-6 context window limits.]`



---

## 7. Caching & Performance

### 7.1 Cache Inventory

The system maintains several in-memory caches. All are event-driven (refreshed when data changes) rather than timer-driven (refreshed on a schedule).

| Cache | Location | Size | TTL | Trigger | Purpose |
|-------|----------|------|-----|---------|---------|
| **Leaderboard metadata** | `leaderboard.py:_cache` | ~5 MB | Event-driven | `notify_data_changed()` | Admin stats, tags, PDF counts, rating stats |
| **Model analysis** | `model_analysis.py:_live_analysis_cache` | ~160 KB per entry | 1h safety net | `mark_live_analysis_dirty()` | Correlation tables, agreement stats |
| **Tag queries** | `leaderboard.py:_tag_cache` | Max 100 entries | 20s | Cleared on cache refresh | Filtered leaderboard by tag combo |
| **Goals-met** | `scheduler.py:_goals_met_cache` | ~1 KB per cat | 60s | `invalidate_goals_cache()` | Avoid repeated DB queries in compare loop |
| **Match counts** | `leaderboard.py:_match_count_cache` | ~1 KB | 5 min | `invalidate_match_count_cache()` | Total match count for status endpoint |
| **Convergence** | MongoDB `convergence_cache` | ~50 KB per cat | Persistent | After comparison rounds | Convergence curve charts |
| **OpenSkill** | MongoDB `analysis_store` | ~200 KB per cat | Persistent | Admin refresh button | OpenSkill correlation columns |

**Total in-memory cache footprint: ~20 MB** (down from ~750 MB before the DB-backed rankings migration).

### 7.2 Event-Driven Cache Architecture

Caches are never refreshed on a timer or on every request. Instead, they respond to a single event signal:

```
Match completes
  → update_rankings_for_match()     (incremental DB update)
  → notify_data_changed()           (sets dirty flags)
    → _cache_dirty.set()            (leaderboard metadata cache)
    → mark_live_analysis_dirty()    (model analysis cache)
    → invalidate_goals_cache()      (goals check)
    → invalidate_match_count_cache() (match counts)
```

Each cache has a debounce period (10-30s) to batch rapid match completions. During a tournament round with 100 matches completing in ~60s, the caches refresh once or twice — not 100 times.

### 7.3 Leaderboard Serving

The leaderboard is served directly from the `rankings` MongoDB collection via indexed queries — not from an in-memory cache. This is the "Option 3: DB-Backed Leaderboard" from the scaling roadmap.

```python
# Primary query: category leaderboard with pagination
db.rankings.find({"category": "cs.CR"})
    .sort("rank", 1)
    .skip(offset)
    .limit(50)
```

**Performance**: ~5-10ms per query (indexed). The `category_1_rank_1` compound index makes this essentially a B-tree range scan.

**Search**: Title search uses a regex on the `title` field within the category. For the current scale (~2K papers per category), this is fast enough. At 100K+ papers, a text index or full-text search engine would be needed.

### 7.4 Memory Budget

| Component | Memory | Notes |
|-----------|--------|-------|
| Python process baseline | ~150 MB | FastAPI + imported libraries |
| MongoDB driver pool | ~50 MB | Connection pool, cursors |
| Leaderboard metadata cache | ~5 MB | Tags, stats, PDF counts |
| Model analysis cache | ~10 MB | All-categories + per-category entries |
| LLM executor thread pool | ~20 MB | `ThreadPoolExecutor` for litellm calls |
| Active comparison data | ~50 MB | Paper summaries loaded during matches |
| **Typical RSS** | **~450 MB** | In a 2 GB container with ~1.2 GB available |

Peak memory occurs during `_refresh_cache()` when old and new caches briefly coexist. With the current metadata-only cache, this peak is negligible (~10 MB).

---

## 8. API Reference

### 8.1 Public Endpoints

These require no authentication and are used by the frontend.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/leaderboard` | Paginated leaderboard. Params: `category`, `period` (all/week/month/recent), `limit`, `offset`, `search`, `sort_by`, `tags` |
| `GET` | `/api/papers/{paper_id}` | Paper detail with match history |
| `GET` | `/api/categories` | Active categories list |
| `GET` | `/api/tags` | All category tags with paper counts |
| `GET` | `/api/model-analysis` | Model correlation data (WR, TS, OS, agreement, scatter). Param: `category` |
| `GET` | `/api/convergence` | Convergence curve data. Param: `category` |
| `GET` | `/api/status` | Public system status (paper/match counts) |
| `GET` | `/api/prompts` | Current evaluation prompt (read-only) |
| `GET` | `/api/archive/list` | Available weekly/monthly archive snapshots |
| `GET` | `/api/archive/{category}/{year}/w{week}` | Weekly archive snapshot |
| `GET` | `/api/sitemap.xml` | SEO sitemap |

### 8.2 Admin Endpoints

All require `X-Admin-Token` header (obtained via `/api/admin/login`).

**Paper Ingestion:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/fetch` | Trigger 4-step fetch pipeline for a category |
| `GET` | `/api/admin/fetch-status/{category}` | Poll fetch task status (running/completed/failed) |
| `GET` | `/api/admin/check-new-papers` | Check ArXiv for new papers without downloading |
| `POST` | `/api/admin/backfill-summaries` | Generate missing summaries (force mode) |
| `GET` | `/api/admin/summary-gen-progress` | Real-time summary generation progress |

**Tournament Control:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/compare` | Trigger manual comparison round |
| `POST` | `/api/admin/toggle-pause` | Pause/unpause entire system |
| `GET` | `/api/admin/progress` | Detailed tournament progress with convergence goals |
| `GET` | `/api/admin/scheduler-diagnostics` | Compare loop health, last cycle results |
| `GET` | `/api/admin/diagnose-pairs` | Per-paper stall diagnosis |
| `GET` | `/api/admin/unranked-papers` | Papers not on leaderboard with diagnostic details |

**Configuration:**

| Method | Path | Description |
|--------|------|-------------|
| `GET/PUT` | `/api/admin/settings` | All admin settings |
| `GET/PUT` | `/api/admin/prompt` | Tournament evaluation prompt |
| `POST` | `/api/admin/categories/add` | Add new category |
| `POST` | `/api/admin/categories/remove` | Remove category |
| `POST` | `/api/admin/categories/reorder` | Drag-and-drop category ordering |
| `GET` | `/api/admin/tournaments` | Per-category tournament state |
| `POST` | `/api/admin/tournaments/{id}/toggle-fetch` | Pause/resume fetching per category |
| `POST` | `/api/admin/tournaments/{id}/toggle-compare` | Pause/resume comparisons per category |

**Monitoring:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/status` | Full admin dashboard data |
| `GET` | `/api/admin/stats` | Cost, token usage, per-model breakdowns |
| `GET` | `/api/admin/timeseries` | System logs for memory/event charts |
| `GET` | `/api/admin/extraction-stats` | PDF extraction success rates |
| `POST` | `/api/admin/refresh-openskill` | Trigger OpenSkill recomputation |
| `POST` | `/api/admin/reconcile-rankings` | Full ranking recomputation from matches |
| `POST` | `/api/admin/rerank-all` | Recompute ranks for a category |

### 8.3 Authentication

**Admin auth**: Password-based. `POST /api/admin/login` with `{"password": "..."}` returns a token. Token is sent as `X-Admin-Token` header. Tokens are stored in `admin_sessions` collection.

**User auth**: Google OAuth via Emergent-managed integration. Users can bookmark papers, create reading lists, and submit suggestions. User features are secondary to the core tournament/ranking functionality.

---

## 9. Frontend Architecture

### 9.1 Build & Serving

The frontend is a React 18 application compiled to a production bundle (`yarn build`). The compiled bundle is served by FastAPI as static files — there is no separate frontend server in production.

**Critical implication**: Hot reload works during development but does **NOT** rebuild the production bundle. After modifying any frontend file, you must run:
```bash
cd /app/frontend && yarn build && sudo supervisorctl restart frontend
```

### 9.2 Key Pages

| Page | Route | Purpose |
|------|-------|---------|
| **Leaderboard** | `/` | Main page. Ranked papers by category with search/filter/sort |
| **Paper Detail** | `/paper/{id}` | Paper info, match history, win/loss record |
| **Model Correlation** | `/correlation` | Inter-model agreement, scoring method comparisons |
| **Validation** | `/validation` | Human vs AI benchmark experiments |
| **Methodology** | `/methodology` | Public documentation of ranking methodology |
| **Admin Panel** | `/admin` | Password-protected dashboard (6 tabs) |
| **Archive** | `/archive/{category}` | Historical leaderboard snapshots |

### 9.3 Admin Panel Tabs

| Tab | Component | Purpose |
|-----|-----------|---------|
| **Statistics** | `AdminStatistics.jsx` | Cost charts, token usage, memory monitoring, per-model breakdowns |
| **Tournaments** | `AdminOverview.jsx` | Per-category paper ingestion, tournament progress, convergence goals |
| **Settings** | (inline in AdminPage) | Global settings: parallel agents, CI targets, fetch intervals |
| **Prompt** | (inline in AdminPage) | Edit tournament evaluation prompt |
| **Experiment** | `AdminExperiment.jsx` | Validation experiment management |
| **Suggestions** | (inline in AdminPage) | User-submitted feature suggestions |
| **Users** | (inline in AdminPage) | Registered user management |

### 9.4 Key Components

**Correlation page sections** (each is a standalone component receiving data from the unified `/api/model-analysis` endpoint):
- `CorrelationSection` — Inter-model WR/TS correlation tables (Aggregate + Average modes)
- `ScoringMethodSection` — WR vs TrueSkill vs OpenSkill comparison
- `PwVsSiSection` — Pairwise ranking vs Single-Item rating correlation
- `InterModelSection` — Per-model-pair correlation details
- `SiRatingSection` — Single-Item rating distribution analysis
- `ConvergenceSection` — Ranking stability curves

**Leaderboard components** (in `components/leaderboard/`):
- Paper cards with score, rank, confidence indicators
- Period filters (all-time, week, month, recent)
- Tag-based filtering
- Search with real-time results

### 9.5 Styling

- **Tailwind CSS** with a custom theme
- **Shadcn/UI** component library (buttons, cards, switches, dropdowns, etc.)
- Dark/light mode toggle
- Responsive design (mobile-optimized admin panel)
- `sonner` for toast notifications

---

## 10. Deployment & Operations

### 10.1 Production Environment

| Component | Configuration |
|-----------|--------------|
| Container | Kubernetes pod, 2 GB RAM limit (~1.2 GB available for Python after OS/MongoDB/nginx) |
| Process manager | Supervisor (manages backend + frontend + MongoDB + nginx) |
| Backend | FastAPI on `0.0.0.0:8001`, proxied by nginx |
| Frontend | Compiled React bundle served on port 3000 |
| Routing | Kubernetes ingress: `/api/*` → port 8001, all other routes → port 3000 |
| CDN | Cloudflare (DNS, caching, bot protection) |

### 10.2 Startup Sequence

The server prioritizes fast readiness over completeness:

```
T+0.0s   FastAPI starts, essential indexes created
T+0.1s   Precomputed JSON caches loaded (experiments)
T+0.1s   Health endpoint available — start accepting traffic
T+0.1s   _deferred_startup() begins in background:
           → Create remaining indexes
           → Run migrations & backfills
           → Seed rankings for new papers
T+2.0s   Leaderboard metadata cache warmed
T+5.0s   Compare loop starts
T+8.0s   Fetch loop starts
T+30s    Model analysis cache warmed (background)
T+120s   Summary bias cache pre-warmed
```

All heavy work (index creation, backfills, cache warming) runs in `_deferred_startup()` as a background task. The health endpoint responds immediately so Kubernetes doesn't kill the pod during a slow warm-up.

### 10.3 Deploy Behavior

The deploy platform writes files to disk sequentially (not atomically). With `--reload` enabled (development), each file write triggers a uvicorn restart. Deploying 15+ modified files causes 2-3 restart cycles before the final stable process starts.

**Mitigation**: On first startup, the server patches the supervisor config to remove `--reload`, then exits. Supervisor restarts it without `--reload`, eliminating the restart storm. This is critical for the 2 GB container — during a reload cycle, the old and new processes briefly coexist, doubling RSS and triggering OOM kills.

### 10.4 MongoDB Configuration

**WiredTiger cache**: The default WiredTiger cache is 50% of system RAM (~3.5 GB). This leaves no room for Python. At startup, the server caps it to 384 MB:
```python
await admin_db.command({"setParameter": 1, "wiredTigerEngineRuntimeConfig": "cache_size=384M"})
```

**TTL index**: `system_logs` has a 7-day TTL index on the `ts` field. MongoDB automatically purges old logs.

### 10.5 Monitoring

**Memory**: RSS is logged every 5 minutes (`_bg_memory_heartbeat`) and at key events (cache refresh, comparison round, fetch cycle). Stored in `system_logs` with color-coded thresholds in the admin chart:
- Green: < 1 GB (safe)
- Amber: 1-1.5 GB (warning)
- Red: > 1.5 GB (danger, approaching 2 GB limit)

**Scheduler health**: `/api/admin/scheduler-diagnostics` exposes:
- `loop_alive`: Boolean — is the compare loop running?
- `last_cycle_at`: Timestamp of last cycle
- `last_cycle_results`: Per-category match results from the last round
- `cycles_since_restart`: Counter (resets to 0 on crash/restart)
- Crash info (error, traceback, restart count) if applicable

**Admin dashboard**: The Statistics tab shows cumulative cost, token usage, per-model breakdowns, memory chart with restart markers, and paper/match growth curves.

---

## 11. Known Limitations & Technical Debt

### 11.1 Monolithic Files

| File | Lines | Concern |
|------|-------|---------|
| `routers/admin.py` | 3,336 | The largest file. Mixes tournament control, paper ingestion, statistics, prompt management, category CRUD, and diagnostics |
| `routers/leaderboard.py` | 1,635 | Public API + cache management + convergence computation + archive logic |
| `services/scheduler.py` | 1,620 | Compare loop + fetch loop + summary generation + matchmaking |
| `services/ranking.py` | 1,428 | WR scoring + TrueSkill + rankings CRUD + repair queue |
| `services/model_analysis.py` | 1,316 | Correlation computation + cache management |
| `server.py` | 1,286 | Startup + migrations + index creation + backfills |

**Recommended split** (not yet implemented):
- `admin.py` → `admin_tournaments.py`, `admin_settings.py`, `admin_diagnostics.py`, `admin_categories.py`
- `scheduler.py` → `compare_loop.py`, `fetch_loop.py`, `summary_gen.py`, `matchmaking.py`

### 11.2 Circular Import Chain

```
core/auth.py  →  routers/admin.py  →  services/scheduler.py
     ↑                                       │
     └───────────────────────────────────────┘
```

`core/auth.py` imports from `routers/admin.py` (for `_invalidate_admin_cache`), and `routers/admin.py` imports from `core/auth.py` (for `verify_admin`, `get_settings`). This works at runtime because the imports are deferred (inside function bodies), but it's fragile and makes refactoring difficult.

**Fix**: Extract shared utilities (`get_settings`, `invalidate_settings_cache`) into a standalone module with no router/service dependencies.

### 11.3 Claude Content Policy Gaps

Claude Opus refuses to generate impact summaries for papers about adversarial AI (jailbreaking, safety evaluation, bypassing classifiers). These papers get GPT and Gemini summaries but no Claude Thinking summary.

**Current mitigation**: Summary fallback chain allows GPT/Gemini summaries for tournament matchability. The papers participate in tournaments but with a different model's summary than the default.

**Impact**: Minimal. ~2 out of 823 papers in cs.CR affected. The fallback summaries are high quality.

### 11.4 Twitter/X Mobile Unfurling

Open Graph meta tags are served correctly for desktop browsers, but Twitter/X mobile app shows a blank preview card. Root cause: Cloudflare's bot protection blocks Twitter's mobile user-agent crawler. Desktop Twitter works because it uses a different crawler.

**Status**: Blocked on Cloudflare configuration. Investigated in multiple sessions with no resolution. The Cloudflare "bot fight mode" or "super bot fight mode" setting needs exceptions for Twitter's crawlers.

### 11.5 Single-Process Architecture

The entire system (web server + background scheduler + analysis computation) runs in a single FastAPI process. This means:
- A CPU-intensive computation (e.g., OpenSkill replay) blocks the event loop for all HTTP requests
- Memory is shared — a spike in one component affects all others
- No horizontal scaling — can't add more workers

**Planned fix**: Architecture split via `KURATE_ROLE` environment variable (documented in `/app/memory/ARCHITECTURE_DECOMPOSITION.md`):
- `KURATE_ROLE=web`: Only run FastAPI routes, no background tasks
- `KURATE_ROLE=worker`: Only run scheduler loops, no HTTP serving

---

## 12. Scaling Roadmap

### 12.1 Current Limits

| Metric | Current | Limit | Bottleneck |
|--------|---------|-------|-----------|
| Papers | ~5,100 | ~50,000 | RSS memory (~8.6 KB per paper in metadata cache) |
| Matches | ~150,000 | ~500,000 | Match count aggregations slow above 500K |
| Categories | 14 | ~30 | Each category adds ~50 MB during comparison rounds |
| Concurrent agents | 20 | 20 (hard cap) | LLM proxy rate limits; raise cap to test |
| Match throughput | ~50/min | ~100/min | `parallel_agents` cap; LLM latency floor ~8s |

### 12.2 Near-Term (10K-50K papers)

**Already done:**
- DB-backed rankings (O(1) memory for leaderboard serving)
- Event-driven cache refresh (no periodic full recomputation)
- Materialized `unique_opponents` (O(1) stall detection)
- Gap-fill ranking seed (no match loading at startup)

**Remaining:**
- Per-category streaming in `_refresh_cache()` (reduce peak memory during metadata refresh)
- Text index on `rankings.title` for fast search at scale
- Increase `parallel_agents` cap after testing LLM proxy limits

### 12.3 Long-Term (50K+ papers)

- **Architecture split**: Separate web and worker processes (KURATE_ROLE)
- **TrueSkill-first matchmaking**: Use uncertainty (σ) to select maximally informative pairs, reducing total matches needed by ~35%
- **Incremental OpenSkill**: Currently requires full match replay; implement online updates
- **Match archiving**: Move old matches to a cold collection after ranking stabilizes

### 12.4 Infrastructure

- Current: Single 2 GB Kubernetes pod, local MongoDB
- Scale to 4 GB: Doubles headroom for metadata caches, enables 100K papers
- Scale to dedicated MongoDB: Atlas free tier → dedicated cluster for index and query performance
- Scale to multi-pod: Requires KURATE_ROLE split + shared MongoDB

---

## 13. Lessons Learned

Operational lessons from production incidents and debugging sessions. Each entry includes the root cause, how it was detected, and the fix — for future reference.

### 13.1 Silent Background Task Crashes

**Incident**: The model analysis cache was never populated after server restart. Every page view to `/correlation` took 6.6 seconds instead of 0.15 seconds.

**Root cause**: `logger` was not imported in `model_analysis.py`. The background warm-up task crashed with `NameError: name 'logger' is not defined`. Since it was an `asyncio.create_task`, the exception was silently discarded — no log line, no error, no alert.

**Detection**: User reported >5s correlation page load. Investigation found `compute_time_s: 6.6` in the API response, indicating a cold computation rather than a cache hit.

**Fix**: Added `from core.config import logger` to `model_analysis.py`.

**Lesson**: Always log at the start of background tasks ("Task X started") so silent crashes are detectable by the absence of the log line. Periodically check `asyncio.Task` results for unhandled exceptions.

### 13.2 Ghost Matches

**Incident**: 278 matches in cs.SI had rankings that never updated. Papers showed 0 wins/0 losses despite having completed matches in the DB.

**Root cause**: `update_rankings_for_match` used `find_one_and_update` without `upsert`. When the compare loop matched a paper before the fetch loop created its ranking entry (race condition), the `$inc` silently did nothing — match saved to DB, rankings never updated.

**Fix**: If `find_one_and_update` returns `None`, create the ranking entry on the fly, then retry the increment. If retry fails, queue for background repair.

**Lesson**: In MongoDB, `$inc` on a non-existent document is a silent no-op. Always check the return value and handle `None`.

### 13.3 Stale Frontend Builds

**Incident**: Frontend code changes appeared correct in source files but the browser showed old behavior. Multiple debugging cycles were wasted on non-existent React state bugs.

**Root cause**: The React app serves a compiled production bundle, not live source files. Hot reload works in development but does NOT rebuild the bundle. The testing agent was screenshotting the old compiled bundle.

**Fix**: After ANY frontend file modification, run `cd /app/frontend && yarn build && sudo supervisorctl restart frontend`.

**Lesson**: Always browser-test UI changes AFTER rebuilding the bundle.

### 13.4 Summary Generation Silently Skipped

**Incident**: Admin clicked "Generate missing summaries" while system was paused. Progress showed 0 generated, all skipped. No error message.

**Root cause**: The `gen_one` inner function checked `settings.paused` but ignored the `force=True` parameter from the admin button. All papers were silently skipped.

**Fix**: `gen_one` now checks `if not force:` before consulting the pause state.

**Lesson**: Admin manual actions (`force=True`) must bypass operational guardrails (pause state, failure blacklists). The admin explicitly chose to override — respect that.

### 13.5 PDF Downloads Permanently Blacklisted

**Incident**: 22 papers in cs.CR showed as "not downloaded" forever. Clicking the fetch button never retried them.

**Root cause**: The PDF download query excluded papers with `pdf_failed=True`. Once a paper failed (e.g., temporary ArXiv rate limit), it was permanently blacklisted from automatic and manual retries.

**Fix**: In force mode (admin button), the query includes all papers with `full_text=None` regardless of `pdf_failed` status. Automatic scheduler cycles still skip failed papers.

**Lesson**: Distinguish between "automatic retry" (skip known failures to avoid wasting time) and "manual retry" (user explicitly wants to try again). Same principle as 13.4.

### 13.6 ArXiv 429 Killing Entire Pipeline

**Incident**: "Fetch & generate summaries" button showed "completed: 0 new papers" when ArXiv was rate-limited. No PDFs downloaded, no summaries generated — even though there were papers needing both.

**Root cause**: The entire `run_fetch_cycle` was a single try/except. ArXiv 429 at step 1 caused the function to throw, skipping steps 2-4.

**Fix**: Restructured into 4 independent try/except blocks. Each step runs even if a previous one fails. Status reports "partial" when some steps succeed and others fail.

**Lesson**: Multi-step pipelines should be resilient to individual step failures, especially when steps are independent (downloading PDFs doesn't require fetching new papers first).

### 13.7 Cache Mutation on Read

**Incident**: Duplicate OpenSkill rows appeared in the correlation tables. The same data showed 2x or 3x depending on how many times the page was loaded.

**Root cause**: The cache stored a dict reference. On each read, OpenSkill data was merged into the same dict, adding rows each time. The cached result was mutated in place.

**Fix**: Moved the OpenSkill merge step into `compute_live_analysis` BEFORE caching. The cached result is complete and immutable — no post-cache mutation on read.

**Lesson**: Never mutate cached data after retrieval. Either return a deep copy, or merge everything before caching so the stored result is immutable.

### 13.8 Summary Count Display Mismatch

**Incident**: Admin panel showed "799/801 summarized" with a "Generate 2 missing summaries" button that never worked. The 2 "missing" summaries didn't actually exist.

**Root cause**: `summary_coverage.with_summaries` was set to `total_papers` (leaderboard/matchable count = 799) instead of the actual DB count of papers with summaries (801). The "2 missing" were papers that were ranked but not matchable — not papers missing summaries.

**Fix**: Query `db.papers.count_documents({"summaries": {"$exists": True, "$ne": {}}})` for the actual count.

**Lesson**: Display metrics must come from their actual data source, not from a proxy value that happens to be close. "Ranked papers" ≠ "papers with summaries" — they diverge when matchability filters apply.
