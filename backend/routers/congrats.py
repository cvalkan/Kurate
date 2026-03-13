"""Congratulations pipeline: rate-limited kudos + Gmail send via OAuth."""

import os
import asyncio
import base64
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

from core.config import db, logger

router = APIRouter(prefix="/api/congrats")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SITE_URL = os.environ.get("SITE_URL", "")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_redirect_uri(request: Request) -> str:
    if SITE_URL:
        return f"{SITE_URL}/api/gmail/callback"
    origin = request.headers.get("origin", "")
    return f"{origin}/api/gmail/callback"


def _build_flow(redirect_uri: str) -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )


async def _get_current_user(request: Request) -> Optional[dict]:
    from routers.auth import _get_current_user as _auth_get_user
    return await _auth_get_user(request)


async def _get_rate_limit() -> int:
    from core.auth import get_settings
    settings = await get_settings()
    return settings.get("congrats_per_week", 5)


# --- Rate limiting & tracking ---

class CongratsRequest(BaseModel):
    paper_id: str
    badge_category: str
    badge_year: int
    badge_slug: str
    method: str  # "linkedin", "twitter", "email"


@router.get("/remaining")
async def get_remaining(request: Request):
    """How many congrats the current user has left this week."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    limit = await _get_rate_limit()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    count = await db.congratulations.count_documents({
        "user_id": user["user_id"],
        "created_at": {"$gte": week_ago.isoformat()},
    })
    return {"remaining": max(0, limit - count), "limit": limit, "used": count}


@router.post("/send")
async def send_congrats(body: CongratsRequest, request: Request):
    """Record a congratulation (rate-limited)."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    limit = await _get_rate_limit()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    count = await db.congratulations.count_documents({
        "user_id": user["user_id"],
        "created_at": {"$gte": week_ago.isoformat()},
    })
    if count >= limit:
        raise HTTPException(429, f"Rate limit reached ({limit} per week)")

    await db.congratulations.insert_one({
        "user_id": user["user_id"],
        "user_name": user.get("name", ""),
        "user_email": user.get("email", ""),
        "paper_id": body.paper_id,
        "badge_category": body.badge_category,
        "badge_year": body.badge_year,
        "badge_slug": body.badge_slug,
        "method": body.method,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "ok", "remaining": max(0, limit - count - 1)}


# --- Gmail OAuth ---

@router.get("/gmail/auth-url")
async def gmail_auth_url(request: Request, return_to: str = Query("")):
    """Start Gmail OAuth flow — returns URL to redirect user to."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Gmail integration not configured")

    redirect_uri = _get_redirect_uri(request)
    flow = _build_flow(redirect_uri)
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    # Store state → user mapping (10 min TTL)
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": user["user_id"],
        "return_to": return_to,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })
    return {"url": url}


@router.get("/gmail/status")
async def gmail_status(request: Request):
    """Check if user has Gmail send permission."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    token = await db.gmail_tokens.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    )
    return {"authorized": bool(token and token.get("access_token"))}


class EmailSendRequest(BaseModel):
    to_emails: list[str]
    subject: str
    body_html: str
    paper_id: str
    badge_category: str
    badge_year: int
    badge_slug: str


@router.post("/gmail/send")
async def gmail_send(body: EmailSendRequest, request: Request):
    """Send a congratulatory email via the user's Gmail."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    token_doc = await db.gmail_tokens.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    )
    if not token_doc or not token_doc.get("access_token"):
        raise HTTPException(403, "Gmail not authorized. Please authorize first.")

    # Build credentials
    creds = Credentials(
        token=token_doc["access_token"],
        refresh_token=token_doc.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            await db.gmail_tokens.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"access_token": creds.token}},
            )
        except Exception as e:
            logger.warning(f"Gmail token refresh failed: {e}")
            raise HTTPException(403, "Gmail authorization expired. Please re-authorize.")

    # Send email
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        for to_email in body.to_emails[:5]:  # Max 5 recipients
            msg = MIMEText(body.body_html, "html")
            msg["to"] = to_email
            msg["subject"] = body.subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            await asyncio.to_thread(
                lambda: service.users().messages().send(
                    userId="me", body={"raw": raw}
                ).execute()
            )
        logger.info(f"Gmail sent by {user['email']} to {body.to_emails}")
    except Exception as e:
        logger.error(f"Gmail send failed: {e}")
        raise HTTPException(500, f"Failed to send email: {str(e)[:100]}")

    # Record as congrats
    await db.congratulations.insert_one({
        "user_id": user["user_id"],
        "user_name": user.get("name", ""),
        "user_email": user.get("email", ""),
        "paper_id": body.paper_id,
        "badge_category": body.badge_category,
        "badge_year": body.badge_year,
        "badge_slug": body.badge_slug,
        "method": "email",
        "to_emails": body.to_emails,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "sent", "recipients": len(body.to_emails)}


# --- Extract author emails from PDF ---

class ExtractEmailsRequest(BaseModel):
    paper_id: str


@router.post("/extract-emails")
async def extract_emails(body: ExtractEmailsRequest, request: Request):
    """Use LLM to extract author email addresses from the paper."""
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    paper = await db.papers.find_one(
        {"id": body.paper_id}, {"_id": 0, "title": 1, "authors": 1, "abstract": 1, "full_text": 1, "arxiv_id": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    text = paper.get("full_text", "") or paper.get("abstract", "")
    if not text:
        return {"emails": [], "note": "No paper text available"}

    # Use first 5000 chars (emails are usually in the first page)
    snippet = text[:5000]

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        from core.config import EMERGENT_LLM_KEY

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"extract-emails-{body.paper_id}",
            system_message="Extract email addresses from this academic paper text. Return ONLY a JSON array of email strings. If none found, return []. No explanations.",
        ).with_model("gemini", "gemini-2.0-flash")

        import json
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: asyncio.run(chat.send_message(UserMessage(
                text=f"Extract all author email addresses from this paper:\n\nTitle: {paper.get('title', '')}\nAuthors: {', '.join(paper.get('authors', []))}\n\nText:\n{snippet}"
            ))),
        )
        # Parse JSON array from response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        emails = json.loads(cleaned)
        if not isinstance(emails, list):
            emails = []
        emails = [e for e in emails if isinstance(e, str) and "@" in e]
        return {"emails": emails}
    except Exception as e:
        logger.warning(f"Email extraction failed: {e}")
        return {"emails": [], "note": "Could not extract emails automatically"}
