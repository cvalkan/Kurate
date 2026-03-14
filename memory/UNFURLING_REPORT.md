# Social Media Unfurling Issues — Technical Report

## Context
Kurate.org (PaperSumo) generates shareable badge images for top-ranked scientific papers and reading list previews. These are shared on Twitter/X and LinkedIn via OG meta tags served from FastAPI endpoints.

## Architecture (as of Mar 14 2026)
- **Share pages**: Server-rendered **100% static HTML** at `/api/badge/{...}/share` and `/api/lists/{id}/share`. Zero JavaScript, zero redirects. Just OG meta tags + a clickable button for human visitors.
- **OG images**: Pre-rendered SVG→PNG via CairoSVG, persistently cached in MongoDB (`prerendered_images` collection). Fallback to on-the-fly rendering + in-memory cache.
- **Human navigation**: Manual click via styled "View Leaderboard on Kurate.org" button (no automatic redirect of any kind).
- **Twitter sharing**: Uses `twitter.com/intent/tweet?text=...&url=SHARE_URL` with the dedicated `url` parameter to explicitly set which URL generates the card.
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

**Fix**: Added in-memory image cache with 1-hour TTL + persistent MongoDB storage (`prerendered_images` collection). Images are pre-rendered when archives/lists are created. Cached images serve well under any crawler timeout.

**Status**: ✅ Resolved

---

## Issue 7: Twitter unfurling works from desktop but NOT from mobile (Mar 14 2026)
**Symptom**: Identical tweets containing the same share URL produce different cards depending on whether posted from desktop or mobile Twitter:
- **Desktop**: Correct rich badge card with pre-rendered image, badge-specific title/description
- **Mobile**: Generic fallback card showing root domain metadata ("PaperSumo by Kurate.org — AI Paper Rankings"), no badge image

**Screenshot evidence**: Side-by-side posts by same user, same URL, ~20 seconds apart. Desktop post shows full badge card; mobile post shows generic `kurate.org` summary card with a document icon.

### Investigation timeline

**Attempt 1: Remove `<meta http-equiv="refresh">`**
- **Hypothesis**: The `<meta http-equiv="refresh" content="0;url=...">` tag in the share page was causing Twitter's mobile crawler to follow the instant redirect before reading OG tags, landing on the SPA page (which has default OG metadata).
- **Action**: Replaced meta-refresh with `<script>window.location.replace(...)</script>`.
- **Result**: ❌ Did not fix the issue. Mobile still shows generic card.

**Attempt 2: Remove ALL JavaScript and redirects**
- **Hypothesis**: Twitter's mobile app may use a WebView (which executes JS) to preview URLs, causing the JS redirect to fire before OG tags are extracted.
- **Action**: Removed ALL JavaScript from share pages. Pages are now 100% pure static HTML — only `<meta>` tags in `<head>` + a clickable `<a>` link in `<body>`. Zero redirects of any kind.
- **Result**: ❌ Did not fix the issue. Mobile still shows generic card.

**Attempt 3: Use Twitter `url` intent parameter**
- **Hypothesis**: The tweet text contains multiple URLs (bare "Kurate.org" domain, arXiv link, share URL). Twitter picks which URL to use for the card, and mobile/desktop pick differently. Desktop uses the last URL (share URL → correct card), mobile picks "Kurate.org" (root domain → generic card).
- **Action**: Changed `twitter.com/intent/tweet?text=...` to `twitter.com/intent/tweet?text=...&url=SHARE_URL`, using the dedicated `url` parameter which explicitly tells Twitter which URL generates the card. Removed the share URL from the `text` parameter.
- **Result**: ❌ Did not fix the issue according to user testing.

### Verified facts
1. **Share page serves correct OG tags** — verified via `curl` with Twitterbot User-Agent. All `og:title`, `og:description`, `og:image`, `twitter:card`, `twitter:image` tags are present and correct.
2. **Image endpoint responds correctly** — returns HTTP 200, `content-type: image/png`, ~191KB.
3. **HEAD requests work** — middleware converts HEAD to GET for badge/list endpoints, returns 200.
4. **No redirects or JavaScript** — share pages are 100% static HTML after attempt 2.
5. **The issue persists across both preview and production domains.**

### Remaining hypotheses (external to code)

