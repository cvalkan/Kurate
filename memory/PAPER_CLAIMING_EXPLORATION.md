# Paper Claiming via ORCID + Semantic Scholar — Technical Exploration

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
│   Frontend   │────▶│  Backend API │────▶│  External APIs     │
│  "Claim"     │     │  /api/claim  │     │  - ORCID OAuth     │
│   button     │     │  /api/verify │     │  - ORCID Public    │
└─────────────┘     └──────────────┘     │  - Semantic Scholar│
                                          │  - arXiv OAI-PMH   │
                                          └───────────────────┘
```

## External API Capabilities (Verified)

### 1. ORCID
- **OAuth 2.0 / OpenID Connect**: Standard flow, endpoints confirmed at `orcid.org/.well-known/openid-configuration`
  - Authorization: `https://orcid.org/oauth/authorize`
  - Token: `https://orcid.org/oauth/token`
  - Userinfo: `https://orcid.org/oauth/userinfo`
- **Public API** (`pub.orcid.org/v3.0`): Requires client credentials token (not anonymous)
  - `/v3.0/{orcid}/record` → full profile (name, affiliations, works)
  - `/v3.0/{orcid}/works` → publication list with external IDs (DOI, arXiv ID)
- **Registration**: Free at `orcid.org/developer-tools` → Client ID + Secret
- **Scopes**: `/read-public` (sufficient for verification), `/authenticate` (for OAuth sign-in)
- **Rate limits**: Daily quotas on public API since Feb 2025; Member API unaffected

### 2. Semantic Scholar (Verified Working)
- **Author search**: `GET /graph/v1/author/search?query=Name&fields=authorId,name,externalIds`
  - Returns disambiguated author entities with S2 ID, DBLP IDs, sometimes ORCID
  - Tested: returns correct results for "Yann LeCun", "Yoshua Bengio"
- **Author by ID**: `GET /graph/v1/author/{authorId}?fields=name,externalIds,paperCount`
- **Author papers**: `GET /graph/v1/author/{authorId}/papers?fields=title,externalIds`
  - Returns all papers with arXiv IDs, DOIs
- **Paper by arXiv ID**: `GET /graph/v1/paper/arXiv:{arxiv_id}?fields=title,authors.authorId,authors.externalIds`
  - Returns paper with disambiguated author list (each has S2 author ID)
- **Rate limit**: 100 req/s with free API key, 1 req/s without
- **Coverage**: ~80-90% of active CS/ML researchers have disambiguated profiles

### 3. arXiv
- Papers in our DB already have `arxiv_id` field
- arXiv OAI-PMH includes ORCID when authors link it (growing but ~30-40%)
- No OAuth for third parties

## Verification Signal Priority

```
Signal 1: ORCID → S2 bridge (strongest, most coverage)
  User authenticates ORCID → get ORCID ID
  → S2 search by ORCID externalId or name → get S2 author ID
  → S2 author papers → check if target arxiv_id in list
  Confidence: HIGH, Coverage: ~80%

Signal 2: ORCID works list (strong, varies)
  User authenticates ORCID → get ORCID ID
  → ORCID API /works → check if target arxiv_id or DOI in works
  Confidence: HIGH, Coverage: ~50-60% (depends on author maintaining profile)

Signal 3: S2 paper → author list (reverse lookup)
  Look up our paper on S2 by arxiv_id → get S2 author IDs
  → Check if user's ORCID-linked S2 ID is in the author list
  Confidence: HIGH, Coverage: ~80%

Signal 4: Name + affiliation fuzzy match (fallback)
  ORCID profile name vs paper author list
  + ORCID affiliation vs paper metadata
  Confidence: MEDIUM (provisionally verified, flagged for review)

Signal 5: Manual claim
  User provides proof, admin reviews within 24-48h
```

## Proposed Data Model

```python
# New collection: author_verifications
{
    "user_id": "google-oauth-id",           # Existing auth
    "orcid_id": "0000-0002-1234-5678",      # From ORCID OAuth
    "orcid_name": "Jane Smith",
    "orcid_affiliations": ["MIT", "Stanford"],
    "semantic_scholar_id": "12345678",       # Cached S2 author ID
    "verified_papers": [
        {
            "paper_id": "uuid-in-our-db",
            "arxiv_id": "2602.12215",
            "method": "semantic_scholar",    # orcid_works | semantic_scholar | name_match | manual
            "verified_at": "2026-03-12T...",
            "confidence": 1.0,              # 1.0 = auto-verified, 0.8 = provisional
        }
    ],
    "orcid_token": "encrypted-refresh-token", # For re-verification
    "cached_s2_papers": ["arxiv:...", ...],    # Cached S2 paper list
    "cache_refreshed_at": "2026-03-12T...",
    "created_at": "2026-03-12T..."
}

# Addition to papers collection
{
    "claimed_by": [
        {
            "orcid_id": "0000-0002-1234-5678",
            "author_name": "Jane Smith",
            "verified": true,
            "method": "semantic_scholar",
            "claimed_at": "2026-03-12T..."
        }
    ]
}
```

