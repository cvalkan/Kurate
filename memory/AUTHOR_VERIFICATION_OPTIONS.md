# Author Verification & Paper Claiming — Options Analysis
*Date: April 5, 2026*

## Goal
Allow researchers to claim authorship of their papers on Kurate.org, proving they are who they say they are and linking their identity to their publications.

## Current Implementation Status
- **ORCID OAuth**: Fully built (backend + frontend). Proves identity, extracts institutional email domains.
- **Semantic Scholar helpers**: Built — paper lookup by arXiv ID, author search by ORCID (unreliable), author paper list retrieval.
- **Verification pipeline**: Built — multi-signal verification with fuzzy name matching, trust levels.
- **Frontend component**: Built but orphaned (not wired to any page).
- **ORCID credentials**: Configured in production `.env`.

## Key Finding: S2 ORCID Lookup Coverage is ~7%, Not 40-60%

Semantic Scholar stores ORCID in `externalIds` on some author profiles, and the data structure exists for `ORCID:xxx` direct lookup. However, empirical testing (April 2026) shows extremely sparse coverage:

- Tested 15 prominent CS/ML researchers (LeCun, Hinton, Sutskever, Bengio, Manning, Narayanan, Abebe, Gebru, Guestrin, etc.)
- **Only 1/15 (Manning) had ORCID mapped on S2** (~7%)
- The `ORCID:xxx` direct lookup endpoint returns 404 for all tested ORCIDs — even Manning's, despite his profile having the ORCID in `externalIds`
- S2 author search by ORCID ID string also returns 0 results for all tested

**Conclusion:** S2's ORCID→author mapping cannot be relied upon as a primary verification path. It's useful as a fast-track shortcut (check first, skip disambiguation if found), but 90%+ of users will need a fallback.

---

## Option A: ORCID + S2 Name Search

**Flow:**
1. User connects ORCID (OAuth) → proves identity, gives real name + institutional email
2. Backend searches Semantic Scholar by **name** (not ORCID)
3. User picks their S2 author profile from results (disambiguation step)
4. Backend fetches all papers for that S2 author
5. Cross-reference with Kurate's DB by arXiv ID
6. User confirms which papers are theirs

**Pros:**
- S2 has a real, stable API (free, no scraping)
- ORCID provides strong identity proof
- S2 paper entries include arXiv IDs → direct matching with Kurate's DB
- Most infrastructure already built

**Cons:**
- **Name disambiguation is a real problem**: "Wei Zhang" returns thousands of S2 results. Common names make the picker UX painful or unusable.
- Relies on user correctly identifying their S2 profile among duplicates
- S2 author profiles can be fragmented (same person split across multiple IDs)

**Effort:** ~1 day (name search endpoint + disambiguation UI + bulk confirm)

---

## Option B: ORCID + Google Scholar URL (Recommended)

**Flow:**
1. User connects ORCID (OAuth) → proves identity, gives institutional email domain
2. User pastes their Google Scholar profile URL (e.g., `https://scholar.google.com/citations?user=kukA0LcAAAAJ`)
3. Backend fetches the **single public profile page** → extracts:
   - "Verified email at [domain]" (institutional affiliation signal)
   - Paper titles listed on the profile
4. **Domain cross-check**: ORCID institutional email domain vs Scholar verified domain. If they match → high trust (no email verification code needed)
5. Cross-reference Scholar paper titles against Kurate's DB (fuzzy title matching)
6. User confirms matched papers → bulk claim

**Pros:**
- **No disambiguation**: user provides their exact profile URL
- Researchers know their Scholar URL (or find it in seconds)
- Scholar profiles are the most complete & actively maintained publication lists
- ORCID + Scholar domain match provides strong verification without sending email codes
- Fetching one public page per claim is not bulk scraping — well within acceptable use

**Cons:**
- **No Google Scholar API**: must parse public HTML. The page structure has been stable for years (`gsc_a_at` class for paper titles, "Verified email at" text), but Google could change it without notice.
- Some profiles show "Verified email at gmail.com" (useless as institutional signal)
- Paper matching is by title (not arXiv ID) since Scholar doesn't consistently show arXiv IDs
- If Google starts CAPTCHAing single-page fetches, the flow breaks (fallback: ask user to paste paper titles manually)

**Effort:** ~1-2 days (Scholar page parser + domain cross-check + title matching + bulk confirm UI)

---

## Option C: Google Scholar URL + Email Verification Code (alphaXiv's approach)

