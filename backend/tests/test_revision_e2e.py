"""End-to-end test for OAI-PMH fetch + revision detection.

Tests the unified dedup logic with mocked lookup functions.
No database needed — pure logic tests.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock

import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

from services.arxiv import strip_arxiv_version


def _simulate_dedup(raw_papers, existing_bases, date_from, lookup_fn):
    """Run the unified dedup logic (mirrors scheduler code exactly)."""

    async def run():
        results = []
        for rp in raw_papers:
            base, version = strip_arxiv_version(rp.get("arxiv_id", ""))
            existing = existing_bases.get(base)

            if existing:
                actual_version = None

                if version > existing["current_version"]:
                    actual_version = version
                elif rp.get("updated") and rp.get("created") and rp["updated"] != rp["created"]:
                    try:
                        lookup = await lookup_fn(base)
                        if lookup and lookup["version"] > existing["current_version"]:
                            actual_version = lookup["version"]
                            rp["arxiv_id"] = lookup["full_id"]
                            if lookup.get("published"):
                                rp["published"] = lookup["published"]
                    except Exception:
                        pass

                if actual_version:
                    results.append({
                        "action": "revision",
                        "base": base,
                        "new_version": actual_version,
                        "published": rp.get("published"),
                        "arxiv_id": rp.get("arxiv_id"),
                    })
                else:
                    results.append({"action": "skip_existing", "base": base})
                continue

            rp_created = rp.get("created", "")
            if date_from and rp_created and rp_created < date_from:
                results.append({"action": "skip_old", "base": base})
                continue

            results.append({"action": "new", "base": base, "published": rp.get("published")})

        return results

    return asyncio.get_event_loop().run_until_complete(run())


EXISTING_V1 = {
    "2601.11111": {"current_version": 1, "id": "paper-1", "arxiv_id": "2601.11111"},
    "2601.22222": {"current_version": 1, "id": "paper-2", "arxiv_id": "2601.22222"},
    "2601.33333": {"current_version": 1, "id": "paper-3", "arxiv_id": "2601.33333"},
}


def test_new_paper_via_oai():
    """Genuinely new paper (created recently, not in DB) → added."""
    raw = [{"arxiv_id": "2606.99999", "created": "2026-06-05", "updated": "2026-06-05",
            "published": "2026-06-05", "title": "Brand New Paper"}]
    results = _simulate_dedup(raw, {}, "2026-06-04", AsyncMock())
    assert results[0]["action"] == "new"
    assert results[0]["published"] == "2026-06-05"


def test_old_paper_not_in_db_skipped():
    """Old paper (2017) with metadata update, not in DB → skipped."""
    raw = [{"arxiv_id": "1711.10561", "created": "2017-11-28", "updated": "2026-06-04",
            "published": "2017-11-28"}]
    results = _simulate_dedup(raw, {}, "2026-06-04", AsyncMock())
    assert results[0]["action"] == "skip_old"


def test_revision_detected_via_oai_plus_api_lookup():
    """OAI shows updated≠created for tracked paper. API confirms v2.
    Revision detected with correct original published date."""
    raw = [{"arxiv_id": "2601.11111", "created": "2026-06-02", "updated": "2026-06-04",
            "published": "2026-06-02",  # WRONG (OAI gives revision date)
            "title": "Revised Paper"}]

    async def mock_lookup(base):
        return {"full_id": "2601.11111v2", "version": 2,
                "published": "2026-01-15T10:00:00Z"}  # CORRECT original date

    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", mock_lookup)
    r = results[0]
    assert r["action"] == "revision"
    assert r["new_version"] == 2
    assert r["arxiv_id"] == "2601.11111v2"
    assert r["published"] == "2026-01-15T10:00:00Z"  # Got corrected!


def test_metadata_only_update_skipped():
    """OAI shows updated≠created, but API says same version → metadata only, skip."""
    raw = [{"arxiv_id": "2601.22222", "created": "2017-11-28", "updated": "2026-06-04",
            "published": "2017-11-28"}]

    async def mock_lookup(base):
        return {"full_id": "2601.22222v1", "version": 1,
                "published": "2026-01-15T10:00:00Z"}

    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", mock_lookup)
    assert results[0]["action"] == "skip_existing"


def test_existing_paper_no_update_skipped():
    """Paper in DB, OAI returns it with created==updated → no change, skip."""
    raw = [{"arxiv_id": "2601.33333", "created": "2026-01-15", "updated": "2026-01-15",
            "published": "2026-01-15"}]
    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", AsyncMock())
    assert results[0]["action"] == "skip_existing"


def test_revision_via_rest_api_versioned_id():
    """REST API fallback delivers versioned ID (2601.11111v3) → revision, no lookup needed."""
    raw = [{"arxiv_id": "2601.11111v3", "published": "2026-01-15T10:00:00Z"}]
    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", AsyncMock())
    r = results[0]
    assert r["action"] == "revision"
    assert r["new_version"] == 3
    assert r["published"] == "2026-01-15T10:00:00Z"


def test_api_lookup_fails_skips_safely():
    """REST API lookup throws → paper skipped (not duplicated, not lost)."""
    raw = [{"arxiv_id": "2601.11111", "created": "2026-01-15", "updated": "2026-06-04",
            "published": "2026-01-15"}]

    async def failing_lookup(base):
        raise Exception("API timeout")

    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", failing_lookup)
    assert results[0]["action"] == "skip_existing"


def test_api_lookup_returns_none_skips():
    """REST API lookup returns None → paper skipped."""
    raw = [{"arxiv_id": "2601.11111", "created": "2026-01-15", "updated": "2026-06-04",
            "published": "2026-01-15"}]

    async def none_lookup(base):
        return None

    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", none_lookup)
    assert results[0]["action"] == "skip_existing"


def test_mixed_realistic_batch():
    """Realistic OAI-PMH batch: new + revision + metadata-only + old."""
    raw = [
        {"arxiv_id": "2606.88888", "created": "2026-06-05", "updated": "2026-06-05",
         "published": "2026-06-05", "title": "New"},
        {"arxiv_id": "2601.11111", "created": "2026-06-02", "updated": "2026-06-04",
         "published": "2026-06-02", "title": "Revised"},
        {"arxiv_id": "2601.22222", "created": "2017-11-28", "updated": "2026-06-04",
         "published": "2017-11-28", "title": "Metadata Only"},
        {"arxiv_id": "1711.10561", "created": "2017-11-28", "updated": "2026-06-04",
         "published": "2017-11-28", "title": "Old Not Tracked"},
        {"arxiv_id": "2601.33333", "created": "2026-01-15", "updated": "2026-01-15",
         "published": "2026-01-15", "title": "No Change"},
    ]

    async def mock_lookup(base):
        lookups = {
            "2601.11111": {"full_id": "2601.11111v2", "version": 2,
                           "published": "2026-01-15T10:00:00Z"},
            "2601.22222": {"full_id": "2601.22222v1", "version": 1,
                           "published": "2026-01-15T10:00:00Z"},
        }
        return lookups.get(base)

    results = _simulate_dedup(raw, EXISTING_V1, "2026-06-04", mock_lookup)
    actions = {r["base"]: r["action"] for r in results}

    assert actions["2606.88888"] == "new"
    assert actions["2601.11111"] == "revision"
    assert actions["2601.22222"] == "skip_existing"   # metadata only
    assert actions["1711.10561"] == "skip_old"         # old, not tracked
    assert actions["2601.33333"] == "skip_existing"    # no change

    # Verify revision details
    rev = [r for r in results if r["action"] == "revision"][0]
    assert rev["new_version"] == 2
    assert rev["arxiv_id"] == "2601.11111v2"
    assert rev["published"] == "2026-01-15T10:00:00Z"  # Corrected from OAI's 2026-06-02


def test_paper_at_v2_gets_v3():
    """Paper already at v2 in DB, OAI+API shows v3 → v2→v3 revision."""
    existing = {"2601.11111": {"current_version": 2, "id": "paper-1", "arxiv_id": "2601.11111v2"}}
    raw = [{"arxiv_id": "2601.11111", "created": "2026-06-02", "updated": "2026-06-05",
            "published": "2026-06-02"}]

    async def mock_lookup(base):
        return {"full_id": "2601.11111v3", "version": 3,
                "published": "2026-01-15T10:00:00Z"}

    results = _simulate_dedup(raw, existing, "2026-06-04", mock_lookup)
    assert results[0]["action"] == "revision"
    assert results[0]["new_version"] == 3
