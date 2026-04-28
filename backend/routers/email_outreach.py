"""Admin Email Outreach pipeline: send personalized congrats to top-ranked paper authors via Gmail."""

import asyncio
import base64
import os
import json
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

from core.config import db, logger, CATEGORIES
from core.auth import verify_admin

router = APIRouter(prefix="/api/admin/email-outreach", tags=["admin-email-outreach"])

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

DEFAULT_TEMPLATE = {
    "subject": "Your paper ranked #{{rank}} in {{category}} on Kurate.org",
    "body_html": """<p>Hi {{author_name}},</p>

<p>Your paper <strong>"{{paper_title}}"</strong> was ranked <strong>#{{rank}}</strong> in <strong>{{category}}</strong> for {{period}} on <a href="https://kurate.org">Kurate.org</a> — based on AI-evaluated scientific impact across {{total_papers}} papers.</p>

<p>See the full ranking: <a href="{{leaderboard_url}}">{{leaderboard_url}}</a></p>

{{badge_html}}

<p>Congratulations!</p>

<p>— <a href="https://kurate.org">Kurate.org</a></p>""",
}


async def _get_gmail_creds(admin_user_id: str = "admin") -> Credentials:
    """Get valid Gmail credentials for the admin. Refreshes if expired."""
    token_doc = await db.gmail_tokens.find_one(
        {"user_id": admin_user_id}, {"_id": 0}
    )
    if not token_doc or not token_doc.get("access_token"):
        raise HTTPException(403, "Gmail not authorized. Connect Gmail first via the Congrats page.")

    creds = Credentials(
        token=token_doc["access_token"],
        refresh_token=token_doc.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            await db.gmail_tokens.update_one(
                {"user_id": admin_user_id},
                {"$set": {"access_token": creds.token}},
            )
        except Exception as e:
            logger.warning(f"Gmail token refresh failed: {e}")
            raise HTTPException(403, "Gmail authorization expired. Please re-authorize.")
    return creds


def _render_template(template_str: str, variables: dict) -> str:
    """Simple mustache-style template rendering."""
    result = template_str
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


# --- Templates ---

@router.get("/templates", dependencies=[Depends(verify_admin)])
async def get_templates():
    """Get email templates."""
    doc = await db.settings.find_one({"key": "email_outreach_templates"}, {"_id": 0})
    if doc and doc.get("templates"):
        return {"templates": doc["templates"], "default": DEFAULT_TEMPLATE}
    return {"templates": [{"name": "default", **DEFAULT_TEMPLATE}], "default": DEFAULT_TEMPLATE}


class SaveTemplateRequest(BaseModel):
    name: str = "default"
    subject: str
    body_html: str


@router.post("/templates", dependencies=[Depends(verify_admin)])
async def save_template(body: SaveTemplateRequest):
    """Save/update an email template."""
    doc = await db.settings.find_one({"key": "email_outreach_templates"}, {"_id": 0})
    templates = doc.get("templates", []) if doc else []

    # Upsert by name
    found = False
    for t in templates:
        if t["name"] == body.name:
            t["subject"] = body.subject
            t["body_html"] = body.body_html
            t["updated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        templates.append({
            "name": body.name,
            "subject": body.subject,
            "body_html": body.body_html,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    await db.settings.update_one(
        {"key": "email_outreach_templates"},
        {"$set": {"key": "email_outreach_templates", "templates": templates}},
        upsert=True,
    )
    return {"status": "saved", "templates": templates}


# --- Medalists with emails ---

@router.get("/medalists", dependencies=[Depends(verify_admin)])
async def get_email_medalists(period: str = "weekly:2026-1", top_n: int = 3):
    """Get medalists with cached author emails for email outreach.
    Returns a flat list of papers (not grouped by category) for table rendering."""
    from core.auth import get_settings

    # Build category name map (covers all categories, not just the hardcoded 6)
    settings = await get_settings() or {}
    try:
        from core.arxiv_categories import ARXIV_TAXONOMY
    except ImportError:
        ARXIV_TAXONOMY = {}
    cat_names = {**ARXIV_TAXONOMY, **dict(CATEGORIES)}  # CATEGORIES overrides taxonomy

    if period.startswith("weekly:"):
        parts = period.split(":")[1].split("-")
        period_type, query_filter = "weekly", {"year": int(parts[0]), "week": int(parts[1])}
    elif period.startswith("monthly:"):
        parts = period.split(":")[1].split("-")
        period_type, query_filter = "monthly", {"year": int(parts[0]), "month": int(parts[1])}
    else:
        return {"period": period, "papers": [], "error": "Use weekly:YYYY-WW or monthly:YYYY-MM"}

    settings = await get_settings() or {}
    freq_config = settings.get("archive_frequency") or {}
    has_freq_config = bool(freq_config)

    all_papers = []

    async for archive in db.leaderboard_archives.find(
        {"period_type": period_type, **query_filter},
        {"_id": 0, "category": 1, "leaderboard": {"$slice": top_n}, "label": 1},
    ):
        cat = archive["category"]
        if has_freq_config:
            default_freq = freq_config.get("default", "weekly")
            cat_freq = freq_config.get(cat, default_freq)
            if cat_freq != period_type:
                continue

        for p in archive.get("leaderboard", [])[:top_n]:
            paper_id = p.get("id")
            # Get cached emails
            email_doc = await db.author_emails.find_one(
                {"paper_id": paper_id}, {"_id": 0}
            )
            # Get all sends for this paper+period
            sent_emails = []
            async for s in db.email_sends.find(
                {"paper_id": paper_id, "period": period},
                {"_id": 0, "to_email": 1, "sent_at": 1},
            ):
                sent_emails.append({"to_email": s["to_email"], "sent_at": s["sent_at"]})

            cached_emails = email_doc.get("emails", []) if email_doc else []
            # Mark as "extracted" only if emails were found OR the paper has full_text
            # (abstract-only extractions with empty results should be retried)
            truly_extracted = email_doc is not None and (len(cached_emails) > 0 or email_doc.get("has_full_text", False))

            all_papers.append({
                "id": paper_id,
                "rank": p.get("rank"),
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id"),
                "category": cat,
                "category_name": cat_names.get(cat, cat),
                "period_label": archive.get("label", ""),
                "emails": cached_emails,
                "emails_extracted": truly_extracted,
                "sent_emails": sent_emails,
                "already_sent": len(sent_emails) > 0,
                "sent_at": sent_emails[0]["sent_at"] if sent_emails else None,
            })

    # Sort by category then rank
    all_papers.sort(key=lambda p: (p["category"], p.get("rank") or 99))

    return {
        "period": period,
        "papers": all_papers,
        "total_papers": len(all_papers),
        "total_with_emails": sum(1 for p in all_papers if p["emails"]),
        "total_sent": sum(1 for p in all_papers if p["already_sent"]),
        "total_no_emails": sum(1 for p in all_papers if p["emails_extracted"] and not p["emails"]),
    }


# --- Email extraction ---

class ExtractEmailsRequest(BaseModel):
    paper_id: str


@router.post("/extract-emails", dependencies=[Depends(verify_admin)])
async def extract_emails_for_paper(body: ExtractEmailsRequest):
    """Extract author emails for a single paper using LLM.

    If full_text is missing (legacy papers), downloads the PDF on-demand first.
    """
    paper = await db.papers.find_one(
        {"id": body.paper_id},
        {"_id": 0, "title": 1, "authors": 1, "abstract": 1, "full_text": 1, "arxiv_id": 1, "pdf_link": 1, "doi": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    full_text = paper.get("full_text", "") or ""

    # If no full_text, try downloading the PDF on-demand (legacy papers missing pdf_link)
    if not full_text and paper.get("arxiv_id"):
        pdf_url = paper.get("pdf_link") or f"https://arxiv.org/pdf/{paper['arxiv_id']}"
        logger.info(f"[email-extract] Downloading PDF on-demand for {paper['arxiv_id']}")
        try:
            from services.llm import download_and_extract_pdf
            full_text = await download_and_extract_pdf(pdf_url, doi=paper.get("doi")) or ""
            if full_text:
                await db.papers.update_one(
                    {"id": body.paper_id},
                    {"$set": {"full_text": full_text, "pdf_link": pdf_url, "needs_pdf": False},
                     "$unset": {"pdf_failed": "", "pdf_fail_reason": ""}},
                )
                logger.info(f"[email-extract] PDF downloaded for {paper['arxiv_id']} ({len(full_text)} chars)")
        except Exception as e:
            logger.warning(f"[email-extract] On-demand PDF download failed for {paper['arxiv_id']}: {e}")

    text = full_text or paper.get("abstract", "") or ""
    if not text:
        await _cache_emails(body.paper_id, [], paper.get("authors", []))
        return {"paper_id": body.paper_id, "emails": [], "note": "No paper text available"}

    # Use first 8K chars — covers header, affiliations, correspondence section
    snippet = text[:8000]
    emails = []

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        from core.config import EMERGENT_LLM_KEY

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"extract-emails-{body.paper_id}",
            system_message=(
                "Extract author email addresses from this academic paper text. "
                "Handle curly-brace group notation like {user1, user2}@domain.edu — expand each into a full email address. "
                "Handle cases where institution names are glued to emails due to PDF extraction (e.g. 'Corporationjtu@nvidia.com' should become 'jtu@nvidia.com'). "
                "Return ONLY a JSON array of clean email strings. If none found, return []. No explanations."
            ),
        ).with_model("openai", "gpt-4o-mini")

        response = await asyncio.to_thread(
            lambda: asyncio.run(chat.send_message(UserMessage(
                text=f"Extract all author email addresses:\n\nTitle: {paper.get('title', '')}\nAuthors: {', '.join(paper.get('authors', []))}\n\nText:\n{snippet}"
            ))),
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            emails = [e for e in parsed if isinstance(e, str) and "@" in e]
    except Exception as e:
        logger.warning(f"[email-extract] LLM extraction failed for {body.paper_id}: {e}")

    await _cache_emails(body.paper_id, emails, paper.get("authors", []), has_full_text=bool(full_text))
    return {"paper_id": body.paper_id, "emails": emails}


async def _cache_emails(paper_id: str, emails: list, authors: list, has_full_text: bool = False):
    """Store extracted emails in the author_emails collection."""
    await db.author_emails.update_one(
        {"paper_id": paper_id},
        {"$set": {
            "paper_id": paper_id,
            "emails": emails,
            "authors": authors,
            "has_full_text": has_full_text,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


class ExtractBatchRequest(BaseModel):
    paper_ids: list[str]


@router.post("/extract-emails-batch", dependencies=[Depends(verify_admin)])
async def extract_emails_batch(body: ExtractBatchRequest):
    """Batch extract emails for multiple papers. Returns immediately, processes in background."""
    if not body.paper_ids:
        return {"status": "no_papers"}

    # Skip papers that already have cached emails found.
    # Papers with empty cached results (from abstract-only extraction) should be retried
    # since on-demand PDF download may now succeed.
    already = set()
    async for doc in db.author_emails.find(
        {"paper_id": {"$in": body.paper_ids}, "emails.0": {"$exists": True}},
        {"_id": 0, "paper_id": 1}
    ):
        already.add(doc["paper_id"])

    to_extract = [pid for pid in body.paper_ids if pid not in already]

    if not to_extract:
        return {"status": "all_cached", "already_extracted": len(already)}

    async def _run():
        for pid in to_extract:
            try:
                await extract_emails_for_paper(ExtractEmailsRequest(paper_id=pid))
                await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                logger.warning(f"Batch email extraction failed for {pid}: {e}")

    asyncio.create_task(_run())
    return {
        "status": "started",
        "extracting": len(to_extract),
        "already_cached": len(already),
    }


# --- Manual email entry ---

class ManualEmailRequest(BaseModel):
    paper_id: str
    emails: list[str]


@router.post("/set-emails", dependencies=[Depends(verify_admin)])
async def set_emails_manually(body: ManualEmailRequest):
    """Manually set/override author emails for a paper."""
    emails = [e.strip() for e in body.emails if "@" in e.strip()]
    paper = await db.papers.find_one({"id": body.paper_id}, {"_id": 0, "authors": 1})

    await db.author_emails.update_one(
        {"paper_id": body.paper_id},
        {"$set": {
            "paper_id": body.paper_id,
            "emails": emails,
            "authors": paper.get("authors", []) if paper else [],
            "manual": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"status": "saved", "paper_id": body.paper_id, "emails": emails}


# --- Send emails ---

class SendEmailRequest(BaseModel):
    paper_id: str
    to_emails: list[str]
    period: str
    category: str
    rank: int
    template_name: str = "default"
    custom_subject: Optional[str] = None
    custom_body: Optional[str] = None


@router.post("/send", dependencies=[Depends(verify_admin)])
async def send_outreach_email(body: SendEmailRequest):
    """Send a personalized outreach email to paper authors via Gmail, with inline badge."""
    paper = await db.papers.find_one(
        {"id": body.paper_id},
        {"_id": 0, "title": 1, "authors": 1, "arxiv_id": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    # Get template
    if body.custom_subject and body.custom_body:
        subject_tpl = body.custom_subject
        body_tpl = body.custom_body
    else:
        doc = await db.settings.find_one({"key": "email_outreach_templates"}, {"_id": 0})
        templates = doc.get("templates", []) if doc else []
        tpl = next((t for t in templates if t["name"] == body.template_name), None)
        if not tpl:
            subject_tpl = DEFAULT_TEMPLATE["subject"]
            body_tpl = DEFAULT_TEMPLATE["body_html"]
        else:
            subject_tpl = tpl["subject"]
            body_tpl = tpl["body_html"]

    cat_names = dict(CATEGORIES)
    category_name = cat_names.get(body.category, body.category)

    # Parse period to get year/week/month for badge + leaderboard URL
    year, week, month = None, None, None
    period_label = body.period
    if body.period.startswith("weekly:"):
        parts = body.period.split(":")[1].split("-")
        year, week = int(parts[0]), int(parts[1])
        period_label = f"Week {week}, {year}"
    elif body.period.startswith("monthly:"):
        parts = body.period.split(":")[1].split("-")
        year, month = int(parts[0]), int(parts[1])
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        period_label = f"{month_names[month]} {year}"

    # Get paper count from archive
    total_papers = "?"
    archive_query = {"category": body.category}
    if week is not None:
        archive_query.update({"period_type": "weekly", "year": year, "week": week})
    elif month is not None:
        archive_query.update({"period_type": "monthly", "year": year, "month": month})
    archive = await db.leaderboard_archives.find_one(archive_query, {"_id": 0, "paper_count": 1})
    if archive:
        total_papers = str(archive.get("paper_count", "?"))

    # Build leaderboard URL
    if week is not None:
        leaderboard_url = f"https://kurate.org/leaderboard/{body.category}/{year}/w{week}"
    elif month is not None:
        leaderboard_url = f"https://kurate.org/leaderboard/{body.category}/{year}/m{month}"
    else:
        leaderboard_url = f"https://kurate.org"

    # Generate badge PNG if top-3
    badge_png = None
    if body.rank <= 3 and year:
        try:
            from routers.badges import _get_badge_data, _render_badge_png
            badge_data = await _get_badge_data(
                body.category, year, body.paper_id,
                week=week, month=month,
            )
            badge_png = await _render_badge_png(badge_data)
            logger.info(f"[email-outreach] Badge rendered for {body.paper_id} ({len(badge_png)} bytes)")
        except Exception as e:
            logger.warning(f"[email-outreach] Badge render failed: {e}")

    # Build badge HTML (inline CID reference if we have the image)
    if badge_png:
        badge_html = '<p><img src="cid:badge" alt="Kurate Badge" style="max-width:600px;width:100%;border-radius:8px;" /></p>'
    else:
        badge_html = ""

    # Render variables
    authors = paper.get("authors", [])
    first_author = authors[0] if authors else "researcher"

    variables = {
        "author_name": first_author,
        "paper_title": paper.get("title", ""),
        "category": category_name,
        "rank": str(body.rank),
        "period": period_label,
        "paper_id": body.paper_id,
        "total_papers": total_papers,
        "arxiv_id": paper.get("arxiv_id", ""),
        "leaderboard_url": leaderboard_url,
        "badge_html": badge_html,
    }

    subject = _render_template(subject_tpl, variables)
    body_html = _render_template(body_tpl, variables)

    # Get Gmail credentials
    creds = await _get_gmail_creds()

    # Build and send email
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        sent_to = []
        for to_email in body.to_emails[:5]:
            # Proper MIME structure for inline images:
            # multipart/related
            #   ├── multipart/alternative
            #   │     └── text/html (references cid:badge)
            #   └── image/png (Content-ID: <badge>)
            msg = MIMEMultipart("related")
            msg["to"] = to_email
            msg["subject"] = subject
            msg["from"] = "robert@kurate.org"

            msg_alt = MIMEMultipart("alternative")
            msg_alt.attach(MIMEText(body_html, "html"))
            msg.attach(msg_alt)

            if badge_png:
                from email.mime.image import MIMEImage
                img_part = MIMEImage(badge_png, _subtype="png")
                img_part.add_header("Content-ID", "<badge>")
                img_part.add_header("Content-Disposition", "inline", filename="kurate-badge.png")
                msg.attach(img_part)

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            await asyncio.to_thread(
                lambda: service.users().messages().send(
                    userId="me", body={"raw": raw}
                ).execute()
            )
            sent_to.append(to_email)
            logger.info(f"[email-outreach] Sent to {to_email} for paper {body.paper_id}")

        # Record in DB
        now = datetime.now(timezone.utc).isoformat()
        for to_email in sent_to:
            await db.email_sends.insert_one({
                "paper_id": body.paper_id,
                "to_email": to_email,
                "subject": subject,
                "period": body.period,
                "category": body.category,
                "rank": body.rank,
                "sent_at": now,
                "status": "sent",
                "paper_title": paper.get("title", ""),
                "authors": authors,
            })

        return {"status": "sent", "recipients": sent_to, "sent_at": now}

    except Exception as e:
        logger.error(f"[email-outreach] Send failed: {e}")
        raise HTTPException(500, f"Failed to send: {str(e)[:200]}")


class SendBatchRequest(BaseModel):
    paper_ids: list[str]
    period: str
    template_name: str = "default"


@router.post("/send-batch", dependencies=[Depends(verify_admin)])
async def send_batch(body: SendBatchRequest):
    """Send outreach emails for multiple papers. Skips already-sent."""
    results = {"sent": [], "skipped": [], "failed": []}

    for paper_id in body.paper_ids:
        # Check if already sent
        existing = await db.email_sends.find_one(
            {"paper_id": paper_id, "period": body.period}, {"_id": 0}
        )
        if existing:
            results["skipped"].append(paper_id)
            continue

        # Get emails
        email_doc = await db.author_emails.find_one(
            {"paper_id": paper_id}, {"_id": 0}
        )
        if not email_doc or not email_doc.get("emails"):
            results["skipped"].append(paper_id)
            continue

        # Get paper for rank/category
        # Look up in archives
        paper = await db.papers.find_one(
            {"id": paper_id}, {"_id": 0, "title": 1, "authors": 1, "categories": 1}
        )
        if not paper:
            results["skipped"].append(paper_id)
            continue

        category = (paper.get("categories") or [""])[0] if paper.get("categories") else ""
        try:
            await send_outreach_email(SendEmailRequest(
                paper_id=paper_id,
                to_emails=email_doc["emails"][:3],
                period=body.period,
                category=category,
                rank=1,  # Will be enriched from archive data
                template_name=body.template_name,
            ))
            results["sent"].append(paper_id)
            await asyncio.sleep(2)  # Pace sends
        except Exception as e:
            logger.warning(f"[email-outreach] Batch send failed for {paper_id}: {e}")
            results["failed"].append(paper_id)

    return results



# --- Test send ---

class TestSendRequest(BaseModel):
    paper_id: str
    period: str
    category: str
    rank: int


@router.post("/test-send", dependencies=[Depends(verify_admin)])
async def test_send(body: TestSendRequest):
    """Send a test email to roblauko@gmail.com with badge for a specific paper."""
    return await send_outreach_email(SendEmailRequest(
        paper_id=body.paper_id,
        to_emails=["roblauko@gmail.com"],
        period=body.period,
        category=body.category,
        rank=body.rank,
    ))


# --- History ---

@router.get("/history", dependencies=[Depends(verify_admin)])
async def get_send_history(limit: int = 100):
    """Get email send history."""
    sends = []
    async for doc in db.email_sends.find(
        {}, {"_id": 0}
    ).sort("sent_at", -1).limit(limit):
        sends.append(doc)
    return {"sends": sends, "count": len(sends)}


# --- Gmail status ---

@router.get("/gmail-status", dependencies=[Depends(verify_admin)])
async def gmail_status():
    """Check if Gmail is authorized for sending."""
    token = await db.gmail_tokens.find_one(
        {"user_id": "admin"}, {"_id": 0, "access_token": 1}
    )
    # Also check any user with gmail tokens
    if not token:
        token = await db.gmail_tokens.find_one(
            {}, {"_id": 0, "access_token": 1, "user_id": 1}
        )
    return {
        "authorized": bool(token and token.get("access_token")),
        "user_id": token.get("user_id") if token else None,
    }


# --- Gmail OAuth for admin ---
# Reuses the existing /api/gmail/callback registered in GCP.
# We just initiate the flow with user_id="admin" and return_to="/admin/outreach/email".

SITE_URL = os.environ.get("SITE_URL", "")

@router.get("/gmail/auth-url", dependencies=[Depends(verify_admin)])
async def gmail_auth_url_admin(request: Request):
    """Start Gmail OAuth flow for admin. Uses the same redirect_uri as the
    existing congrats flow (already registered in GCP)."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Gmail integration not configured (GOOGLE_CLIENT_ID/SECRET missing)")

    # Use the SAME redirect_uri that's registered in GCP
    redirect_uri = f"{SITE_URL}/api/gmail/callback" if SITE_URL else f"{request.headers.get('origin', '')}/api/gmail/callback"

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=["https://www.googleapis.com/auth/gmail.send"],
        redirect_uri=redirect_uri,
    )
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    # Store state — the existing /api/gmail/callback handler reads this
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": "admin",
        "return_to": "/admin/outreach/email",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })
    return {"url": url}
