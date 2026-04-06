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

---

## Empirical Survey: ORCID → S2 Linkability (April 2026, n=50)

Sample: 50 ORCID profiles from arXiv-relevant domains (CS, ML, NLP, robotics, physics, economics, quantum computing, biomolecular).

### ORCID Profile Quality
| Metric | Count | % |
|---|---|---|
| Has works on ORCID | 42/50 | **84%** |
| Has verified email visible | 14/50 | 28% |
| Has institutional email domain | 13/50 | 26% |

### S2 Linkability
| Method | Count | % |
|---|---|---|
| S2 direct ORCID lookup | 0/50 | **0%** (completely unusable) |
| S2 name search finds candidates | 33/50 | 66% |
| S2 name result has matching ORCID | 1/50 | 2% |

### S2 Name Search Disambiguation
Of the 33 profiles with S2 name search results:
- Unambiguous (1 candidate): 8/33 (24%)
- Ambiguous (2+ candidates): 25/33 (**76% need disambiguation**)

### Institutional vs Non-Institutional
| Metric | Institutional (n=13) | Non-institutional (n=37) |
|---|---|---|
| Has works on ORCID | 100% | 78% |
| S2 findable by name | 77% | 62% |
| S2 by ORCID | 0% | 0% |

### Key Insight (CORRECTED)
The first survey (general ORCID keyword search) showed 84% with works — but this was biased toward established researchers who have keywords in their ORCID profiles. **A second survey of actual Kurate leaderboard authors tells a very different story.**

---

## Survey 2: Kurate Leaderboard Authors (April 2026, n=40)

Sample: First authors of actual papers on Kurate's leaderboard across cs.RO, cs.CR, cs.DC, cs.SI, astro-ph.CO, quant-ph.

### ORCID Profile Quality
| Metric | Count | % |
|---|---|---|
| Has ORCID profile (found by name) | 32/40 | 80% |
| ORCID with any works | 11/40 | **28%** |
| ORCID with 5+ works | 5/40 | 12% |
| Has auto-imported works (Crossref etc.) | 10/40 | 25% |
| Has institutional email | 4/40 | 10% |

### S2 Linkability
| Method | Count | % |
|---|---|---|
| S2 direct ORCID lookup | 0/32 | **0%** |
| S2 name search finds candidates | 38/40 | 95% |
| S2 name unambiguous (1 result) | 10/38 | 26% |
| S2 name ambiguous (2+ results) | 28/38 | **74%** |
| S2 result has matching ORCID | 0/32 | 0% |

### S2 Name Search Disambiguation Detail
| Candidates | Count | Notes |
|---|---|---|
| 1 (unambiguous) | 10 | Can auto-link |
| 2 | 4 | Manageable picker |
| 3 | 4 | Manageable picker |
| 4 | 2 | Needs context (affiliation, paper count) |
| 5 (max returned) | 18 | Likely more — may need better disambiguation |

### Comparison: General ORCID vs Kurate Authors
| Metric | General (n=50) | Kurate (n=40) |
|---|---|---|
| ORCID with works | **84%** | **28%** |
| ORCID with 5+ works | ? | 12% |
| Institutional email | 26% | 10% |
| S2 direct ORCID | 0% | 0% |
| S2 name found | 66% | 95% |
| S2 name unambiguous | 24% | 26% |

**Why the gap:** Kurate authors are recent arXiv preprint authors — often junior researchers (grad students, postdocs). Their papers are preprints (no DOI → no Crossref auto-import). The general ORCID sample was biased toward established researchers with keyword-rich profiles.

---

## S2 ORCID Coverage (Empirical Data)

### Celebrity Researcher Test (n=15)
Tested prominent CS/ML researchers (LeCun, Hinton, Bengio, Manning, etc.):
- Only 1/15 (Manning) had ORCID mapped on S2 (~7%)
- The `ORCID:xxx` direct lookup endpoint returns 404 for all tested

### Broad Sample (n=50)
- S2 direct ORCID lookup: **0/50 (0%)**
- S2 name search: 66% find candidates, but 76% of those are ambiguous

**Conclusion:** S2 ORCID mapping is completely unusable as a primary path. S2 name search works for ~66% but with severe disambiguation problems (76% ambiguous). Neither is reliable enough as a primary verification method.

---

## Option E: ORCID as Both Identity AND Verification (Recommended)

**Flow:**
1. User connects ORCID (OAuth) → proves identity *(already built)*
2. User selects a paper on Kurate they want to claim
3. Backend calls `GET /v3.0/{orcid_id}/works` → checks if the paper is already on their ORCID profile
4. **If found** (84% of cases) → **instant auto-verification**, no extra steps
5. **If not found** → Kurate shows: "To verify authorship, add this paper to your ORCID profile" with guidance/link to orcid.org. User adds it (~60 seconds), clicks "I've added it", backend re-checks.

**Pros:**
- **ORCID is the single source of truth** for both identity and publication ownership — no S2, no Scholar, no scraping
- Official, free, stable API with read scope already available
- No name disambiguation, no fuzzy matching, no HTML parsing
- Zero external service dependencies beyond ORCID itself
- Verification is cryptographic: ORCID OAuth proves they own the profile where the paper lives
- DOI-based matching → exact, not fuzzy title matching
- **84% of researchers already have works on ORCID** → instant verification for most users
- Encourages researchers to maintain their ORCID (benefit to the community)
- Simplest backend: one API call to check works list

**Cons:**
- ~16% of researchers have zero works on ORCID and must add the paper manually (~60 second action)
- No deep link to pre-fill ORCID's "add work" form
- arXiv preprints less likely to be auto-imported than journal papers (Crossref imports primarily DOI-registered works)

**Effort:** ~0.5-1 day. ORCID OAuth and API helpers already built. New work: works-check endpoint (~30 lines), UI guidance flow, on-demand verification trigger.

---

## Recommendation (Updated with Kurate-specific data)

**No single option is clearly dominant for Kurate's user base:**

- **Option E (ORCID-only):** Only 28% instant verification for Kurate authors (not 84%). 72% would need to manually add a paper to ORCID. Still the simplest to implement and maintain (no scraping, no disambiguation), but higher friction than initially estimated.

- **Option B (ORCID + Scholar URL):** Avoids the 72% manual-add problem since most researchers maintain Scholar profiles. But adds HTML parsing fragility and fuzzy title matching.

- **S2 path:** 95% findable by name search, but 74% ambiguous. Could work WITH a disambiguation picker showing paper counts and affiliations, but UX is clunky for common names.

**Pragmatic approach:** Implement Option E first (simplest, ~0.5 day). For the 72% who need to manually add a paper to ORCID, provide clear step-by-step guidance in the UI. Monitor the conversion rate. If too many users drop off at the "add to ORCID" step, add Option B (Scholar URL) as an alternative path.
