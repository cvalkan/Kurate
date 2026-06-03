"""Shared date-bucketing helpers — the single source of truth for "what UTC day
is this document", working for both string (preview) and BSON Date (production)
stored fields. Used by the admin2 backfill and the legacy chunk aggregations so
they bucket dates identically."""


def mongo_day_expr(field: str) -> dict:
    """MongoDB aggregation expression → 'YYYY-MM-DD' from a field that may be a
    BSON Date, an ISO string, or missing."""
    return {"$substrCP": [{"$toString": {"$ifNull": [f"${field}", ""]}}, 0, 10]}


def safe_day(raw):
    """Python equivalent: 'YYYY-MM-DD' from a BSON Date or ISO string; None if empty."""
    if raw is None:
        return None
    return raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]
