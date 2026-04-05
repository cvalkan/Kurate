# Kurate.org Architecture Decomposition Analysis
*Date: April 5, 2026*

## Goal
Make tournament, validation, and stats logic updatable without causing downtime for the main user-facing leaderboard.

## Current State: Coupling Map

| Component | Reads From | Writes To | In-Process Signals |
|---|---|---|---|
| **Scheduler** (fetch + compare loops) | `settings`, `papers`, `matches`, `rankings`, `tournaments` | `papers`, `matches`, `rankings`, `tournaments` | `notify_data_changed()` → leaderboard cache, `_invalidate_admin_cache()` |
| **Leaderboard** (user-facing reads) | `rankings`, `papers`, `matches`, `settings` | Nothing (read-only) | Receives `notify_data_changed()` |
| **Admin** (dashboard + controls) | `matches`, `papers`, `rankings`, `tournaments`, `settings`, `analysis_store` | `settings`, `analysis_store` | Receives cache invalidations |
| **Model Analysis** | `rankings`, `matches`, `analysis_store` | `analysis_store` | — |
| **Validation/Benchmarks** | `validation_*` collections | `validation_*` collections | Independent |

**Critical coupling point**: `notify_data_changed()` is an in-memory `asyncio.Event`. The scheduler sets it to tell the leaderboard "refresh your cache." This only works within a single process.

## The Real Problem
Updating tournament/admin logic shouldn't risk a blip for leaderboard users. Currently, any deploy restarts the entire process (scheduler + leaderboard + admin), causing:
1. ~5-10s downtime on the user-facing leaderboard
2. Scheduler interruption (loses in-flight LLM comparisons)
3. Risk that a bug in new tournament code takes down the leaderboard

---

## Option A: Role-Based Startup (Recommended First Step)

**Concept**: Same codebase, different startup behavior based on an env var.

```
KURATE_ROLE=all      → Current behavior (everything)
KURATE_ROLE=web      → Only leaderboard + public routes (no scheduler, no heavy admin compute)
KURATE_ROLE=worker   → Only scheduler loops (no HTTP server, or minimal health endpoint)
```

**How to use it**:
- On **Emergent** (production): Set `ROLE=web`. Users always get a fast, stable leaderboard. Deploys never disrupt it.
- On a **$5 VPS**: Run the same code with `ROLE=worker`. Connects to same MongoDB, crunches matches in background. Restart/update anytime — users don't notice.
- For **local dev / preview**: Keep `ROLE=all` (default). Everything works together.

**Required code change**: Replace `notify_data_changed()` (in-memory signal) with a DB-based signal. Scheduler bumps a version number in MongoDB; leaderboard checks it every few seconds. ~50 lines.

**Effort**: ~1-2 days
**Pros**: Minimal refactoring. Same codebase. Easy to test. Gradual migration path.
**Cons**: Still a monolith — a Python import error in scheduler code could theoretically prevent web role from starting (mitigated by lazy imports).

---

## Option B: Separate Apps via Shared MongoDB (Clean Split)

**Concept**: 3 independent FastAPI applications sharing one MongoDB (Atlas).

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  kurate-web  │   │kurate-worker │   │ kurate-admin │
│  (Emergent)  │   │    (VPS)     │   │(Emergent/VPS)│
│              │   │              │   │              │
│ Leaderboard  │   │  Scheduler   │   │  Admin UI    │
│ Paper pages  │   │  Fetch loop  │   │  Model Anal. │
│ Badges       │   │  Compare     │   │  OS Refresh  │
│ Bookmarks    │   │  Ranking     │   │  Validation  │
│ Auth         │   │  LLM calls   │   │  Experiments │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────┬───────┴───────────────────┘
                  │
           ┌──────┴──────┐
           │  MongoDB    │
           │  (Atlas)    │
           └─────────────┘
```

**Critical prerequisite**: Production MongoDB must be remotely accessible (Atlas or VPS-hosted). Current `mongodb://localhost:27017` only works in single-container setup.

**Inter-service communication**:
- No HTTP calls between services — all read/write the same DB
- Cache invalidation: Worker writes a version bump to `signals` collection. Web polls every 5-10s.
- Admin commands: Write command docs to `tournament_commands` collection. Worker polls.

**Effort**: ~3-5 days for split + 1 day for DevOps
**Pros**: True isolation. Worker crash can't affect leaderboard. Independent deploy cycles.
**Cons**: 3 codebases (or mono-repo with 3 entry points). More DevOps. Needs MongoDB Atlas.

---

## Option C: Emergent + Cron Worker (Lightest VPS Footprint)

**Concept**: Keep everything on Emergent except the background scheduler, which runs on a cheap VPS as a standalone Python script (~500 lines).

**Pros**: Cheapest VPS ($5-10/mo). Minimal code duplication.
**Cons**: Need to duplicate ranking logic and LLM integration code. Two places to update comparison prompts.

---

## Recommendation

**Start with Option A**, then graduate to Option B if needed.

Option A is 90% of the benefit for 10% of the effort. The main risk (deploy takes down leaderboard) is solved by the web role skipping the scheduler. If you don't change comparison logic, you don't need to deploy the VPS at all.

## What Doesn't Make Sense
- Full microservices with REST APIs between services (overkill — services don't need to talk to each other)
- Message queue (Redis/RabbitMQ/SQS) — MongoDB polling achieves the same thing
- Kubernetes multi-service — too heavy for this team size
