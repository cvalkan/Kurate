import uuid
import secrets
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from typing import Optional
from passlib.hash import bcrypt
import httpx
import resend
import os

from core.config import db, logger

router = APIRouter(prefix="/api/auth")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
SESSION_DAYS = 7

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# --- Models ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class SessionRequest(BaseModel):
    session_id: str


# --- Helpers ---

def _generate_session_token():
    return f"sess_{secrets.token_urlsafe(32)}"


def _generate_verification_token():
    return secrets.token_urlsafe(32)


async def _get_current_user(request: Request) -> Optional[dict]:
    """Extract user from session token (cookie or header)."""
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None

    session = await db.user_sessions.find_one(
        {"session_token": token}, {"_id": 0}
    )
    if not session:
        return None

    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None

    user = await db.users.find_one(
        {"user_id": session["user_id"]}, {"_id": 0}
    )
    if not user or user.get("active") is False:
        return None
    return user


async def _create_session(user_id: str, response: Response) -> str:
    token = _generate_session_token()
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=SESSION_DAYS * 86400,
    )
    return token


async def _send_verification_email(email: str, name: str, token: str, origin: str):
    if not RESEND_API_KEY:
        logger.warning("No RESEND_API_KEY — skipping verification email")
        return False

    verify_url = f"{origin}/verify-email?token={token}"
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
      <h2 style="color: #1a1a2e; margin-bottom: 8px;">Verify your email</h2>
      <p style="color: #666; font-size: 14px;">Hi {name}, click the button below to verify your email address for Kurate.org.</p>
      <a href="{verify_url}" style="display: inline-block; background: #1a1a2e; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-size: 14px; margin: 16px 0;">Verify Email</a>
      <p style="color: #999; font-size: 12px; margin-top: 24px;">If you didn't create this account, ignore this email.</p>
    </div>
    """
    params = {
        "from": SENDER_EMAIL,
        "to": [email],
        "subject": "Verify your Kurate.org account",
        "html": html,
    }
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Verification email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        return False


# --- Endpoints ---

@router.post("/register")
async def register(req: RegisterRequest, request: Request, response: Response):
    existing = await db.users.find_one({"email": req.email}, {"_id": 0})
    if existing:
        if existing.get("provider") == "google":
            raise HTTPException(400, "This email is registered via Google. Please use Google sign-in.")
        raise HTTPException(400, "Email already registered")

    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    verification_token = _generate_verification_token()
    password_hash = bcrypt.hash(req.password)

    await db.users.insert_one({
        "user_id": user_id,
        "email": req.email,
        "name": req.name,
        "picture": None,
        "password_hash": password_hash,
        "email_verified": False,
        "verification_token": verification_token,
        "provider": "email",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Send verification email — do NOT create session until verified
    origin = request.headers.get("origin", request.headers.get("referer", ""))
    if origin and "?" in origin:
        origin = origin.split("?")[0]
    if origin and origin.endswith("/"):
        origin = origin[:-1]
    sent = await _send_verification_email(req.email, req.name, verification_token, origin)

    return {
        "status": "verification_required",
        "verification_sent": sent,
        "message": "Account created. Please check your email to verify your account before logging in.",
    }


@router.post("/verify-email")
async def verify_email(token: str):
    user = await db.users.find_one(
        {"verification_token": token}, {"_id": 0}
    )
    if not user:
        raise HTTPException(400, "Invalid or expired verification token")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"email_verified": True}, "$unset": {"verification_token": ""}},
    )
    return {"status": "ok", "message": "Email verified successfully"}


class ResendVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest, request: Request):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user:
        # Don't reveal whether email exists
        return {"status": "ok", "message": "If this email is registered, a verification link has been sent."}

    if user.get("email_verified"):
        return {"status": "ok", "message": "Email is already verified. You can log in."}

    if user.get("provider") == "google":
        return {"status": "ok", "message": "Google accounts are automatically verified. Use Google sign-in."}

    # Generate fresh token
    new_token = _generate_verification_token()
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"verification_token": new_token}},
    )

    origin = request.headers.get("origin", request.headers.get("referer", ""))
    if origin and "?" in origin:
        origin = origin.split("?")[0]
    if origin and origin.endswith("/"):
        origin = origin[:-1]

    sent = await _send_verification_email(req.email, user.get("name", ""), new_token, origin)
    if not sent:
        raise HTTPException(500, "Failed to send verification email. Please try again later.")

    return {"status": "ok", "message": "Verification email sent. Check your inbox."}


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user:
        raise HTTPException(401, "Invalid email or password")

    if user.get("provider") == "google":
        raise HTTPException(400, "This email is registered via Google. Please use Google sign-in.")

    if not user.get("password_hash") or not bcrypt.verify(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    if not user.get("email_verified"):
        raise HTTPException(403, "Please verify your email before logging in. Check your inbox for the verification link.")

    if user.get("active") is False:
        raise HTTPException(403, "Your account has been deactivated. Please contact the administrator.")

    token = await _create_session(user["user_id"], response)

    orcid_admin_verified = False
    if user.get("orcid_id"):
        av = await db.author_verifications.find_one(
            {"user_id": user["user_id"]}, {"_id": 0, "admin_verified": 1}
        )
        orcid_admin_verified = bool(av.get("admin_verified")) if av else False

    return {
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user.get("picture"),
            "email_verified": user.get("email_verified", False),
            "provider": user.get("provider", "email"),
            "orcid_id": user.get("orcid_id"),
            "orcid_admin_verified": orcid_admin_verified,
        },
        "session_token": token,
    }


@router.post("/google-session")
async def google_session(req: SessionRequest, response: Response):
    """Exchange Emergent Google OAuth session_id for user data and create local session."""
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": req.session_id},
                timeout=10,
            )
            if res.status_code != 200:
                raise HTTPException(401, "Invalid Google session")
            data = res.json()
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to verify Google session: {e}")

    email = data.get("email")
    name = data.get("name", "")
    picture = data.get("picture", "")

    if not email:
        raise HTTPException(400, "No email returned from Google")

    # Upsert user
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        if existing.get("active") is False:
            raise HTTPException(403, "Your account has been deactivated. Please contact the administrator.")
        await db.users.update_one(
            {"email": email},
            {"$set": {"name": name, "picture": picture, "provider": "google", "email_verified": True}},
        )
        user_id = existing["user_id"]
        is_new_user = False
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "password_hash": None,
            "email_verified": True,
            "provider": "google",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        is_new_user = True

    token = await _create_session(user_id, response)

    # Get full user record to include orcid_id
    full_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    orcid_admin_verified = False
    if full_user and full_user.get("orcid_id"):
        av = await db.author_verifications.find_one(
            {"user_id": user_id}, {"_id": 0, "admin_verified": 1}
        )
        orcid_admin_verified = bool(av.get("admin_verified")) if av else False

    return {
        "user": {"user_id": user_id, "email": email, "name": name, "picture": picture, "email_verified": True, "provider": "google", "orcid_id": full_user.get("orcid_id") if full_user else None, "orcid_admin_verified": orcid_admin_verified},
        "session_token": token,
        "is_new_user": is_new_user,
    }


@router.get("/me")
async def get_me(request: Request):
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    orcid_admin_verified = False
    if user.get("orcid_id"):
        av = await db.author_verifications.find_one(
            {"user_id": user["user_id"]}, {"_id": 0, "admin_verified": 1}
        )
        orcid_admin_verified = bool(av.get("admin_verified")) if av else False
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
        "picture": user.get("picture"),
        "email_verified": user.get("email_verified", False),
        "provider": user.get("provider", "email"),
        "orcid_id": user.get("orcid_id"),
        "orcid_admin_verified": orcid_admin_verified,
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/", samesite="none", secure=True)
    return {"status": "ok"}



class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("provider") == "google":
        raise HTTPException(400, "Google accounts cannot change password here")
    if not user.get("password_hash") or not bcrypt.verify(req.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    new_hash = bcrypt.hash(req.new_password)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"password_hash": new_hash}})
    return {"status": "ok"}
