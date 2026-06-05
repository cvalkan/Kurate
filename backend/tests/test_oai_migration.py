"""Tests for OAI-PMH fetch + revision detection + date handling.

Covers:
1. New paper via OAI-PMH → added with correct created date
2. Old paper with metadata update → skipped (created < date_from)
3. Paper in DB + OAI-PMH updated≠created + API says same version → skip (metadata-only)
4. Paper in DB + OAI-PMH updated≠created + API says new version → revision detected
5. Paper via REST API with version suffix → revision detected
6. lookup_arxiv_version returns correct version numbers
"""
import asyncio
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

# We need to set up env before importing
import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

from services.arxiv import strip_arxiv_version, lookup_arxiv_version, _parse_oai_arxiv_response
from core.config import db


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Test OAI-PMH parser ──────────────────────────────────────────────

def test_oai_parser_extracts_created_and_updated():
    """OAI-PMH parser should return created, updated, and published=created."""
    xml = """<?xml version="1.0"?>
    <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
    <ListRecords>
    <record>
        <header><identifier>oai:arXiv.org:2601.18175</identifier>
        <datestamp>2026-06-02</datestamp></header>
        <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
            <id>2601.18175</id>
            <created>2026-01-26</created>
            <updated>2026-06-02</updated>
            <authors><author><keyname>Russo</keyname><forenames>Daniel</forenames></author></authors>
            <title>Success Conditioning</title>
            <categories>cs.AI cs.LG</categories>
            <abstract>A test abstract.</abstract>
        </arXiv>
        </metadata>
    </record>
    </ListRecords>
    </OAI-PMH>"""

    papers, token = _parse_oai_arxiv_response(xml)
    assert len(papers) == 1
    p = papers[0]
    assert p["arxiv_id"] == "2601.18175"
    assert p["created"] == "2026-01-26"
    assert p["updated"] == "2026-06-02"
    assert p["published"] == "2026-01-26"  # Must use created, NOT updated
    assert p["categories"] == ["cs.AI", "cs.LG"]
    assert p["title"] == "Success Conditioning"


def test_oai_parser_no_update_field():
    """Paper with no <updated> field — created only."""
    xml = """<?xml version="1.0"?>
    <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
    <ListRecords>
    <record>
        <header><identifier>oai:arXiv.org:2606.12345</identifier>
        <datestamp>2026-06-05</datestamp></header>
        <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
            <id>2606.12345</id>
            <created>2026-06-05</created>
            <authors><author><keyname>Test</keyname></author></authors>
            <title>New Paper</title>
            <categories>cs.RO</categories>
            <abstract>Abstract.</abstract>
        </arXiv>
        </metadata>
    </record>
    </ListRecords>
    </OAI-PMH>"""

    papers, token = _parse_oai_arxiv_response(xml)
    assert len(papers) == 1
    p = papers[0]
    assert p["published"] == "2026-06-05"
    assert p["created"] == "2026-06-05"
    assert p["updated"] == ""  # No update


def test_oai_parser_old_paper_metadata_update():
    """2017 paper with metadata update — created should be 2017."""
    xml = """<?xml version="1.0"?>
    <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
    <ListRecords>
    <record>
        <header><identifier>oai:arXiv.org:1711.10561</identifier>
        <datestamp>2026-06-04</datestamp></header>
        <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
            <id>1711.10561</id>
            <created>2017-11-28</created>
            <updated>2026-06-04</updated>
            <authors><author><keyname>Raissi</keyname></author></authors>
            <title>Physics Informed Deep Learning</title>
            <categories>cs.AI cs.LG</categories>
            <abstract>Old paper.</abstract>
        </arXiv>
        </metadata>
    </record>
    </ListRecords>
    </OAI-PMH>"""

    papers, token = _parse_oai_arxiv_response(xml)
    assert len(papers) == 1
    p = papers[0]
    assert p["published"] == "2017-11-28"  # NOT 2026-06-04
    assert p["created"] == "2017-11-28"
    assert p["updated"] == "2026-06-04"


# ── Test dedup classification logic (unit test, no DB) ────────────────

