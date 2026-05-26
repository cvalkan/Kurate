"""Author paper claiming via ORCID + Semantic Scholar verification."""

import os
import re
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Query, Depends
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger
from routers.validation_utils import collect_all
from core.auth import verify_admin

router = APIRouter(prefix="/api/claim")

ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")
ORCID_REDIRECT_URI = os.environ.get("ORCID_REDIRECT_URI", "")
S2_API_KEY = os.environ.get("S2_API_KEY", "")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
ORCID_BASE = "https://orcid.org"
ORCID_PUB_API = "https://pub.orcid.org/v3.0"


# --- Helpers ---

async def _get_current_user(request: Request) -> Optional[dict]:
    """Extract user from session (reuse auth module logic)."""
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


async def _fetch_orcid_verification(orcid_id: str) -> dict:
    """Fetch ORCID verification status: verified-email flag + public email domains."""
    result = {"verified_email": False, "verified_primary_email": False, "email_domains": [], "claimed": False}

    # 1. Public API: get history flags (needs client credentials token)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get client credentials token
            token_res = await client.post(
                f"{ORCID_BASE}/oauth/token",
                data={
                    "client_id": ORCID_CLIENT_ID,
                    "client_secret": ORCID_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                    "scope": "/read-public",
                },
                headers={"Accept": "application/json"},
            )
            if token_res.status_code == 200:
                access_token = token_res.json().get("access_token")
                # Fetch record with history
                rec_res = await client.get(
                    f"{ORCID_PUB_API}/{orcid_id}/record",
                    headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
                )
                if rec_res.status_code == 200:
                    data = rec_res.json()
                    history = data.get("history") or {}
                    result["verified_email"] = history.get("verified-email", False)
                    result["verified_primary_email"] = history.get("verified-primary-email", False)
                    result["claimed"] = history.get("claimed", False)
    except Exception as e:
        logger.warning(f"ORCID public API check failed: {e}")

    # 2. Public record JSON: get email domains (if user set visibility to PUBLIC)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            pr_res = await client.get(
                f"{ORCID_BASE}/{orcid_id}/public-record.json",
                headers={"Accept": "application/json"},
            )
            if pr_res.status_code == 200:
                pr_data = pr_res.json()
                email_domains = (pr_data.get("emails") or {}).get("emailDomains") or []
                for d in email_domains:
                    if d.get("visibility") == "PUBLIC" and d.get("value"):
                        result["email_domains"].append(d["value"])
    except Exception as e:
        logger.warning(f"ORCID public-record.json check failed: {e}")

    return result


def _s2_headers():
    h = {"Accept": "application/json"}
    if S2_API_KEY:
        h["x-api-key"] = S2_API_KEY
    return h


async def _s2_lookup_paper(arxiv_id: str) -> Optional[dict]:
    """Look up a paper on Semantic Scholar by arXiv ID. Returns authors with externalIds."""
    url = f"{S2_BASE}/paper/arXiv:{arxiv_id}"
    params = {"fields": "title,authors.authorId,authors.name,authors.externalIds"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=_s2_headers(), params=params)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"S2 paper lookup failed ({r.status_code}): {arxiv_id}")
    except Exception as e:
        logger.warning(f"S2 paper lookup error: {e}")
    return None


async def _s2_search_author_by_orcid(orcid_id: str) -> Optional[dict]:
    """Search for an author on S2 by ORCID external ID."""
    url = f"{S2_BASE}/author/search"
    params = {"query": orcid_id, "fields": "authorId,name,externalIds,paperCount"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=_s2_headers(), params=params)
            if r.status_code == 200:
                data = r.json()
                for author in data.get("data", []):
                    ext = author.get("externalIds") or {}
                    if ext.get("ORCID") == orcid_id:
                        return author
    except Exception as e:
        logger.warning(f"S2 author search error: {e}")
    return None


async def _s2_get_author_papers(s2_author_id: str, limit: int = 500) -> list:
    """Get all papers for an S2 author."""
    url = f"{S2_BASE}/author/{s2_author_id}/papers"
    params = {"fields": "externalIds,title", "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=_s2_headers(), params=params)
            if r.status_code == 200:
                return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"S2 author papers error: {e}")
    return []


FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "protonmail.com", "proton.me", "icloud.com", "mail.com", "aol.com",
    "zoho.com", "yandex.com", "gmx.com", "gmx.net", "tutanota.com",
    "fastmail.com", "mailinator.com", "guerrillamail.com",
}


def _compute_trust_level(verified_email: bool, email_domains: list) -> dict:
    """Compute email trust level and label for admin display."""
    has_public_domain = len(email_domains) > 0
    is_institutional = has_public_domain and all(d.lower() not in FREE_EMAIL_DOMAINS for d in email_domains)
    domain_str = ", ".join(email_domains) if email_domains else None

    if verified_email and is_institutional:
        return {"level": "high", "color": "green", "label": f"verified · {domain_str}"}
    if verified_email and has_public_domain and not is_institutional:
        return {"level": "medium", "color": "amber", "label": f"verified · {domain_str}"}
    if verified_email and not has_public_domain:
        return {"level": "medium", "color": "amber", "label": "verified · domain hidden"}
    return {"level": "low", "color": "red", "label": "unverified email"}


async def _verify_authorship(orcid_id: str, arxiv_id: str, orcid_name: str = "",
                             orcid_verified_email: bool = False,
                             orcid_email_domains: list = None) -> dict:
    """Run verification pipeline. Only S2 ORCID-linked signals auto-verify.
    Name matches are never auto-verified — they provide trust context for admin review."""

    if orcid_email_domains is None:
        orcid_email_domains = []

    name_match_result = None

    # Signal 1: S2 paper reverse lookup — ORCID linked on S2 (auto-verify)
    s2_paper = await _s2_lookup_paper(arxiv_id)
    if s2_paper:
        for author in s2_paper.get("authors", []):
            ext = author.get("externalIds") or {}
            if ext.get("ORCID") == orcid_id:
                return {
                    "verified": True,
                    "method": "s2_direct_orcid",
                    "confidence": 1.0,
                    "s2_author_id": author.get("authorId"),
                    "matched_name": author.get("name"),
                }

        # Check name match on S2 author list (for admin context only)
        if orcid_name and s2_paper.get("authors"):
            match = _fuzzy_name_match(orcid_name, [a.get("name", "") for a in s2_paper["authors"]])
            if match:
                name_match_result = {"method": "s2_name_match", "matched_name": s2_paper["authors"][match["index"]].get("name"), "score": match["score"]}

    # Signal 3: S2 author search by ORCID → paper list (auto-verify)
    s2_author = await _s2_search_author_by_orcid(orcid_id)
    if s2_author:
        papers = await _s2_get_author_papers(s2_author["authorId"])
        for p in papers:
            ext = p.get("externalIds") or {}
            if ext.get("ArXiv") == arxiv_id or ext.get("ArXiv") == arxiv_id.split("v")[0]:
                return {
                    "verified": True,
                    "method": "s2_author_papers",
                    "confidence": 1.0,
                    "s2_author_id": s2_author["authorId"],
                    "matched_name": s2_author.get("name"),
                }

    # Check name match on DB author list (for admin context only)
    if orcid_name and not name_match_result:
        paper_doc = await db.papers.find_one(
            {"arxiv_id": {"$regex": f"^{re.escape(arxiv_id)}"}},
            {"_id": 0, "authors": 1},
        )
        if paper_doc and paper_doc.get("authors"):
            match = _fuzzy_name_match(orcid_name, paper_doc["authors"])
            if match:
                name_match_result = {"method": "db_name_match", "matched_name": paper_doc["authors"][match["index"]], "score": match["score"]}

    # Compute trust level for admin (email-based only)
    trust = _compute_trust_level(
        verified_email=orcid_verified_email,
        email_domains=orcid_email_domains,
    )

    return {
        "verified": False,
        "method": name_match_result["method"] if name_match_result else "no_match",
        "confidence": 0.0,
        "name_match": name_match_result,
        "trust": trust,
    }


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip accents, collapse whitespace."""
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return " ".join(name.lower().split())


def _fuzzy_name_match(orcid_name: str, author_names: list, threshold: float = 0.85) -> dict | None:
    """Match ORCID profile name against a list of author names.
    
    Handles: first/last order variations, initials, unicode.
    Returns {index, score} or None.
    """
    norm_orcid = _normalize_name(orcid_name)
    orcid_parts = set(norm_orcid.split())

    best_score = 0.0
    best_idx = -1

    for i, author_name in enumerate(author_names):
        if not author_name:
            continue
        norm_author = _normalize_name(author_name)
        author_parts = set(norm_author.split())

        # Exact match
        if norm_orcid == norm_author:
            return {"index": i, "score": 1.0}

        # Check if last names match and first name/initial matches
        # Try both orderings (First Last vs Last First)
        orcid_list = norm_orcid.split()
        author_list = norm_author.split()

        if len(orcid_list) >= 2 and len(author_list) >= 2:
            # Check last name match
            if orcid_list[-1] == author_list[-1]:
                # Check first name or initial
                o_first = orcid_list[0]
                a_first = author_list[0]
                if o_first == a_first or o_first[0] == a_first[0]:
                    score = 0.95 if o_first == a_first else 0.90
                    if score > best_score:
                        best_score = score
                        best_idx = i

            # Reversed order: author is "Last, First"
            if orcid_list[-1] == author_list[0].rstrip(","):
                o_first = orcid_list[0]
                a_first = author_list[-1]
                if o_first == a_first or o_first[0] == a_first[0]:
                    score = 0.95 if o_first == a_first else 0.90
                    if score > best_score:
                        best_score = score
                        best_idx = i

        # Token overlap (handles middle names, suffixes)
        if len(orcid_parts) >= 2 and len(author_parts) >= 2:
            overlap = len(orcid_parts & author_parts)
            total = max(len(orcid_parts), len(author_parts))
            token_score = overlap / total
            if token_score > best_score and token_score >= 0.65:
                best_score = token_score
                best_idx = i

    if best_score >= threshold and best_idx >= 0:
        return {"index": best_idx, "score": round(best_score, 2)}
    return None


# --- ORCID OAuth ---

class OrcidCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


@router.get("/orcid/auth-url")
async def get_orcid_auth_url(redirect_uri: str = Query(...)):
    """Return the ORCID OAuth authorization URL."""
    if not ORCID_CLIENT_ID:
        raise HTTPException(503, "ORCID integration not configured")
    url = (
        f"{ORCID_BASE}/oauth/authorize"
        f"?client_id={ORCID_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=/authenticate"
        f"&redirect_uri={redirect_uri}"
    )
    return {"url": url}


@router.post("/orcid/connect")
async def connect_orcid(body: OrcidCallbackRequest, request: Request):
    """Exchange ORCID OAuth code for ORCID ID and link to user account."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    if not ORCID_CLIENT_ID or not ORCID_CLIENT_SECRET:
        raise HTTPException(503, "ORCID integration not configured")

    # Exchange code for access token + ORCID ID
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{ORCID_BASE}/oauth/token",
            data={
                "client_id": ORCID_CLIENT_ID,
                "client_secret": ORCID_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": body.code,
                "redirect_uri": body.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            logger.warning(f"ORCID token exchange failed: {r.status_code} {r.text}")
            raise HTTPException(400, "Failed to verify ORCID authorization")
        token_data = r.json()

    orcid_id = token_data.get("orcid")
    orcid_name = token_data.get("name")
    if not orcid_id:
        raise HTTPException(400, "No ORCID ID returned")

    # Upsert author_verifications record
    # Fetch ORCID verification status (verified email, public email domains)
    orcid_verification = await _fetch_orcid_verification(orcid_id)

    await db.author_verifications.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "orcid_id": orcid_id,
                "orcid_name": orcid_name or user.get("name", ""),
                "orcid_connected_at": datetime.now(timezone.utc).isoformat(),
                "orcid_verified_email": orcid_verification["verified_email"],
                "orcid_email_domains": orcid_verification["email_domains"],
                "orcid_claimed": orcid_verification["claimed"],
            },
            "$setOnInsert": {
                "user_id": user["user_id"],
                "verified_papers": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        },
        upsert=True,
    )

    # Also store orcid_id on the user record for quick access
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"orcid_id": orcid_id}},
    )

    logger.info(f"ORCID connected: user={user['user_id']} orcid={orcid_id} verified_email={orcid_verification['verified_email']} domains={orcid_verification['email_domains']}")
    return {"status": "ok", "orcid_id": orcid_id, "orcid_name": orcid_name}