## Backend API Endpoints

```
POST /api/auth/orcid/callback
  - Handles ORCID OAuth callback
  - Stores ORCID ID + tokens
  - Triggers background verification of all claimable papers

GET /api/claim/eligible
  - Returns papers the authenticated user can claim
  - Uses cached S2 paper list + ORCID works

POST /api/claim/{paper_id}
  - Claims a specific paper
  - Runs verification pipeline
  - Returns: verified | provisional | manual_required

GET /api/claim/status/{paper_id}
  - Check claim status for a paper

GET /api/papers/{paper_id}/claims
  - Public: show verified authors for a paper
```

## Verification Flow (Pseudocode)

```
VERIFY_AUTHORSHIP(user_orcid, paper_arxiv_id):

  # Signal 1: S2 paper reverse lookup (fastest, single API call)
  s2_paper = S2_API.get_paper(arxiv_id, fields="authors.authorId,authors.externalIds")
  IF s2_paper:
    FOR author IN s2_paper.authors:
      IF author.externalIds.ORCID == user_orcid:
        RETURN VERIFIED(method="s2_direct_orcid")
  
  # Signal 2: S2 author → paper list
  s2_author = CACHED_S2_AUTHOR(user_orcid)
  IF NOT s2_author:
    # Search S2 by ORCID external ID or by name from ORCID profile
    s2_author = S2_API.search_author(orcid=user_orcid) 
                OR S2_API.search_author(name=orcid_profile_name)
    CACHE s2_author
  IF s2_author:
    s2_papers = S2_API.get_author_papers(s2_author.id)
    IF paper_arxiv_id IN s2_papers.externalIds:
      RETURN VERIFIED(method="semantic_scholar")

  # Signal 3: ORCID works list
  orcid_works = ORCID_API.get_works(user_orcid)
  IF paper_arxiv_id IN orcid_works.external_ids 
     OR paper_doi IN orcid_works.external_ids:
    RETURN VERIFIED(method="orcid_works")

  # Signal 4: Fuzzy name + affiliation match
  orcid_name = ORCID_API.get_name(user_orcid)
  paper_authors = DB.papers.get(arxiv_id).authors
  best_match = fuzzy_match(orcid_name, paper_authors)  # >0.85 threshold
  IF best_match AND affiliation_matches(orcid_affiliations, paper_metadata):
    RETURN PROVISIONAL(method="name_affiliation", confidence=0.8)

  # Signal 5: Manual claim
  RETURN MANUAL_REQUIRED(reason="no_auto_match")
```

## Implementation Plan

### Phase 1: ORCID OAuth + Basic Claiming (MVP)
1. Register ORCID app (free, Public API)
2. Add ORCID OAuth flow alongside existing Google Auth
3. Create `author_verifications` collection
4. Implement S2 paper reverse lookup (Signal 1 — single API call, highest ROI)
5. Add "Claim" button on paper pages for authenticated users
6. Display verified author badges on papers

### Phase 2: Full Verification Pipeline
7. Add ORCID works lookup (Signal 2)
8. Add S2 author paper list lookup (Signal 3)
9. Cache S2 author ID → paper list (refresh weekly)
10. Add "eligible papers" endpoint for batch claiming

### Phase 3: Fallbacks + Polish
11. Fuzzy name matching (rapidfuzz library)
12. Manual claim flow with admin review queue
13. Author profile pages showing all claimed papers
14. Badge notifications (email on new badge eligibility)

## Dependencies
- `requests` (already installed) — for S2/ORCID API calls
- Semantic Scholar free API key (apply at semanticscholar.org)
- ORCID Client ID + Secret (register at orcid.org/developer-tools)
- `rapidfuzz` — for name matching in Phase 3 (pip install rapidfuzz)

## Cost
- ORCID Public API: Free
- Semantic Scholar API: Free (100 req/s with key)
- Total external cost: $0
