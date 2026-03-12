"""Author paper claiming via ORCID + Semantic Scholar verification."""

import os
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger

router = APIRouter(prefix="/api/claim")

ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")
ORCID_REDIRECT_URI = os.environ.get("ORCID_REDIRECT_URI", "")
S2_API_KEY = os.environ.get("S2_API_KEY", "")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
ORCID_BASE = "https://orcid.org"


# --- Helpers ---

async def _get_current_user(request: Request) -> Optional[dict]:
    """Extract user from session (reuse auth module logic)."""
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


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


async def _verify_authorship(orcid_id: str, arxiv_id: str) -> dict:
    """Run multi-signal verification pipeline. Returns {verified, method, confidence}."""

    # Signal 1: S2 paper reverse lookup (fastest — single API call)
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

    # Signal 2: S2 author search → paper list
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

    # No automatic verification possible
    return {"verified": False, "method": "no_match", "confidence": 0.0}


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
    await db.author_verifications.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "orcid_id": orcid_id,
                "orcid_name": orcid_name or user.get("name", ""),
                "orcid_connected_at": datetime.now(timezone.utc).isoformat(),
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

    logger.info(f"ORCID connected: user={user['user_id']} orcid={orcid_id}")
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
    paper = await db.papers.find_one({"id": paper_id}, {"_id": 0, "id": 1, "arxiv_id": 1, "title": 1, "claimed_by": 1})
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
    result = await _verify_authorship(orcid_id, arxiv_id)

    claim_record = {
        "orcid_id": orcid_id,
        "user_id": user["user_id"],
        "author_name": verification.get("orcid_name", user.get("name", "")),
        "verified": result["verified"],
        "method": result["method"],
        "confidence": result["confidence"],
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
        return {"status": "pending", "message": "Could not automatically verify. Claim submitted for manual review."}


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
