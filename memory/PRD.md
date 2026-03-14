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
- Human vs AI Benchmark: new Validation Hub section comparing inter-human and AI-human agreement rates across 7 controlled datasets (5,260 same-pair comparisons), with Thurstonian ceiling analysis, Cohen's kappa, difficulty stratification, and NeurIPS 2014 reference

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

## Recent Fix (Mar 9 2026)
- **Admin rating-status performance**: Moved per-category rating counts into the background leaderboard cache. The `/api/admin/rating-status` endpoint now accepts a `category` param and reads from pre-computed cache (~16ms) instead of doing 2-4 MongoDB `count_documents` calls (~200ms each). Category switching in admin panel is now instant.

## Pending Tasks
- (P1) Consolidate fragile MIDL experiment pipeline into single robust background task
- (P2) Explore adding new validation datasets from OpenReview (ICLR 2024 CV)
- (P2) Add missing HTTP security headers
- (P2) Improve summary generation failure tracking UI
- (P2) Continue refactoring monolithic leaderboard.py
- (P2) Verify all ICLR datasets fully scored in single-item experiment
- (P2) Further refactor validation.py (2500+ lines)
- (Future) Chain-of-thought variant: multi-aspect reasoning then holistic verdict
- (Future) Author profile pages showing all claimed papers

## Key Issue: Budget Exhaustion
The Emergent LLM key budget gets exhausted during large-scale summary generation. User needs to top up via Profile -> Universal Key -> Add Balance.

## Completed Work
- Linkable validation sub-URLs via ?v= search params (Mar 11 2026)
- Higher resolution leaderboard convergence matching validation charts (Mar 11 2026)
- Auto per-model SI rating extraction from summaries in scheduler (Mar 11 2026)
- Precomputed analysis caches for Model Correlation page (Mar 11 2026)
- Log/linear scale toggle on convergence charts (Mar 11 2026)
- Single-Item Rating Analysis section with model toggle on Model Analysis page (Mar 11 2026)
- Pre-computation system for production deployment
- Single-Item Scoring experiment - run on eLife (Cancer + Neuro), ICLR (7 datasets), MIDL, PeerRead, RH-50, Qeios Social
- "Surprisingly Popular" analysis: BT_rank - SI_rank as independent quality predictor
- Controlled PW Thinking Judge experiment on Qeios + RH-50
- Institutional Bias Analysis with controlled same-pair analysis
- AlphaXiv Integration for community popularity data
- HTTP Security Headers middleware
- Convergence chart fix
- Live Leaderboard Metric Integration (Rating + Gap columns)
- Admin controls for leaderboard column visibility
- Non-blocking rating generation for existing papers
- Comprehensive Validation Summary Report page
- Frontend rebuild for llm-ranker fork (Mar 9 2026)
- Deployment readiness verification (Mar 9 2026)
- Author Verification MVP: ORCID OAuth + Semantic Scholar claiming (Mar 12 2026)
  - Backend: /api/claim/* endpoints (connect ORCID, claim papers, verify via S2)
  - Frontend: AuthorClaimSection on paper pages, OrcidCallbackPage
  - Multi-signal verification: S2 direct ORCID match, S2 name match, DB name match, fallback to manual review
  - Verified badges display on paper pages
  - ORCID credentials configured and OAuth redirect tested end-to-end
- Decoupled ORCID Verification & Public Badge Sharing (Mar 13 2026)
  - ORCID linking moved to user Profile page, decoupled from paper claims
  - Admin approves ORCID links under Users tab (not Claims)
  - Profile page shows pending/verified status for ORCID link
  - Claims tab removed from admin panel
  - Badge sharing made public for all users
  - Socially shareable badges (Gold/Silver/Bronze) for top-3 papers in weekly/monthly archives
  - SVG templates + CairoSVG for server-side OG image generation
  - SITE_URL env var ensures kurate.org in OG tags on production
- Badge Share URL Fix & SVG Refinements (Mar 13 2026)
  - Fixed share URL: frontend now uses window.location.origin (kurate.org on prod) instead of REACT_APP_BACKEND_URL
  - Removed "arXiv (cs.XX)" from badge header to prevent logo overlap
  - Categories now show "Category: cs.DC, cs.AI" format with all categories from paper record
- Summary Token Tracking (Mar 13 2026)
  - generate_precomparison_impact_summary now calls litellm.completion directly to capture actual usage
  - Stores {input, output, thinking} tokens per summary in paper.summary_tokens.{model_key}
  - Admin stats endpoint uses tracked tokens when available, falls back to improved estimates
  - Thinking tokens for Opus Thinking now properly accounted for in cost calculation
  - Cost estimates corrected from $105 to ~$303 for summaries (3x underestimate fixed)
