"""Shared utilities for social sharing endpoints."""

import os
from fastapi import Request

SITE_URL = os.environ.get("SITE_URL", "")

# Explicit public host allowlist — only these are trusted from proxy headers
_ALLOWED_HOSTS = {
    "kurate.org", "www.kurate.org",
}
# Preview hostnames are dynamic but follow a pattern
_PREVIEW_SUFFIX = ".preview.emergentagent.com"


def get_public_base_url(request: Request) -> str:
    """Resolve the public-facing base URL from proxy headers with allowlist validation."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto", "https")

    if host in _ALLOWED_HOSTS or host.endswith(_PREVIEW_SUFFIX):
        return f"{proto}://{host}"

    return SITE_URL or f"{proto}://{host}" if host else "https://kurate.org"


SHARE_HEADERS = {
    "Cache-Control": "public, max-age=300, no-transform",
}
