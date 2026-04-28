"""Admin Email Outreach pipeline: send personalized congrats to top-ranked paper authors via Gmail."""

import asyncio
import base64
import os
import json
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import APIRouter, Depends, HTTPException, Query
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

<p>Congratulations! Your paper <strong>"{{paper_title}}"</strong> was ranked <strong>#{{rank}}</strong> in <strong>{{category}}</strong> on <a href="https://kurate.org">Kurate.org</a> for {{period}}.</p>

<p>Kurate uses AI-powered pairwise tournaments to surface the most impactful preprints each week — and yours stood out among {{total_papers}} papers evaluated.</p>

<p>If you'd like to share this with colleagues, here's your paper's page: <a href="https://kurate.org/paper/{{paper_id}}">kurate.org/paper/{{paper_id}}</a></p>

<p>Congratulations again — and if the ranking surprises you (positively or negatively), I'd love to hear your take. I'm always refining the methodology.</p>

<p>Best,<br>Robert</p>""",
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

    cat_names = dict(CATEGORIES)

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

            all_papers.append({
                "id": paper_id,
                "rank": p.get("rank"),
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "arxiv_id": p.get("arxiv_id"),
                "category": cat,
                "category_name": cat_names.get(cat, cat),
                "period_label": archive.get("label", ""),
                "emails": email_doc.get("emails", []) if email_doc else [],
                "emails_extracted": email_doc is not None,
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
    """Extract author emails for a single paper using LLM."""
    paper = await db.papers.find_one(
        {"id": body.paper_id},
        {"_id": 0, "title": 1, "authors": 1, "abstract": 1, "full_text": 1, "arxiv_id": 1}
    )
    if not paper:
        raise HTTPException(404, "Paper not found")

    text = paper.get("full_text", "") or paper.get("abstract", "")
    if not text:
        return {"paper_id": body.paper_id, "emails": [], "note": "No paper text available"}

    snippet = text[:5000]

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        from core.config import EMERGENT_LLM_KEY

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"extract-emails-{body.paper_id}",
            system_message="Extract email addresses from this academic paper text. Return ONLY a JSON array of email strings. If none found, return []. No explanations.",
        ).with_model("gemini", "gemini-2.0-flash")

        response = await asyncio.to_thread(
            lambda: asyncio.run(chat.send_message(UserMessage(
                text=f"Extract all author email addresses from this paper:\n\nTitle: {paper.get('title', '')}\nAuthors: {', '.join(paper.get('authors', []))}\n\nText:\n{snippet}"
            ))),
        )
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
    except Exception as e:
        logger.warning(f"Email extraction failed for {body.paper_id}: {e}")
        emails = []

    # Cache in DB
    await db.author_emails.update_one(
        {"paper_id": body.paper_id},
        {"$set": {
            "paper_id": body.paper_id,
            "emails": emails,
            "authors": paper.get("authors", []),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"paper_id": body.paper_id, "emails": emails}


class ExtractBatchRequest(BaseModel):
    paper_ids: list[str]


@router.post("/extract-emails-batch", dependencies=[Depends(verify_admin)])
async def extract_emails_batch(body: ExtractBatchRequest):
    """Batch extract emails for multiple papers. Returns immediately, processes in background."""
    if not body.paper_ids:
        return {"status": "no_papers"}

    # Only extract for papers without cached emails
    already = set()
    async for doc in db.author_emails.find(
        {"paper_id": {"$in": body.paper_ids}}, {"_id": 0, "paper_id": 1}
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
    """Send a personalized outreach email to paper authors via Gmail."""
    # Get paper info
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

    # Parse period label
    period_label = body.period
    cat_names = dict(CATEGORIES)
    category_name = cat_names.get(body.category, body.category)

    # Count papers in the period for context
    total_papers = "hundreds of"

    # Render for first author (or generic)
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
    }

    subject = _render_template(subject_tpl, variables)
    body_html = _render_template(body_tpl, variables)

    # Get Gmail credentials
    creds = await _get_gmail_creds()

    # Send
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        sent_to = []
        for to_email in body.to_emails[:5]:  # Max 5 recipients per paper
            msg = MIMEMultipart("alternative")
            msg["to"] = to_email
            msg["subject"] = subject
            msg["from"] = "robert@kurate.org"
            part = MIMEText(body_html, "html")
            msg.attach(part)
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
