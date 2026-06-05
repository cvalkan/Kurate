"""Tests for the OAI-PMH migration script (fix_oai_dates.py).

Seeds fake OAI papers + matches on the preview DB, runs the migration,
and verifies that Phase 1 repairs dates/versions and Phase 2 removes ghosts
without leaving orphan references.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_oai_migration")
os.environ.setdefault("ADMIN_PASSWORD", "papersumo2025")

@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    database = client["test_oai_migration"]
    for coll_name in await database.list_collection_names():
        await database[coll_name].drop()
    yield database
    for coll_name in await database.list_collection_names():
        await database[coll_name].drop()
    client.close()


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirect the migration module's file paths to temp dir so tests never
    clobber the real /app/oai_dates_results.jsonl or oai_papers.json."""
    import scripts.fix_oai_dates as migration
    monkeypatch.setattr(migration, "JSONL_PATH", tmp_path / "results.jsonl")
    monkeypatch.setattr(migration, "OAI_JSON_PATH", tmp_path / "oai.json")


def _make_paper(arxiv_id, paper_id, category, published, title="Test"):
    return {
        "id": paper_id,
        "arxiv_id": arxiv_id,
        "categories": [category],
        "published": published,
        "title": title,
        "authors": ["Author"],
        "link": f"https://arxiv.org/abs/{arxiv_id}",
        "summaries": {},
        "full_text": None,
    }


def _make_ranking(paper_id, category, arxiv_id, published):
    return {
        "paper_id": paper_id,
        "category": category,
        "arxiv_id": arxiv_id,
        "published": published,
        "wins": 5, "losses": 3, "comparisons": 8,
        "ts_mu": 25.0, "ts_sigma": 8.0, "ts_score": 100,
        "title": "Test",
    }