**Flow:**
1. User pastes Google Scholar profile URL
2. Backend scrapes profile → extracts "Verified email at [domain]" + paper list
3. User provides their full institutional email (e.g., `jsmith@stanford.edu`)
4. Backend verifies the email domain matches Scholar's verified domain
5. Backend sends a verification code to that email address
6. User enters code → proves they control the institutional email
7. Papers synced from Scholar profile

**Pros:**
- Proven flow (alphaXiv uses it)
- No ORCID dependency
- Email verification code is a strong ownership proof

**Cons:**
- Same HTML parsing fragility as Option B
- Requires email-sending infrastructure (Resend integration — not yet built)
- Scholar only shows the **domain**, not the full email. User must provide their email, and you check the domain matches. Potential for mismatch (e.g., user has multiple institutional emails).
- More steps for the user (paste URL + enter email + enter code)
- No ORCID means no additional identity proof beyond "controls an email at this domain"

**Effort:** ~2-3 days (Scholar parser + email sending via Resend + code verification flow + UI)

---

## Option D: ORCID + S2 Name Search + Scholar URL Fallback

**Flow:**
1. User connects ORCID → identity + institutional email
2. Try S2 author search by name → show results if unambiguous
3. If ambiguous or user can't find themselves → fallback to "paste your Google Scholar URL"
4. Cross-reference papers with Kurate's DB
5. User confirms

**Pros:**
- Best of both: S2 API for clean cases, Scholar URL for disambiguation edge cases
- Graceful degradation

**Cons:**
- Most complex to build and maintain
- Two different paper-matching paths (arXiv ID from S2 vs title from Scholar)

**Effort:** ~2-3 days

---

## Recommendation

**Option B (ORCID + Google Scholar URL)** is the sweet spot:
- No disambiguation problem (user provides exact URL)
- ORCID domain match eliminates the need for email verification codes
- Single public page fetch is reliable and not scraping
- Combines strong identity proof (ORCID) with the most complete paper graph (Scholar)
- Least user friction after ORCID connect (just paste a URL)

The ORCID infrastructure is already built. The new work is: Scholar page parser (~30 lines), domain cross-check (~10 lines), title matching against Kurate DB (~30 lines), and the bulk confirm UI.

**Fallback plan**: If Scholar HTML parsing breaks, degrade to Option A (S2 name search with disambiguation picker). The S2 API is stable and free.


---

## Option E: ORCID as Both Identity AND Verification

**Flow:**
1. User connects ORCID (OAuth) → proves identity *(already built)*
2. User selects a paper on Kurate they want to claim
3. Kurate shows: "To verify authorship, add this paper to your ORCID profile" with guidance/link to orcid.org
4. User adds the paper on their ORCID profile (via DOI search, manual entry, or institutional auto-import)
5. User clicks "I've added it" on Kurate
6. Backend calls `GET /v3.0/{orcid_id}/works` → checks if the paper appears (matched by DOI or arXiv ID in external identifiers)
7. Found → auto-verified. Not found → "Paper not detected yet, please check your ORCID profile"

**Pros:**
- **ORCID is the single source of truth** for both identity and publication ownership — no S2, no Scholar, no scraping
- Official, free, stable API with read scope already available
- No name disambiguation, no fuzzy matching, no HTML parsing
- Zero external service dependencies beyond ORCID itself
- Encourages researchers to maintain their ORCID (benefit to the community)
- Simplest backend: one API call to check works list

**Cons:**
- **No deep link** to pre-fill ORCID's "add work" form — user must manually add the paper on orcid.org (some friction)
- Many researchers have sparse ORCID profiles — adding a paper is an extra step
- Slight delay: ORCID API may take a few seconds to reflect newly added works
- Less familiar UX than "paste your Scholar URL" (more researchers use Scholar than actively manage ORCID)

**Effort:** ~0.5-1 day. ORCID OAuth and API helpers already built. New work: works-check endpoint (~30 lines), UI guidance flow, on-demand verification trigger.

---

## Updated Recommendation

**Option E (ORCID-only)** is the cleanest and most maintainable path if the user base is comfortable with ORCID. No external dependencies, no scraping, no disambiguation.

**Option B (ORCID + Scholar URL)** is better if you want lower friction for researchers who already have Scholar profiles and may not actively maintain ORCID.

Both can coexist: Option E as the primary path, Option B as a "fast track" alternative for users with Scholar profiles. The ORCID identity layer is shared between both.
