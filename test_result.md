# Test Result - SciRank Category Separation & Matchmaking

## Testing Protocol
# DO NOT EDIT THIS SECTION

## Current Test Focus
### Task: Category Separation Verification + Matchmaking Improvement

### Changes Made:
1. **Per-category scheduler_status** - Each category now has its own `is_fetching`, `is_processing`, `current_activity`, `last_fetch_at`, `next_fetch_at` tracked independently
2. **Per-category fetch timer** - Each category has its own `last_fetch_at_<category>` in settings, so fetching is independent
3. **Scoped _download_pending_pdfs** - Now accepts `category` parameter and only downloads PDFs for that category's papers
4. **Scoped _generate_pending_summaries** - Now accepts `category` parameter and only generates summaries for that category's papers
5. **Per-category admin stats** - `/api/admin/stats` endpoint now accepts `?category=` parameter to filter token/cost/storage by category
6. **Frontend admin page** - Stats and scheduler status now properly reflect the selected category
7. **Improved matchmaking** - CI-driven priority, win-rate similarity bonus, extreme paper deprioritization

### Credentials:
- Admin URL: /admin
- Admin password: papersumo2025

### Key API Endpoints to Test:
- GET /api/admin/status?category=cs.RO (should show Robotics-specific scheduler status)
- GET /api/admin/status?category=physics.comp-ph (should show Comp Physics-specific scheduler status)
- GET /api/admin/stats?category=cs.RO (should show Robotics-specific usage)
- GET /api/admin/stats?category=physics.comp-ph (should show Comp Physics-specific usage)
- GET /api/admin/progress?category=cs.RO
- GET /api/leaderboard?category=cs.RO&period=all
- GET /api/leaderboard?category=physics.comp-ph&period=all

### Test Scenarios:
1. **Category isolation - Status**: Admin status for cs.RO should show different activity/counts than physics.comp-ph
2. **Category isolation - Stats**: Usage stats (tokens, cost, storage) should differ between categories
3. **Category isolation - Leaderboard**: Each category should show its own papers and match counts
4. **Scheduler per-category fields**: `is_fetching`, `is_processing`, `current_activity` should be per-category
5. **Frontend category switching**: Admin page should update all data when switching category tabs
6. **Matchmaking distribution**: After new comparison rounds, match counts should NOT be perfectly uniform