def _classify_paper(rp, existing_bases, date_from, lookup_result=None):
    """Simulate the scheduler's dedup classification logic.
    Returns: 'new', 'skip_old', 'skip_exists', 'revision', 'metadata_only', 'lookup_failed'"""
    base, version = strip_arxiv_version(rp.get("arxiv_id", ""))
    existing = existing_bases.get(base)

    if existing:
        if version > existing["current_version"]:
            return "revision"
        elif rp.get("updated") and rp.get("created") and rp["updated"] != rp["created"]:
            if lookup_result:
                actual_version = lookup_result["version"]
                if actual_version > existing["current_version"]:
                    return "revision"
                return "metadata_only"
            return "lookup_failed"
        return "skip_exists"
    else:
        rp_created = rp.get("created", "")
        if date_from and rp_created and rp_created < date_from:
            return "skip_old"
        return "new"


def test_classify_new_paper():
    rp = {"arxiv_id": "2606.12345", "created": "2026-06-05", "updated": "2026-06-05"}
    assert _classify_paper(rp, {}, "2026-06-04") == "new"


def test_classify_old_paper_not_in_db():
    rp = {"arxiv_id": "1711.10561", "created": "2017-11-28", "updated": "2026-06-04"}
    assert _classify_paper(rp, {}, "2026-06-04") == "skip_old"


def test_classify_existing_same_version():
    rp = {"arxiv_id": "2601.18175", "created": "2026-01-26", "updated": "2026-01-26"}
    existing = {"2601.18175": {"current_version": 1, "id": "abc"}}
    assert _classify_paper(rp, existing, "2026-06-04") == "skip_exists"


def test_classify_revision_via_rest_api():
    """REST API returns versioned ID like 2601.18175v2."""
    rp = {"arxiv_id": "2601.18175v2", "published": "2026-06-02T19:09:34Z"}
    existing = {"2601.18175": {"current_version": 1, "id": "abc"}}
    assert _classify_paper(rp, existing, "2026-06-04") == "revision"


def test_classify_revision_via_oai_with_lookup():
    """OAI-PMH shows updated≠created, API lookup confirms new version."""
    rp = {"arxiv_id": "2601.18175", "created": "2026-01-26", "updated": "2026-06-02"}
    existing = {"2601.18175": {"current_version": 1, "id": "abc"}}
    lookup = {"full_id": "2601.18175v2", "version": 2, "published": "2026-01-26T05:54:39Z"}
    assert _classify_paper(rp, existing, "2026-06-04", lookup_result=lookup) == "revision"


def test_classify_metadata_only_via_oai_with_lookup():
    """OAI-PMH shows updated≠created, but API lookup says same version — metadata only."""
    rp = {"arxiv_id": "1711.10561", "created": "2017-11-28", "updated": "2026-06-04"}
    existing = {"1711.10561": {"current_version": 1, "id": "abc"}}
    lookup = {"full_id": "1711.10561v1", "version": 1, "published": "2017-11-28T21:21:59Z"}
    assert _classify_paper(rp, existing, "2026-06-04", lookup_result=lookup) == "metadata_only"


# ── Test lookup_arxiv_version (live, against real arXiv API) ──────────

@pytest.mark.skipif(not os.environ.get("RUN_LIVE_TESTS"), reason="Set RUN_LIVE_TESTS=1 for live API tests")
def test_lookup_version_live():
    """Live test against arXiv API — verifies version + published extraction."""
    async def run():
        # Paper with v2
        result = await lookup_arxiv_version("2601.18175")
        assert result is not None
        assert result["version"] == 2
        assert result["full_id"] == "2601.18175v2"
        assert result["published"].startswith("2026-01-26")  # Original v1 date

        # Paper with only v1
        result = await lookup_arxiv_version("1711.10561")
        assert result is not None
        assert result["version"] == 1
        assert result["published"].startswith("2017-11-28")

    asyncio.get_event_loop().run_until_complete(run())


# ── Test migration logic (against preview DB) ─────────────────────────

