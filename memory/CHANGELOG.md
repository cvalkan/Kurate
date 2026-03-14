# Changelog

## March 14, 2026
### Bug Fix: Mobile Twitter Unfurling (Investigation ongoing)
- **Attempted Fix 1**: Replaced `<meta http-equiv="refresh" content="0;url=...">` with `<script>window.location.replace()</script>` — DID NOT FIX mobile issue
- **Attempted Fix 2**: Removed ALL redirects/JavaScript from share pages — made them 100% pure static HTML — DID NOT FIX mobile issue  
- **Attempted Fix 3**: Changed Twitter intent URL to use explicit `url` parameter instead of embedding share URL in `text` — user reports STILL NOT FIXED
- **Conclusion**: The issue is external to our code. Share pages serve correct OG tags. Likely causes:
  1. **Cloudflare Bot Management** interfering with Twitter's mobile crawler (different IP ranges/challenge behavior)
  2. **Twitter Card Cache** persisting old data for the URL
  3. **Twitter mobile app** using a different card resolution mechanism than desktop

### Feature: Open Congrats Section
- Made "Congrats on X" and "Congrats on LinkedIn" buttons accessible to all visitors (no login required)
- Email congrats flow remains behind sign-in (for rate limiting and LLM email extraction)
- Removed the full login gate that previously blocked all congrats functionality

### Feature: Human vs AI Agreement Benchmark
- New backend endpoint: `/api/validation/human-ai-benchmark`
- New frontend section in Validation Hub under Experiments > Judge Quality
- **6-layer analysis across 7 datasets (5,260 controlled same-pair comparisons)**:
  1. Inter-rater correlation rho (pooled: 0.39, NeurIPS ref: 0.2-0.3)
  2. Thurstonian theoretical ceiling (59.0% from model, actual H-H is 79.1%)
  3. Controlled pairwise agreement: H-H=79.1%, H-Comm=92.3%, AI-H=69.7%, AI-Comm=71.9%
  4. Difficulty stratification: hard (within-tier) H-H=62.9%, AI-H=59.5% — closest NeurIPS comparison
  5. BT rank correlation: Spearman=0.524, Kendall=0.360
  6. Cohen's kappa for chance-corrected agreement
- Per-dataset breakdown with collapsible table
- NeurIPS 2014 reference context with explanatory note

### Architecture: Share Page Simplification
- Share pages are now 100% pure static HTML — no JavaScript, no redirects
- Human visitors click a styled "View Leaderboard on Kurate.org" button
- Crawlers see only clean OG/Twitter meta tags
