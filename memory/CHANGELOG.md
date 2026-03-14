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

### Architecture: Share Page Simplification
- Share pages are now 100% pure static HTML — no JavaScript, no redirects
- Human visitors click a styled "View Leaderboard on Kurate.org" button
- Crawlers see only clean OG/Twitter meta tags