# --- Claiming ---

@router.get("/my-orcid")
async def get_my_orcid(request: Request):
    """Get current user's ORCID connection status."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    verification = await db.author_verifications.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    )
    if not verification or not verification.get("orcid_id"):
        return {"connected": False}

    return {
        "connected": True,
        "orcid_id": verification["orcid_id"],
        "orcid_name": verification.get("orcid_name"),
        "verified_count": len(verification.get("verified_papers", [])),
    }


@router.get("/my-claims")
async def get_my_claims(request: Request):
    """Get all papers claimed by the current user."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    verification = await db.author_verifications.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    )
    if not verification:
        return {"claims": []}

    return {"claims": verification.get("verified_papers", []), "orcid_id": verification.get("orcid_id")}


@router.post("/{paper_id}")
async def claim_paper(paper_id: str, request: Request):
    """Claim authorship of a paper. Runs verification pipeline."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    # Check ORCID is connected
    verification = await db.author_verifications.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    )
    if not verification or not verification.get("orcid_id"):
        raise HTTPException(400, "Please connect your ORCID first")

    orcid_id = verification["orcid_id"]

    # Check paper exists
    paper = await db.papers.find_one({"id": paper_id}, {"_id": 0, "id": 1, "arxiv_id": 1, "title": 1, "authors": 1, "claimed_by": 1})
    if not paper:
        raise HTTPException(404, "Paper not found")

    arxiv_id = paper.get("arxiv_id", "").replace("v1", "").replace("v2", "").replace("v3", "")
    if not arxiv_id:
        raise HTTPException(400, "Paper has no arXiv ID — cannot verify")

    # Check not already claimed by this user
    existing_claims = paper.get("claimed_by", [])
    if any(c.get("orcid_id") == orcid_id for c in existing_claims):
        return {"status": "already_claimed", "method": "existing"}

    # Run verification
    orcid_name = verification.get("orcid_name", user.get("name", ""))
    orcid_verified_email = verification.get("orcid_verified_email", False)
    orcid_email_domains = verification.get("orcid_email_domains", [])
    result = await _verify_authorship(orcid_id, arxiv_id, orcid_name, orcid_verified_email, orcid_email_domains)

    claim_record = {
        "orcid_id": orcid_id,
        "user_id": user["user_id"],
        "author_name": verification.get("orcid_name", user.get("name", "")),
        "verified": result["verified"],
        "method": result["method"],
        "confidence": result["confidence"],
        "orcid_verified_email": orcid_verified_email,
        "orcid_email_domains": orcid_email_domains,
        "name_match": result.get("name_match"),
        "trust": result.get("trust"),
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }

    if result["verified"]:
        # Add claim to paper
        await db.papers.update_one(
            {"id": paper_id},
            {"$push": {"claimed_by": claim_record}},
        )
        # Add to user's verified papers
        await db.author_verifications.update_one(
            {"user_id": user["user_id"]},
            {"$push": {"verified_papers": {
                "paper_id": paper_id,
                "arxiv_id": paper.get("arxiv_id"),
                "title": paper.get("title", ""),
                "method": result["method"],
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "confidence": result["confidence"],
            }}},
        )
        logger.info(f"Paper claimed: user={user['user_id']} paper={paper_id} method={result['method']}")
        return {"status": "verified", "method": result["method"], "matched_name": result.get("matched_name")}
    else:
        # Store as pending/manual
        claim_record["status"] = "pending"
        await db.papers.update_one(
            {"id": paper_id},
            {"$push": {"claimed_by": claim_record}},
        )
        logger.info(f"Paper claim pending: user={user['user_id']} paper={paper_id}")
        return {"status": "pending", "message": "Could not automatically verify. Claim submitted for admin review."}


@router.get("/paper/{paper_id}")
async def get_paper_claims(paper_id: str):
    """Public: Get verified author claims for a paper."""
    paper = await db.papers.find_one(
        {"id": paper_id}, {"_id": 0, "claimed_by": 1}
    )
    if not paper:
        return {"claims": []}

    claims = paper.get("claimed_by", [])
    # Only return verified claims publicly
    public_claims = [
        {
            "author_name": c.get("author_name"),
            "orcid_id": c.get("orcid_id"),
            "verified": c.get("verified", False),
            "method": c.get("method"),
            "claimed_at": c.get("claimed_at"),
        }
        for c in claims
        if c.get("verified")
    ]
    return {"claims": public_claims}


# --- Admin endpoints for claim review ---

@router.get("/admin/pending", dependencies=[Depends(verify_admin)])
async def list_pending_claims():
    """Admin: list all papers with pending (unverified) claims."""
    papers = await db.papers.find(
        {"claimed_by": {"$elemMatch": {"verified": False}}},
        {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1, "claimed_by": 1},
    ).to_list(500)

    pending = []
    # Collect user_ids to batch-fetch emails
    user_ids = set()
    for p in papers:
        for c in p.get("claimed_by", []):
            if not c.get("verified") and c.get("user_id"):
                user_ids.add(c["user_id"])
    # Fetch emails
    email_map = {}
    if user_ids:
        users = await db.users.find({"user_id": {"$in": list(user_ids)}}, {"_id": 0, "user_id": 1, "email": 1}).to_list(500)
        email_map = {u["user_id"]: u.get("email", "") for u in users}

    for p in papers:
        for c in p.get("claimed_by", []):
            if not c.get("verified"):
                pending.append({
                    "paper_id": p["id"],
                    "paper_title": p.get("title", ""),
                    "paper_authors": p.get("authors", []),
                    "arxiv_id": p.get("arxiv_id", ""),
                    "claimer_name": c.get("author_name"),
                    "claimer_email": email_map.get(c.get("user_id"), ""),
                    "claimer_orcid": c.get("orcid_id"),
                    "trust": c.get("trust", {}),
                    "name_match": c.get("name_match"),
                    "claimed_at": c.get("claimed_at"),
                })
    return {"pending": pending}


@router.post("/admin/approve/{paper_id}/{orcid_id}", dependencies=[Depends(verify_admin)])
async def approve_claim(paper_id: str, orcid_id: str):
    """Admin: approve a pending claim."""
    # Update the claim to verified
    result = await db.papers.update_one(
        {"id": paper_id, "claimed_by.orcid_id": orcid_id, "claimed_by.verified": False},
        {"$set": {
            "claimed_by.$.verified": True,
            "claimed_by.$.method": "admin_approved",
            "claimed_by.$.confidence": 1.0,
        }},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Pending claim not found")

    # Also add to user's verified papers
    claim_doc = await db.papers.find_one({"id": paper_id}, {"_id": 0, "title": 1, "arxiv_id": 1, "claimed_by": 1})
    if claim_doc:
        for c in claim_doc.get("claimed_by", []):
            if c.get("orcid_id") == orcid_id:
                await db.author_verifications.update_one(
                    {"orcid_id": orcid_id},
                    {"$push": {"verified_papers": {
                        "paper_id": paper_id,
                        "arxiv_id": claim_doc.get("arxiv_id"),
                        "title": claim_doc.get("title", ""),
                        "method": "admin_approved",
                        "verified_at": datetime.now(timezone.utc).isoformat(),
                        "confidence": 1.0,
                    }}},
                )
                break

    logger.info(f"Claim approved by admin: paper={paper_id} orcid={orcid_id}")
    return {"status": "approved"}


@router.post("/admin/reject/{paper_id}/{orcid_id}", dependencies=[Depends(verify_admin)])
async def reject_claim(paper_id: str, orcid_id: str):
    """Admin: reject and remove a pending claim."""
    result = await db.papers.update_one(
        {"id": paper_id},
        {"$pull": {"claimed_by": {"orcid_id": orcid_id, "verified": False}}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Pending claim not found")

    logger.info(f"Claim rejected by admin: paper={paper_id} orcid={orcid_id}")
    return {"status": "rejected"}


@router.get("/admin/verified", dependencies=[Depends(verify_admin)])
async def list_verified_claims():
    """Admin: list all verified (accepted) claims."""
    papers = await collect_all(db.papers.find(
        {"claimed_by": {"$elemMatch": {"verified": True}}},
        {"_id": 0, "id": 1, "title": 1, "authors": 1, "arxiv_id": 1, "claimed_by": 1},
    ))

    user_ids = set()
    for p in papers:
        for c in p.get("claimed_by", []):
            if c.get("verified") and c.get("user_id"):
                user_ids.add(c["user_id"])
    email_map = {}
    if user_ids:
        users = await db.users.find({"user_id": {"$in": list(user_ids)}}, {"_id": 0, "user_id": 1, "email": 1}).to_list(500)
        email_map = {u["user_id"]: u.get("email", "") for u in users}

    verified = []
    for p in papers:
        for c in p.get("claimed_by", []):
            if c.get("verified"):
                verified.append({
                    "paper_id": p["id"],
                    "paper_title": p.get("title", ""),
                    "arxiv_id": p.get("arxiv_id", ""),
                    "claimer_name": c.get("author_name"),
                    "claimer_email": email_map.get(c.get("user_id"), ""),
                    "claimer_orcid": c.get("orcid_id"),
                    "method": c.get("method", ""),
                    "claimed_at": c.get("claimed_at"),
                })
    return {"verified": verified}


@router.post("/admin/revoke/{paper_id}/{orcid_id}", dependencies=[Depends(verify_admin)])
async def revoke_claim(paper_id: str, orcid_id: str):
    """Admin: revoke a verified claim (remove badge)."""
    result = await db.papers.update_one(
        {"id": paper_id},
        {"$pull": {"claimed_by": {"orcid_id": orcid_id, "verified": True}}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Verified claim not found")

    # Also remove from user's verified papers
    await db.author_verifications.update_one(
        {"orcid_id": orcid_id},
        {"$pull": {"verified_papers": {"paper_id": paper_id}}},
    )

    logger.info(f"Claim revoked by admin: paper={paper_id} orcid={orcid_id}")
    return {"status": "revoked"}


# --- Admin ORCID verification (independent of paper claiming) ---

@router.get("/admin/orcid-verifications", dependencies=[Depends(verify_admin)])
async def list_orcid_verifications():
    """Admin: list all users who have linked their ORCID."""
    verifications = await db.author_verifications.find(
        {"orcid_id": {"$exists": True, "$ne": None}},
        {"_id": 0},
    ).to_list(500)

    # Fetch user emails
    user_ids = [v["user_id"] for v in verifications]
    users = await db.users.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "provider": 1},
    ).to_list(500)
    user_map = {u["user_id"]: u for u in users}

    result = []
    for v in verifications:
        u = user_map.get(v["user_id"], {})
        result.append({
            "user_id": v["user_id"],
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "provider": u.get("provider", ""),
            "orcid_id": v["orcid_id"],
            "orcid_name": v.get("orcid_name", ""),
            "orcid_verified_email": v.get("orcid_verified_email", False),
            "orcid_email_domains": v.get("orcid_email_domains", []),
            "orcid_connected_at": v.get("orcid_connected_at", ""),
            "admin_verified": v.get("admin_verified", False),
        })
    return {"verifications": result}


@router.post("/admin/orcid-verify/{user_id}", dependencies=[Depends(verify_admin)])
async def admin_verify_orcid(user_id: str):
    """Admin: approve an ORCID verification."""
    result = await db.author_verifications.update_one(
        {"user_id": user_id, "orcid_id": {"$exists": True}},
        {"$set": {"admin_verified": True, "admin_verified_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "ORCID verification not found")
    logger.info(f"ORCID verified by admin: user={user_id}")
    return {"status": "verified"}


@router.post("/admin/orcid-reject/{user_id}", dependencies=[Depends(verify_admin)])
async def admin_reject_orcid(user_id: str):
    """Admin: reject and remove an ORCID link."""
    await db.author_verifications.update_one(
        {"user_id": user_id},
        {"$unset": {"orcid_id": "", "orcid_name": "", "orcid_verified_email": "", "orcid_email_domains": "", "orcid_connected_at": ""},
         "$set": {"admin_verified": False}},
    )
    await db.users.update_one({"user_id": user_id}, {"$unset": {"orcid_id": ""}})
    logger.info(f"ORCID rejected by admin: user={user_id}")
    return {"status": "rejected"}
