# Author Verification & Paper Claiming — Options Analysis
*Updated: April 6, 2026*

## Goal
Allow researchers to claim authorship of their papers on Kurate.org, proving they are who they say they are and linking their identity to their publications.

## Current Implementation Status
- **ORCID OAuth**: Fully built (backend + frontend). Proves identity via OAuth.
- **Semantic Scholar helpers**: Built — paper lookup by arXiv ID, author search, author paper list retrieval.
- **Verification pipeline**: Built — multi-signal verification with fuzzy name matching, trust levels.
- **Frontend component**: Built but orphaned (not wired to any page).
- **ORCID credentials**: Configured in production `.env`.

---

## Key API Discovery: ORCID Record Summary Exposes Verified Email Domains

As of April 2026, ORCID's **Record Summary API** (`public-record.json`) includes a `emailDomains` field containing verified institutional email domains — without exposing the full email address. This is the privacy-preserving "trust marker" ORCID launched in September 2024.

**Endpoint**: `GET https://orcid.org/{orcid_id}/public-record.json`

**Response (example):**
```json
{
  "emails": {
    "emails": null,
    "emailDomains": [
      {"value": "harvard.edu", "visibility": "PUBLIC", "createdDate": {...}},
      {"value": "dtu.dk", "visibility": "PUBLIC", "createdDate": {...}}
    ]
  }
}
```

**API availability status (April 6, 2026):**

| Endpoint | Verified domains? | Confirmed |
|---|---|---|
| `orcid.org/{id}/public-record.json` (Record Summary) | **Yes — `emailDomains` field** | Tested, working |
| `pub.orcid.org/v3.0/{id}/email` (main API v3.0) | **No** | Tested, not exposed |
| `pub.orcid.org/v3.0/{id}/person` (main API v3.0) | **No** | Tested, no domain field |
| ORCID profile web page (UI) | Yes (visual trust marker) | Documented |

