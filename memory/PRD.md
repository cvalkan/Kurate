# PaperSumo by Kurate.org — Scientific Preprint Ranking System

## Problem Statement
Build a robust system for ranking and validating AI model performance on scientific preprints. Features a leaderboard tournament where different LLMs act as judges to rank papers, with validation against human peer-review ground truth.

## Architecture
- **Frontend**: React + Shadcn UI (production build served via `npx serve`)
- **Backend**: FastAPI + MongoDB
- **LLMs**: GPT-5.2, Claude Opus 4.6, Gemini 3 Pro (via Emergent LLM key)
- **Domain**: kurate.org
- **Preview**: llm-ranker.preview.emergentagent.com

## Optimal Configuration (as of Mar 2 2026)
- **Summarizer**: Opus 4.6 Thinking (used in live tournaments; GPT/Gemini summaries generated for analysis only)
- **Judges**: Round-robin across GPT-5.2, Opus 4.6, Gemini 3 Pro
- **Input format**: Abstract + AI impact assessment summary
- **Summary source**: "claude" (only Claude Thinking summaries used in live tournaments)

## Current State (Mar 14 2026)
- 2174 papers, 64731 matches, 10 active categories
- 25 validation datasets, validation experiments publicly accessible
- All validation experiments publicly accessible
- Leaderboard shows Rating and Gap columns (togglable via admin)
- Security headers fully implemented
- Archive system fully operational on production
- Socially shareable badges for top-ranked papers (SVG → PNG via CairoSVG)
- Decoupled ORCID verification: users link ORCID on Profile page, admin approves under Users tab
- Badge sharing is public for all users (not restricted to verified authors)
- Claims tab removed from admin panel (deprecated in favor of user-level ORCID verification)
- Profile page shows ORCID admin review status (pending/verified)
- Bookmarks & Reading Lists fully operational
- Share pages are 100% pure static HTML (no JS/redirects) for maximum crawler compatibility
- Congrats (social sharing) open to all visitors; email congrats requires sign-in
- Human vs AI Benchmark: pairwise concordance-based inter-rater reliability, Thurstonian ceiling, BT correlation (committee + individual), tie transparency, Cohen's kappa, difficulty stratification across 9 controlled datasets

## Deployment Readiness (Mar 9 2026)

### Verified
- Frontend rebuilt with correct REACT_APP_BACKEND_URL (llm-ranker)
- All backend test files updated with correct URLs
- All API endpoints tested and returning 200
- Security headers present (HSTS, CSP, X-Frame-Options, etc.)
- MongoDB indexes all created (papers, matches, validation_*, settings)
- Precomputed experiment caches loading on startup (172 caches)
- Admin login working with correct password
- All frontend pages rendering correctly
- Leaderboard Rating/Gap columns visible and sortable
- Validation Hub showing all sections (Pairwise, Single-Item, Tournament, Experiments)

### Performance
- Health: ~200ms, Categories: ~130ms, Leaderboard: ~200ms
- Validation endpoints: 110-280ms (cached)
- Background cache refresh: ~1s every 60s
- Analysis cache refresh: every 5 minutes
- Connection pool: 50 max, 10 min

## IMPORTANT: Frontend Build Process
Frontend is served as a pre-built static site. Any changes to .jsx files require:
1. `cd /app/frontend && yarn build`
2. `sudo supervisorctl restart frontend`
Hot-reloading is NOT sufficient.

## Pending Tasks
- (P0) Phase 3: Notification System via Resend integration
- (P1) Synthetic Unfurl Test Suite for social media card rendering
- (P2) Consolidate fragile MIDL experiment pipeline into single robust background task
- (P2) Explore adding new validation datasets from OpenReview (ICLR 2024 CV)
- (P2) Add missing HTTP security headers
- (P2) Improve summary generation failure tracking UI
- (P2) Continue refactoring monolithic leaderboard.py
- (P2) Verify all ICLR datasets fully scored in single-item experiment
- (P2) Further refactor validation.py (2500+ lines)
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict
- (Future) Author profile pages showing all claimed papers

## Known Issues
- Mobile Twitter/X unfurling fails — blocked on user's Cloudflare configuration (see /app/memory/UNFURLING_REPORT.md)

## Key Issue: Budget Exhaustion
The Emergent LLM key budget gets exhausted during large-scale summary generation. User needs to top up via Profile -> Universal Key -> Add Balance.

## Completed Work
- Pairwise concordance-derived rho for Human-AI Benchmark (Mar 14 2026)
  - Replaced Spearman-on-scores with direct pairwise concordance
  - rho now derived via Kruskal (1958): rho = sin(π × (concordance − 0.5))
  - Concordance rate 72.0%, tie fraction 42.3% (previously invisible)
  - Thurstonian ceiling now 68.4% (was 58.9% with old method)
  - Added both committee and individual BT correlations
  - Cleaned all NeurIPS references from UI
- Methodological Correction of Inter-Rater Reliability (Mar 14 2026)
  - Changed from Pearson → Spearman → Pairwise concordance (iterative refinement)
- Removed NeurIPS experiment references from UI (Mar 14 2026)
- Added total controlled pairs display (Mar 14 2026)
- Linkable validation sub-URLs via ?v= search params (Mar 11 2026)
- Higher resolution leaderboard convergence matching validation charts (Mar 11 2026)
- Auto per-model SI rating extraction from summaries in scheduler (Mar 11 2026)
- Precomputed analysis caches for Model Correlation page (Mar 11 2026)
- Log/linear scale toggle on convergence charts (Mar 11 2026)
- Single-Item Rating Analysis section with model toggle on Model Analysis page (Mar 11 2026)
- Pre-computation system for production deployment
- Single-Item Scoring experiment
- "Surprisingly Popular" analysis
- Controlled PW Thinking Judge experiment
- Institutional Bias Analysis
- AlphaXiv Integration
- HTTP Security Headers middleware
- Live Leaderboard Metric Integration (Rating + Gap columns)
- Admin controls for leaderboard column visibility
- Non-blocking rating generation for existing papers
- Comprehensive Validation Summary Report page
- Author Verification MVP: ORCID OAuth + Semantic Scholar claiming (Mar 12 2026)
- Decoupled ORCID Verification & Public Badge Sharing (Mar 13 2026)
- Badge Share URL Fix & SVG Refinements (Mar 13 2026)
- Summary Token Tracking (Mar 13 2026)
