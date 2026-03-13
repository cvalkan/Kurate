# Social Media Unfurling Issues — Technical Report

## Context
Kurate.org (PaperSumo) generates shareable badge images for top-ranked scientific papers and reading list previews. These are shared on Twitter/X and LinkedIn via OG meta tags served from FastAPI endpoints.

## Architecture
- **Share pages**: Server-rendered HTML at `/api/badge/{...}/share` and `/api/lists/{id}/share`
- **OG images**: Dynamically generated SVG→PNG via CairoSVG at `/api/badge/{...}/image.png` and `/api/lists/{id}/image.png`
- **Browser redirect**: JS `window.location.replace()` sends human visitors to the SPA page
- **Infrastructure**: FastAPI → Kubernetes → Cloudflare (production at kurate.org)

---

## Issue 1: Badge share URL using wrong domain
**Symptom**: LinkedIn share links pointed to `scirank.emergent.host` (old Emergent preview URL) instead of `kurate.org`.

**Root cause**: The frontend constructed share URLs using `process.env.REACT_APP_BACKEND_URL` which was baked into the JS bundle at build time with the old preview URL.

**Fix**: Changed to `window.location.origin` so URLs are always relative to the current domain.

**Status**: ✅ Resolved

---

## Issue 2: Badge image not rendering on Twitter
**Symptom**: Twitter card showed title/description but generic icon instead of badge image.

**Root cause**: The `og:image` URL pointed to `kurate.org` (via `SITE_URL` env var) even when sharing from the preview environment. The preview's image endpoint worked, but the OG tag pointed to production which didn't have the data.

**Fix**: Changed OG image URL to use the request's actual host (`x-forwarded-host` header) instead of hardcoded `SITE_URL`. Falls back to `SITE_URL` only when header is missing or contains internal K8s hostname.

**Complication**: The first attempt used `request.headers.get("host")` which returned the internal K8s hostname (`orcid-verify.cluster-5.preview.emergentcf.cloud`). Fixed by checking `x-forwarded-host` first, with a `"cluster" not in host` guard.

**Status**: ✅ Resolved

---

## Issue 3: HEAD requests returning 405
**Symptom**: LinkedIn showed small thumbnail instead of large image card. Badge image existed but LinkedIn rendered it in degraded format.

**Root cause**: FastAPI's `@router.get()` only handles GET, not HEAD. LinkedIn's crawler sends HEAD first to check content-type/size before fetching the full image. The 405 response may have caused LinkedIn to downgrade the card format.

**Fix**: Added middleware that intercepts HEAD requests on `/api/badge/` and `/api/lists/` paths, converts them to GET internally, executes the handler, and returns headers-only response (per HTTP spec).

**Status**: ✅ Resolved. HEAD now returns 200 with correct `content-type: image/png`.

---