def _make_match(paper1_id, paper2_id, category):
    return {
        "id": str(uuid.uuid4()),
        "paper1_id": paper1_id,
        "paper2_id": paper2_id,
        "primary_category": category,
        "completed": True,
        "failed": False,
        "winner_id": paper1_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def seed_jsonl():
    """Create a minimal JSONL with corrections for the 2026 test papers."""
    return [
        json.dumps({
            "arxiv_id": "2601.00001",
            "paper_id": "p-2026-a",
            "category": "cs.AI",
            "published_in_db": "2026-06-04",
            "rest_api_published": "2026-01-15T10:00:00Z",
            "rest_api_updated": "2026-06-03T10:00:00Z",
            "current_version": "v2",
            "title": "Paper A 2026",
        }),
        json.dumps({
            "arxiv_id": "2601.00002",
            "paper_id": "p-2026-b",
            "category": "cs.LG",
            "published_in_db": "2026-06-05",
            "rest_api_published": "2026-01-20T14:30:00Z",
            "rest_api_updated": "2026-06-04T12:00:00Z",
            "current_version": "v3",
            "title": "Paper B 2026",
        }),
    ]


@pytest.fixture
def seed_oai_json():
    """Create a minimal oai_papers.json with a ghost paper."""
    return {
        "total_papers_in_leaderboards": 100,
        "total_oai_papers": 3,
        "papers": [
            {
                "arxiv_id": "2601.00001", "paper_id": "p-2026-a",
                "category": "cs.AI", "published_in_db": "2026-06-04",
                "actual_year": 2026, "actual_month": 1,
                "month_diff": 5, "wrong_date": True,
                "title": "Paper A 2026", "comparisons": 8,
            },
            {
                "arxiv_id": "2601.00002", "paper_id": "p-2026-b",
                "category": "cs.LG", "published_in_db": "2026-06-05",
                "actual_year": 2026, "actual_month": 1,
                "month_diff": 5, "wrong_date": True,
                "title": "Paper B 2026", "comparisons": 8,
            },
            {
                "arxiv_id": "1401.00001", "paper_id": "p-ghost-1",
                "category": "cs.AI", "published_in_db": "2026-06-03",
                "actual_year": 2014, "actual_month": 1,
                "month_diff": 149, "wrong_date": True,
                "title": "Ghost Paper 2014", "comparisons": 5,
            },
        ]
    }


@pytest.mark.asyncio
async def test_phase1_dry_run(db, seed_jsonl, seed_oai_json, monkeypatch):
    """Phase 1 dry run should report papers to fix without mutating."""
    await db.papers.insert_many([
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-06-04"),
        _make_paper("2601.00002", "p-2026-b", "cs.LG", "2026-06-05"),
    ])
    await db.rankings.insert_many([
        _make_ranking("p-2026-a", "cs.AI", "2601.00001", "2026-06-04"),
        _make_ranking("p-2026-b", "cs.LG", "2601.00002", "2026-06-05"),
    ])

    import scripts.fix_oai_dates as migration
    migration.JSONL_PATH.write_text("\n".join(seed_jsonl) + "\n")
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    result = await migration._phase1_repair(dry_run=True)
    assert result["dry_run"] is True
    assert result["papers_to_fix"] == 2
    assert result["already_fixed"] == 0

    p = await db.papers.find_one({"id": "p-2026-a"})
    assert p["published"] == "2026-06-04"


@pytest.mark.asyncio
async def test_phase1_apply(db, seed_jsonl, seed_oai_json, monkeypatch):
    """Phase 1 apply should fix dates and add versioning."""
    await db.papers.insert_many([
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-06-04"),
        _make_paper("2601.00002", "p-2026-b", "cs.LG", "2026-06-05"),
    ])
    await db.rankings.insert_many([
        _make_ranking("p-2026-a", "cs.AI", "2601.00001", "2026-06-04"),
        _make_ranking("p-2026-b", "cs.LG", "2601.00002", "2026-06-05"),
    ])

    import scripts.fix_oai_dates as migration
    migration.JSONL_PATH.write_text("\n".join(seed_jsonl) + "\n")
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    result = await migration._phase1_repair(dry_run=False)
    assert result["fixed_papers"] == 2
    assert result["fixed_rankings"] == 2

    # Verify paper A
    pa = await db.papers.find_one({"id": "p-2026-a"})
    assert pa["published"] == "2026-01-15T10:00:00Z"
    assert pa["arxiv_id"] == "2601.00001v2"
    assert pa["arxiv_id_base"] == "2601.00001"
    assert pa["current_version"] == 2
    assert pa["is_latest_version"] is True

    # Verify paper B
    pb = await db.papers.find_one({"id": "p-2026-b"})
    assert pb["published"] == "2026-01-20T14:30:00Z"
    assert pb["arxiv_id"] == "2601.00002v3"
    assert pb["current_version"] == 3

    # Verify rankings updated
    ra = await db.rankings.find_one({"paper_id": "p-2026-a"})
    assert ra["published"] == "2026-01-15T10:00:00Z"
    assert ra["arxiv_id"] == "2601.00001v2"

    rb = await db.rankings.find_one({"paper_id": "p-2026-b"})
    assert rb["published"] == "2026-01-20T14:30:00Z"


@pytest.mark.asyncio
async def test_phase1_idempotent(db, seed_jsonl, seed_oai_json, monkeypatch):
    """Running Phase 1 twice: second run finds nothing (arxiv_id changed)."""
    await db.papers.insert_one(
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-06-04")
    )
    await db.rankings.insert_one(
        _make_ranking("p-2026-a", "cs.AI", "2601.00001", "2026-06-04")
    )

    import scripts.fix_oai_dates as migration
    migration.JSONL_PATH.write_text(seed_jsonl[0] + "\n")
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    r1 = await migration._phase1_repair(dry_run=False)
    assert r1["fixed_papers"] == 1

    # Second run: arxiv_id is now "2601.00001v2", $in on bare "2601.00001" won't match
    r2 = await migration._phase1_repair(dry_run=False)
    assert r2["total_attempted"] == 0


@pytest.mark.asyncio
async def test_phase2_dry_run(db, seed_oai_json, monkeypatch):
    """Phase 2 dry run should count ghosts without deleting."""
    await db.papers.insert_many([
        _make_paper("1401.00001", "p-ghost-1", "cs.AI", "2026-06-03", "Ghost"),
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-01-15T10:00:00Z"),
    ])
    await db.rankings.insert_one(
        _make_ranking("p-ghost-1", "cs.AI", "1401.00001", "2026-06-03")
    )
    await db.matches.insert_one(
        _make_match("p-ghost-1", "p-2026-a", "cs.AI")
    )

    import scripts.fix_oai_dates as migration
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    result = await migration._phase2_remove(dry_run=True)
    assert result["dry_run"] is True
    assert result["papers_in_db"] == 1
    assert result["rankings_in_db"] == 1
    assert result["matches_to_delete"] == 1

    # Verify nothing deleted
    assert await db.papers.count_documents({}) == 2
    assert await db.matches.count_documents({}) == 1


@pytest.mark.asyncio
async def test_phase2_apply(db, seed_oai_json, monkeypatch):
    """Phase 2 apply should delete ghosts, their matches, and cleanup refs."""
    await db.papers.insert_many([
        _make_paper("1401.00001", "p-ghost-1", "cs.AI", "2026-06-03", "Ghost"),
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-01-15T10:00:00Z", "Legit"),
    ])
    await db.rankings.insert_many([
        _make_ranking("p-ghost-1", "cs.AI", "1401.00001", "2026-06-03"),
        _make_ranking("p-2026-a", "cs.AI", "2601.00001", "2026-01-15"),
    ])
    await db.matches.insert_many([
        _make_match("p-ghost-1", "p-2026-a", "cs.AI"),
        _make_match("p-2026-a", "p-2026-a", "cs.AI"),
    ])
    await db.reading_lists.insert_one({
        "list_id": "rl-1", "user_id": "u1",
        "paper_ids": ["p-ghost-1", "p-2026-a"],
    })
    await db.bookmarks.insert_one({"paper_id": "p-ghost-1", "user_id": "u1"})

    import scripts.fix_oai_dates as migration
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    result = await migration._phase2_remove(dry_run=False)
    assert result["deleted_papers"] == 1
    assert result["deleted_rankings"] == 1
    assert result["deleted_matches"] == 1

    # Ghost paper gone, legit paper still exists
    assert await db.papers.count_documents({"id": "p-ghost-1"}) == 0
    assert await db.papers.count_documents({"id": "p-2026-a"}) == 1
    # Legit ranking still exists
    assert await db.rankings.count_documents({"paper_id": "p-2026-a"}) == 1
    assert await db.rankings.count_documents({"paper_id": "p-ghost-1"}) == 0
    # Only legit match remains
    assert await db.matches.count_documents({}) == 1
    # Reading list cleaned
    rl = await db.reading_lists.find_one({"list_id": "rl-1"})
    assert rl["paper_ids"] == ["p-2026-a"]
    # Bookmark deleted
    assert await db.bookmarks.count_documents({"paper_id": "p-ghost-1"}) == 0


@pytest.mark.asyncio
async def test_full_migration(db, seed_jsonl, seed_oai_json, monkeypatch):
    """Full migration: Phase 1 + Phase 2 in sequence."""
    await db.papers.insert_many([
        _make_paper("2601.00001", "p-2026-a", "cs.AI", "2026-06-04"),
        _make_paper("2601.00002", "p-2026-b", "cs.LG", "2026-06-05"),
        _make_paper("1401.00001", "p-ghost-1", "cs.AI", "2026-06-03", "Ghost"),
    ])
    await db.rankings.insert_many([
        _make_ranking("p-2026-a", "cs.AI", "2601.00001", "2026-06-04"),
        _make_ranking("p-2026-b", "cs.LG", "2601.00002", "2026-06-05"),
        _make_ranking("p-ghost-1", "cs.AI", "1401.00001", "2026-06-03"),
    ])
    await db.matches.insert_many([
        _make_match("p-ghost-1", "p-2026-a", "cs.AI"),
        _make_match("p-2026-a", "p-2026-b", "cs.LG"),
    ])

    import scripts.fix_oai_dates as migration
    migration.JSONL_PATH.write_text("\n".join(seed_jsonl) + "\n")
    migration.OAI_JSON_PATH.write_text(json.dumps(seed_oai_json))
    monkeypatch.setattr(migration, "db", db)

    result = await migration.run_migration(dry_run=False, phase=0)

    # Phase 1: dates fixed
    assert result["phase1_repair"]["fixed_papers"] == 2
    pa = await db.papers.find_one({"id": "p-2026-a"})
    assert pa["published"] == "2026-01-15T10:00:00Z"
    assert pa["arxiv_id"] == "2601.00001v2"

    # Phase 2: ghost removed
    assert result["phase2_remove"]["deleted_papers"] == 1
    assert result["phase2_remove"]["deleted_matches"] == 1
    assert await db.papers.count_documents({}) == 2
    assert await db.matches.count_documents({}) == 1