@pytest.fixture
def test_papers():
    """Create test papers in the DB to simulate OAI-PMH ingestion issues."""
    papers = []

    async def setup():
        # 1. Legitimate new paper with correct OAI date
        papers.append({
            "id": f"test-oai-good-{uuid.uuid4().hex[:8]}",
            "arxiv_id": "2606.09999",
            "arxiv_id_base": "2606.09999",
            "title": "Test Good OAI Paper",
            "authors": ["Test Author"],
            "categories": ["cs.AI"],
            "published": "2026-06-05",  # Short OAI date but correct (matches arxiv_id prefix)
            "added_at": "2026-06-05T10:00:00+00:00",
            "current_version": 1,
            "is_latest_version": True,
        })

        # 2. Paper with WRONG published date (updated used instead of created)
        papers.append({
            "id": f"test-oai-wrong-date-{uuid.uuid4().hex[:8]}",
            "arxiv_id": "2601.18175",
            "arxiv_id_base": "2601.18175",
            "title": "Test Wrong Date Paper",
            "authors": ["Daniel Russo"],
            "categories": ["cs.AI"],
            "published": "2026-06-04",  # WRONG — should be 2026-01-26
            "added_at": "2026-06-04T22:00:00+00:00",
            "current_version": 1,
            "is_latest_version": True,
        })

        # 3. Old paper that shouldn't be in DB at all (2017)
        papers.append({
            "id": f"test-oai-old-{uuid.uuid4().hex[:8]}",
            "arxiv_id": "1711.10561",
            "arxiv_id_base": "1711.10561",
            "title": "Physics Informed Deep Learning",
            "authors": ["Maziar Raissi"],
            "categories": ["cs.AI"],
            "published": "2026-06-04",  # WRONG — created 2017
            "added_at": "2026-06-04T22:00:00+00:00",
            "current_version": 1,
            "is_latest_version": True,
        })

        # 4. Normal REST API paper (should NOT be touched)
        papers.append({
            "id": f"test-rest-ok-{uuid.uuid4().hex[:8]}",
            "arxiv_id": "2606.02386v1",
            "arxiv_id_base": "2606.02386",
            "title": "Test Normal REST Paper",
            "authors": ["Test Author"],
            "categories": ["cs.AI"],
            "published": "2026-06-01T15:35:02Z",  # Full ISO date
            "added_at": "2026-06-01T15:35:02+00:00",
            "current_version": 1,
            "is_latest_version": True,
        })

        for p in papers:
            await db.papers.update_one({"id": p["id"]}, {"$set": p}, upsert=True)

        return papers

    created = asyncio.get_event_loop().run_until_complete(setup())

    yield created

    # Cleanup
    async def cleanup():
        for p in papers:
            await db.papers.delete_one({"id": p["id"]})
    asyncio.get_event_loop().run_until_complete(cleanup())


def test_identify_affected_papers(test_papers):
    """Identify papers with wrong OAI-PMH dates."""

    async def run():
        affected = []
        async for doc in db.papers.find(
            {"id": {"$in": [p["id"] for p in test_papers]}},
            {"_id": 0, "id": 1, "arxiv_id": 1, "published": 1},
        ):
            pub = doc.get("published", "")
            arxiv_id = doc.get("arxiv_id", "")

            # OAI papers have short dates (10 chars) and no version suffix
            is_oai = len(pub) <= 10 and "v" not in arxiv_id

            if is_oai:
                # Extract year/month from arxiv_id prefix
                prefix = arxiv_id.split(".")[0] if "." in arxiv_id else ""
                if len(prefix) == 4:  # YYMM format
                    yy, mm = int(prefix[:2]), int(prefix[2:])
                    arxiv_year = 2000 + yy if yy < 50 else 1900 + yy
                    pub_year = int(pub[:4]) if len(pub) >= 4 else 0

                    if arxiv_year < 2025:
                        affected.append({"id": doc["id"], "reason": "old_paper", "arxiv_id": arxiv_id})
                    elif abs(pub_year * 12 + int(pub[5:7]) - (arxiv_year * 12 + mm)) > 2:
                        affected.append({"id": doc["id"], "reason": "wrong_date", "arxiv_id": arxiv_id})

        old = [a for a in affected if a["reason"] == "old_paper"]
        wrong = [a for a in affected if a["reason"] == "wrong_date"]

        # 1711.10561 should be flagged as old_paper
        assert any(a["arxiv_id"] == "1711.10561" for a in old), f"1711.10561 not flagged as old: {old}"

        # 2601.18175 with pub=2026-06-04 should be flagged as wrong_date
        # (arxiv_id says Jan 2026, published says June 2026)
        assert any(a["arxiv_id"] == "2601.18175" for a in wrong), f"2601.18175 not flagged as wrong: {wrong}"

        # 2606.09999 should NOT be affected (correct date)
        assert not any(a["arxiv_id"] == "2606.09999" for a in affected), "2606.09999 wrongly flagged"

        # REST API paper should NOT be affected
        assert not any(a["arxiv_id"] == "2606.02386v1" for a in affected), "REST paper wrongly flagged"

        return affected

    result = asyncio.get_event_loop().run_until_complete(run())
    print(f"Affected papers: {result}")