**H1: Cloudflare Bot Management (MOST LIKELY)**
Cloudflare injects a challenge script into every response:
```html
<script>(function(){function c(){var b=a.contentDocument...window.__CF$cv$params=...}})();</script>
```
Twitter's mobile crawler may originate from a different IP range/ASN than the desktop crawler. Cloudflare may:
- Serve a full JS challenge page (blocking the real content) to mobile crawler IPs
- Allow desktop crawler IPs through without challenge
- This would explain why the same URL returns different cards for mobile vs desktop

**Action required**: Check Cloudflare dashboard → Security → Events for blocked/challenged requests with User-Agent containing "Twitterbot". Create Cloudflare WAF exception rules (Skip rules) for paths matching `/api/badge/*/share`, `/api/badge/*/image.png`, `/api/lists/*/share`, `/api/lists/*/image.png`.

**H2: Twitter's mobile app uses a different card resolution mechanism**
Desktop Twitter (web client) sends URLs to Twitter's server-side Twitterbot crawler. Mobile Twitter app may:
- Use its own embedded WebView to generate card previews during composition
- Cache the preview generated during composition and use it as the final card
- Use a completely different backend service for mobile-originated cards

If the mobile app's preview mechanism follows a different code path than Twitterbot, it could explain the discrepancy even with perfect HTML.

**H3: Twitter card caching per-device-type**
Twitter may maintain separate card caches for mobile and desktop clients. If the URL was first shared from mobile before our fixes, the cached (broken) card might persist for mobile while desktop got a fresh crawl.

**Action required**: Test with a completely new URL that has never been shared before (use a different paper's badge, or append `?v=3` as cache buster).

**H4: Twitter Card Validator**
Use https://cards-dev.twitter.com/validator to force Twitter to re-crawl the URL. This should update the card for both mobile and desktop. If the validator shows the correct card but mobile still doesn't, it confirms a mobile-specific crawler issue.

**Status**: ⚠️ **UNRESOLVED** — All code-side fixes exhausted. Issue is external (Cloudflare and/or Twitter infrastructure).

---

## Current Architecture (after all fixes, Mar 14 2026)

```
User clicks "Share on Twitter"
  → Opens twitter.com/intent/tweet?text=...&url=SHARE_URL
  → Twitter crawler fetches SHARE_URL:
      1. HEAD request → middleware converts to GET, returns headers only (200)
      2. GET request → server returns 100% static HTML:
         - <head> contains all og: and twitter: meta tags
         - <body> contains human-readable summary + clickable button
         - ZERO JavaScript, ZERO redirects
      3. Crawler reads og:image URL → fetches /api/badge/.../image.png
         - Pre-rendered in MongoDB: serves instantly (~100ms)
         - Cache miss: renders SVG→PNG via CairoSVG (~2-3s), caches result
```

## Remaining Risks
1. **Cloudflare challenge scripts** (HIGH): Injected into every response. May block Twitter's mobile crawler entirely, causing fallback to root domain metadata. Requires Cloudflare dashboard configuration to create bypass rules for share/image paths.
2. **Twitter mobile unfurling** (HIGH): Desktop works, mobile does not. All code-side fixes exhausted. Likely Cloudflare or Twitter infrastructure issue. See Issue 7 for full investigation.
3. **LinkedIn caching**: 7-day cache means bad first impressions persist. Cache buster (`?v=N`) helps but isn't automatic.
4. **No automatic redirect for human visitors**: Share pages now require a manual click to reach the interactive SPA. This is a deliberate tradeoff for maximum crawler compatibility.

## Recommended Next Steps
1. **Cloudflare Skip Rules** (P0): Create WAF exception rules in Cloudflare dashboard to bypass bot management for `/api/badge/*/share`, `/api/badge/*/image.png`, `/api/lists/*/share`, `/api/lists/*/image.png`. This is the most likely fix for the mobile unfurling issue.
2. **Twitter Card Validator** (P0): Test specific share URLs at https://cards-dev.twitter.com/validator to force re-crawl and verify OG tag extraction.
3. **Cache buster test** (P0): Share a badge URL with `?v=3` appended from mobile to rule out Twitter caching.
4. **Synthetic Unfurl Test Suite** (P1): Create automated tests that fetch share pages as different crawlers (Twitterbot, LinkedInBot, facebookexternalhit) and verify OG tags and image endpoint responses.
5. **LinkedIn Post Inspector**: Use https://www.linkedin.com/post-inspector/ to verify LinkedIn unfurling after any changes.