The main v3.0 API was supposed to add this in "the next major version" (per ORCID's 2024 blog) but no new version has shipped. The Record Summary endpoint is the only programmatic access today.

---

## Survey 1: General ORCID Profiles (n=50)

Sample: 50 ORCID profiles from arXiv-relevant keyword searches (CS, ML, NLP, physics, economics).

| Metric | Count | % |
|---|---|---|
| Has works on ORCID | 42/50 | 84% |
| Has verified email visible | 14/50 | 28% |
| Has institutional email domain | 13/50 | 26% |

**Note:** This sample is biased toward established researchers. See Survey 2 for Kurate-specific data.

---

## Survey 2: Kurate Leaderboard Authors (n=40)

Sample: First authors of actual papers on Kurate's leaderboard (cs.RO, cs.CR, cs.DC, cs.SI, astro-ph.CO, quant-ph).

| Metric | Count | % |
|---|---|---|
| Has ORCID profile | 32/40 | 80% |
| ORCID with any works | 11/40 | 28% |
| Has auto-imported works | 10/40 | 25% |
| Has institutional email (old method, full email public) | 4/40 | 10% |

---

## Survey 3: Recent Kurate Preprints — Paper Coverage (n=50)

Sample: 50 most recent papers on Kurate, published 2026-03-15 to 2026-04-03.

| Source | Paper found? | Note |
|---|---|---|
| **Google Scholar** | **48/50 (96%)** | Near-instant arXiv indexing |
| Semantic Scholar | 14/50 (28%) | Days/weeks lag for arXiv preprints |
| First author's ORCID works | 1/50 (2%) | Preprints rarely auto-imported |

---

## Survey 4: ORCID Trust Signals — Full Category Scan (n=140)

Sample: 10 first authors from each of Kurate's 14 active categories. Checked via the Record Summary API (`public-record.json`) for verified email domains, and the main API for affiliations.

| Signal | Count | % | Trust strength |
|---|---|---|---|
| Has ORCID profile | 128/140 | **91%** | Identity proof (via OAuth) |
| **Verified email domain (public, via Record Summary)** | **34/140** | **24%** | **Strong — institution verified by ORCID** |
| Public full email address | 8/140 | 6% | Strong but rare |
| Institution-asserted affiliation | 5/140 | 4% | Strongest (institution pushed via Member API) |
| Self-declared affiliation | 47/140 | 34% | Weak (anyone can type anything) |
| Any public affiliation | 50/140 | 36% | Available for context |

### By category (verified email domain via Record Summary):
| Category | n | ORCID | Domain | Email | Inst-asserted |
|---|---|---|---|---|---|
| physics.comp-ph | 10 | 10 | 5 | 1 | 0 |
| astro-ph.CO | 10 | 9 | 4 | 2 | 1 |
| cs.DC | 10 | 9 | 4 | 0 | 0 |
| q-bio.BM | 10 | 7 | 3 | 2 | 0 |
| quant-ph | 10 | 8 | 3 | 0 | 0 |
| physics.chem-ph | 10 | 10 | 3 | 1 | 0 |
| cs.RO | 10 | 10 | 2 | 0 | 0 |
| cs.CR | 10 | 9 | 2 | 0 | 0 |
| chemrxiv.IC | 10 | 10 | 2 | 0 | 1 |
| cs.SI | 10 | 9 | 2 | 0 | 0 |
| cond-mat.mtrl-sci | 10 | 9 | 1 | 1 | 1 |
| cs.GT | 10 | 9 | 1 | 0 | 1 |
| cs.IT | 10 | 10 | 1 | 1 | 1 |
| econ.GN | 10 | 9 | 1 | 0 | 0 |
| **TOTAL** | **140** | **128 (91%)** | **34 (24%)** | **8 (6%)** | **5 (4%)** |

Sample verified domains found: harvard.edu, mit.edu, berkeley.edu, caltech.edu, ethz.ch, cambridge, oxford, fu-berlin.de, kyushu-u.ac.jp, upenn.edu, etc.

### Key insight: 24% vs 9%
Previous analysis using only the main v3.0 `/email` endpoint found 9% with institutional signals. The Record Summary API's `emailDomains` field reveals **24%** — nearly 3x more. These researchers made their domain public (privacy-preserving) without exposing their full email address.

---

## Semantic Scholar Coverage (Empirical Data)

### S2 ORCID Mapping
- Celebrity researcher test (n=15): 1/15 (7%) had ORCID on S2
- Broad sample (n=50): 0/50 (0%) via direct `ORCID:xxx` lookup
- Kurate authors (n=140): 0/128 (0%) via name search cross-check
- **Verdict: S2 ORCID mapping is completely unusable**

### S2 Name Search
- 95% of Kurate authors findable by name
- But 74% of results are ambiguous (2+ candidates)
- Only 26% unambiguous (1 result)

### S2 Paper Indexing
- Only 28% of recent Kurate preprints indexed on S2
- arXiv preprints take days/weeks to appear

---

## Option A: ORCID + S2 Name Search

**Flow:** ORCID OAuth → S2 name search → user picks profile → fetch papers → cross-reference

**Pros:** S2 has real API, free
**Cons:** 74% ambiguous name results, only 28% of recent papers indexed
**Effort:** ~1 day

---

## Option B: ORCID + Google Scholar URL

**Flow:** ORCID OAuth → user pastes Scholar URL → fetch public profile page → extract papers → cross-reference

**Pros:** 96% of papers on Scholar, no disambiguation, ORCID domain match for trust
**Cons:** No Scholar API (HTML parsing), fragile to page changes, fuzzy title matching
**Effort:** ~1-2 days

---

## Option C: Google Scholar URL + Email Verification Code (alphaXiv's approach)

**Flow:** User pastes Scholar URL → scrape profile → extract "Verified email at" domain → send code → verify

**Pros:** Proven flow (alphaXiv uses it)
**Cons:** Same scraping fragility, needs email-sending infra (Resend), more user steps, no ORCID identity
**Effort:** ~2-3 days

---

## Option E: ORCID as Both Identity AND Verification

**Flow:**
1. User connects ORCID (OAuth) → proves identity
2. Backend checks Record Summary for verified email domain → **24% get instant institutional verification**
3. User selects a paper on Kurate to claim
4. Backend checks ORCID works for this paper → **2% get instant paper verification** (Crossref auto-import)
5. If not found → "Add this paper to your ORCID profile" (~60 sec) → re-check

**Pros:**
- Zero fragile dependencies (no scraping, no S2)
- Record Summary API gives institutional trust for 24% instantly
- ORCID is single source of truth for identity + publication
- Simplest backend (~30 lines new code)

**Cons:**
- 98% of recent preprints need manual ORCID add (~60 sec per paper)
- No deep link to pre-fill ORCID's "add work" form

**Effort:** ~0.5-1 day

---

## Recommendation

**For institutional trust signal:** Use the ORCID Record Summary API (`public-record.json` → `emailDomains`). Available today, gives 24% instant verification, privacy-preserving. For the other 76%, the ask is "make your institutional email domain public on ORCID" (~30 seconds, email stays private). As ORCID continues prompting users, this percentage will grow.

**For paper claiming:** No option avoids a manual step for 98% of recent preprints:
- Option E asks "add paper to ORCID" (~60 sec) — simplest, zero dependencies
- Option B asks "paste Scholar URL" (~15 sec) — lower friction but adds scraping fragility

**Pragmatic path:**
1. **Start with Option E** (simplest): ORCID OAuth → check Record Summary for domain trust marker → check works for paper → if not found, guide user to add it
2. **If conversion drops off at "add to ORCID" step**, add Option B (Scholar URL) as an alternative
3. **Watch for ORCID main API update** — when v3.0 `/person` or `/email` exposes domains, the Record Summary workaround becomes unnecessary

Both options share the ORCID identity + institutional trust layer. The paper verification is the only difference.