## Issue 4: LinkedIn showing generic OG tags for reading lists
**Symptom**: LinkedIn share showed "PaperSumo by Kurate.org — AI Paper Rankings" (the SPA's default OG tags from index.html) instead of the list-specific title/image.

**Root causes** (multiple, layered):

### 4a: Code not deployed
The reading lists feature was new. First LinkedIn share attempt was before deployment → 404 → LinkedIn cached the generic fallback.

### 4b: `og:url` pointing to SPA
The share page's `og:url` meta tag pointed to `/list/{id}` (the SPA route). LinkedIn re-crawls `og:url` as the canonical URL. The SPA serves `index.html` with generic OG tags → LinkedIn used those instead.

**Fix**: Changed `og:url` to point to the share page itself (`/api/lists/{id}/share`) rather than the SPA route.

### 4c: JS redirect confusing crawlers
The share page included `<script>window.location.replace(...)</script>` for all visitors. While social crawlers don't execute JS, some may parse the redirect target and follow it.

**Fix**: Added bot detection via User-Agent string. Crawlers (LinkedInBot, Twitterbot, facebookexternalhit, etc.) get the HTML without the redirect script. Regular browsers still get redirected.

### 4d: Cloudflare challenge script injection
Cloudflare injects a bot-detection iframe/script at the bottom of every response:
```html
<script>(function(){function c(){var b=a.contentDocument...}})();</script>
```
This appears in both preview and production responses. Its impact on crawler parsing is unclear but may interfere with some parsers.

**Status**: ⚠️ Partially resolved. Works reliably after deploying all fixes + using LinkedIn Post Inspector to force re-crawl. May still be flaky for brand-new URLs due to Cloudflare injection.

### 4e: LinkedIn caching
LinkedIn caches crawl results for up to 7 days. Once a URL returns bad data (404, generic OG tags), subsequent shares show the cached result regardless of server-side fixes.

**Workaround**: Added `?v=2` cache buster to share URLs. LinkedIn treats this as a new URL and re-crawls.

**Status**: ⚠️ Workaround in place. LinkedIn Post Inspector can force re-crawl for specific URLs.

---

## Issue 5: Badge Twitter unfurl broke after URL change
**Symptom**: Badge share on Twitter showed arXiv card instead of Kurate badge. The badge image/title disappeared.

**Root cause**: The badge `shareUrl` was changed from `/api/badge/.../share` (which has OG tags) to `/leaderboard/cs.RO/2026/w12` (SPA route, no OG tags). Twitter unfurled the last URL in the tweet — since the leaderboard SPA has no specific OG tags, Twitter picked the arXiv URL instead.

**Fix**: Reverted `shareUrl` back to `/api/badge/.../share` for social sharing. The "Copy link" button still copies the leaderboard URL for human use.

**Status**: ✅ Resolved

---

## Issue 6: Image generation too slow for crawlers
**Symptom**: Unfurling worked intermittently. Sometimes the image appeared, sometimes it didn't.

**Root cause**: CairoSVG image rendering takes 2-3 seconds per image. LinkedIn has a ~3-5 second timeout for fetching OG images. Under server load, rendering could exceed the timeout.

**Measurements** (production):
| Endpoint | Cold render | With cache |
|----------|------------|------------|
| Badge image | 2.4s | 0.12s |
| List image | 3.0s | 0.15s |
| Badge share page | 0.9s | 0.9s |

**Fix**: Added in-memory image cache with 1-hour TTL. First request renders and caches; subsequent requests serve from memory. Cache auto-evicts entries older than TTL when size exceeds 500 entries.

**Status**: ✅ Resolved. Cached images serve well under any crawler timeout.

---

## Current Architecture (after all fixes)

```
User clicks "Share on Twitter/LinkedIn"
  → Opens share URL: /api/badge/.../share or /api/lists/{id}/share
  → Social crawler fetches URL:
      1. HEAD request → middleware converts to GET, returns headers only (200, image/png)
      2. GET request → server checks User-Agent:
         - Bot: returns HTML with OG tags, NO JS redirect
         - Browser: returns HTML with OG tags + JS redirect to SPA
      3. Crawler reads og:image URL → fetches image
         - Cache hit: serves from memory (~100ms)
         - Cache miss: renders SVG→PNG via CairoSVG (~2-3s), caches result
```

## Remaining Risks
1. **Cloudflare challenge scripts**: Injected into every response. Impact on crawler parsing is unknown. Cannot be removed (Cloudflare infrastructure).
2. **LinkedIn caching**: 7-day cache means bad first impressions persist. Cache buster (`?v=N`) helps but isn't automatic.
3. **Twitter last-URL unfurling**: Twitter unfurls the last URL in tweet text. If tweet contains both arXiv link and share link, position matters. Currently share URL is last.
4. **Production cold starts**: After deploy, first image request for each badge/list is slow (2-3s). Pre-warming the cache on startup could help but adds complexity.

## Recommendations for Further Investigation
1. **Pre-render and store images**: Instead of generating on-the-fly, render badge/list images when archives are created or lists are saved. Store as static files or in MongoDB GridFS. Eliminates cold-render latency entirely.
2. **Cloudflare Page Rules**: Configure Cloudflare to NOT inject challenge scripts on `/api/badge/*/share` and `/api/lists/*/share` paths. This may require Cloudflare dashboard configuration.
3. **Test with Twitter Card Validator**: Use https://cards-dev.twitter.com/validator to check specific URLs.
4. **Test with LinkedIn Post Inspector**: Use https://www.linkedin.com/post-inspector/ to force re-crawl and verify OG tags.
