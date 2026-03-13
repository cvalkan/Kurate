# Cloudflare Skip Rules for Share Endpoints

## Why
Cloudflare injects JavaScript detection scripts into HTML responses. This can confuse social media crawlers (LinkedIn, Twitter) when they parse OG meta tags from share pages. Bypassing these injections on share/image endpoints ensures clean HTML for crawlers.

## Steps to Configure

### 1. Go to Cloudflare Dashboard
- Log in at https://dash.cloudflare.com
- Select the `kurate.org` zone

### 2. Create a WAF Custom Rule (Skip)
Navigate to: **Security → WAF → Custom rules → Create rule**

**Rule name:** `Skip bot challenges on share endpoints`

**Expression (Edit expression):**
```
(http.request.uri.path contains "/api/badge/" and http.request.uri.path contains "/share") or 
(http.request.uri.path contains "/api/badge/" and http.request.uri.path contains "/image.png") or 
(http.request.uri.path contains "/api/lists/" and http.request.uri.path contains "/share") or 
(http.request.uri.path contains "/api/lists/" and http.request.uri.path contains "/image.png")
```

**Action:** Skip → Check all skip options:
- ✅ Skip: All remaining custom rules
- ✅ Skip: Rate limiting  
- ✅ Skip: Managed rules
- ✅ Skip: Super Bot Fight Mode (if enabled)

Click **Deploy**.

### 3. Alternatively: Use Page Rules
Navigate to: **Rules → Page Rules → Create Page Rule**

**URL pattern:** `kurate.org/api/badge/*/share`
**Setting:** Disable Security (or set Security Level to "Essentially Off")

Repeat for:
- `kurate.org/api/badge/*/image.png`
- `kurate.org/api/lists/*/share`  
- `kurate.org/api/lists/*/image.png`

### 4. If Using Super Bot Fight Mode
Navigate to: **Security → Bots → Configure Super Bot Fight Mode**

Check that "Verified Bots" (which includes LinkedIn, Twitter, Google bots) are set to **Allow**. These are bots that Cloudflare has verified as legitimate crawlers.

### 5. Test
After deploying rules, verify:
```bash
# Should return clean HTML with no Cloudflare challenge scripts
curl -s -H "User-Agent: LinkedInBot/1.0" "https://kurate.org/api/badge/cs.RO/2026/w10/PAPER_ID/share" | grep -c "CF\$cv\$params"
# Expected: 0

curl -s -H "User-Agent: Twitterbot/1.0" "https://kurate.org/api/lists/LIST_ID/share" | grep -c "CF\$cv\$params"  
# Expected: 0
```

## Notes
- These rules only affect the specific share/image paths, not the rest of the site
- The skip rules ensure crawlers get the raw HTML response without any JavaScript injection
- This is the most reliable way to ensure consistent unfurling on social platforms
- Free Cloudflare plans support up to 5 Page Rules; WAF custom rules may require a paid plan
