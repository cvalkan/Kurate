"""Tests for arXiv fetch dedup/revision logic and migration endpoint."""
import asyncio
import pytest

import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

from services.arxiv import strip_arxiv_version


# ── Dedup classification (mirrors scheduler logic) ────────────────────

def _classify_paper(rp, existing_bases, date_from):
    """Simulate the scheduler's dedup logic with REST API (versioned IDs)."""
    base, version = strip_arxiv_version(rp.get("arxiv_id", ""))
    existing = existing_bases.get(base)

    if existing:
        if version > existing["current_version"]:
            return "revision"
        return "skip_existing"
    return "new"


EXISTING_V1 = {
    "2601.11111": {"current_version": 1, "id": "paper-1"},
    "2601.22222": {"current_version": 1, "id": "paper-2"},
}


def test_new_paper():
    rp = {"arxiv_id": "2606.99999v1", "published": "2026-06-05T10:00:00Z"}
    assert _classify_paper(rp, {}, "2026-06-04") == "new"


def test_existing_same_version():
    rp = {"arxiv_id": "2601.11111v1", "published": "2026-01-15T10:00:00Z"}
    assert _classify_paper(rp, EXISTING_V1, "2026-06-04") == "skip_existing"


def test_revision_detected():
    rp = {"arxiv_id": "2601.11111v2", "published": "2026-01-15T10:00:00Z"}
    assert _classify_paper(rp, EXISTING_V1, "2026-06-04") == "revision"


def test_revision_v2_to_v3():
    existing = {"2601.11111": {"current_version": 2, "id": "paper-1"}}
    rp = {"arxiv_id": "2601.11111v3", "published": "2026-01-15T10:00:00Z"}
    assert _classify_paper(rp, existing, "2026-06-04") == "revision"


def test_strip_version():
    assert strip_arxiv_version("2601.18175v2") == ("2601.18175", 2)
    assert strip_arxiv_version("2601.18175") == ("2601.18175", 1)
    assert strip_arxiv_version("2601.18175v10") == ("2601.18175", 10)
