# PRD — Kurate.org AI Paper Ranking Platform

## Problem Statement
Build and maintain a sophisticated AI paper-judging system that uses multiple LLM judges to rank academic papers through pairwise tournaments, with validation experiments, convergence monitoring, and multi-category support.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async) + Background scheduler
- **Frontend**: React + Shadcn UI + Recharts
- **LLMs**: Claude Opus 4.6 (Emergent key), GPT-5.5 (direct OpenAI key), Gemini 3.1 Pro (Emergent key)
- **Scoring**: TrueSkill with sigma-based convergence + quality-based matchmaking
- **Dual-Pod**: Leader election via MongoDB lock; follower runs lightweight startup

## What's Been Implemented

### Core System
- 21 active categories (arXiv + ChemRxiv + IACR ePrint) with automated fetch/summarize/match pipeline
- TrueSkill-based ranking with sigma convergence goals (general σ≤2.5, top-K σ≤2.0)
- Quality-based opponent selection using `trueskill.quality_1vs1()`
- Undefeated urgency: 100%/0% WR papers stay needy until they lose or hit match floor
- Match floor: papers with ≥50 comparisons considered converged regardless of sigma
- Round-robin judge rotation (Claude, GPT, Gemini)
- Weekly archive snapshots with medal awards
- Dual-pod leader election with follower memory optimization

### Convergence System (NEW - May 16, 2026)
- Convergence uses raw TrueSkill sigma (not Wilson CI)
- Admin settings: sigma_target_general (σ≤2.5), sigma_target_topk (σ≤2.0), min_comparisons_converged (50)
- Leaderboard 95% CI column displays ±Elo points (sigma × 20)
- Admin progress shows ±Elo labels for goals
- Pair exhaustion check fixed (caps unique_opponents at matchable count)

### Quality Matchmaking (NEW - May 16, 2026)
- Opponent selection uses `trueskill.quality_1vs1()` instead of closest-score distance
- Accounts for BOTH skill difference AND uncertainty — new papers face stronger opponents
- Undefeated papers (100%/0% WR) get mild urgency (0.1) until they lose or hit floor
- Calibration ratio preserved — quality operates within established/needy pool selection
- Simulation-validated: 25% fewer matches, breaks 100% WR naturally

### Dual-Pod Optimization (May 14, 2026)
- Follower skips leader-only startup tasks (retry summaries, dedup, backfill, archive)
- Follower runs periodic GC every 5 minutes
- Follower metadata cache refreshes every 5min (was event-driven only)
- Promoted follower starts archive loop
- SIGTERM shutdown logs include pod_role, markers bolder on chart

### Bug Fixes (May 16, 2026)
- `insert_ranking_for_paper`: removed summary check (callers pre-filter via matchability)
- `update_rankings_for_match`: added `is_latest_version` to paper lookup projection
- Rounding consistency: paper page uses `ci_elo` from API, not local recomputation

## Known Issues
- Orphan rankings: 420 on preview (ghost entries, cosmetic only — don't affect convergence)
- Production: ~10 duplicate titles (minor)
- ChemRxiv papers: MOCKED from static JSON seed file
- Twitter/X mobile unfurling: BLOCKED (awaiting Cloudflare WAF skip rule)

## Pending Tasks
- P0: Multiple Reviewer Personas (ReviewerToo)
- P1: Live ChemRxiv Fetcher
- P1: SSR for Bots/SEO
- P1: Sub-topic Matchmaking
- P1: sitemap.xml
- P1: Author Verification (ORCID OAuth)

## Key Documents
- `/app/memory/TRUESKILL_CONVERGENCE_PLAN.md` — sigma convergence analysis and thresholds
- `/app/memory/ORPHAN_RANKINGS_PLAN.md` — root cause analysis and cleanup plan
- `/app/tools/sim_quality.py` — matchmaking simulation comparing strategies
