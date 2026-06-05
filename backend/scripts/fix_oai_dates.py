"""Migration: Fix OAI-PMH papers — repair 2026 dates + remove pre-2026 ghosts.

Phase 1 (REPAIR): Update the 1,083 papers from 2026 that have wrong dates/versions.
  - Uses /app/oai_dates_results.jsonl as the source of truth.
  - Updates papers.published, rankings.published with the correct REST API date.
  - Sets arxiv_id to versioned form (e.g. 2601.18175 -> 2601.18175v2),
    arxiv_id_base, current_version, is_latest_version on papers + rankings.

Phase 2 (REMOVE): Delete the 1,956 pre-2026 OAI papers that should never have been ingested.
  - Deletes paper docs, rankings, matches (where paper1_id or paper2_id is a ghost),
    and cleans up reading_lists, bookmarks, author_emails, x_handle_discoveries,
    tweet_drafts, rankings_repair_queue references.
  - Does NOT recalculate TrueSkill ratings for opponents (would require full replay;
    impact is small). A daily_stats rebuild is needed after Phase 2.

SAFETY:
  - Dry-run by default (?dry_run=true) — shows counts, does not mutate.
  - Phase 1 and Phase 2 can be run independently (?phase=1 or ?phase=2).
  - Idempotent: already-fixed papers are detected and skipped.
  - Batched deletes (500 at a time) to stay within Atlas 30s timeout.
  - Full audit log returned in the response.

Usage (via admin API):
  POST /api/admin/fix-oai-dates?dry_run=true           # preview both phases
  POST /api/admin/fix-oai-dates?dry_run=false&phase=1   # apply Phase 1 only
  POST /api/admin/fix-oai-dates?dry_run=false&phase=2   # apply Phase 2 only
  POST /api/admin/fix-oai-dates?dry_run=false           # apply both phases
"""
import asyncio
import json
import logging
import re
from collections import Counter
from pathlib import Path

from core.config import db

logger = logging.getLogger("oai_migration")

JSONL_PATH = Path("/app/oai_dates_results.jsonl")
OAI_JSON_PATH = Path("/app/oai_papers.json")

# Collections that can reference a paper_id
_CLEANUP_COLLECTIONS = [
    ("bookmarks", "paper_id"),
    ("author_emails", "paper_id"),
    ("x_handle_discoveries", "paper_id"),
    ("tweet_drafts", "paper_id"),
    ("rankings_repair_queue", "paper_id"),
]


def _load_date_corrections() -> dict:
    """Load the 1,083 correct dates from oai_dates_results.jsonl.
    Returns {arxiv_id: {rest_api_published, current_version, ...}}"""
    if not JSONL_PATH.exists():
        return {}
    corrections = {}
    for line in JSONL_PATH.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("rest_api_published"):
            corrections[r["arxiv_id"]] = r
    return corrections


def _load_older_paper_ids() -> set:
    """Load paper_ids for pre-2026 OAI papers from oai_papers.json."""
    if not OAI_JSON_PATH.exists():
        return set()
    with open(OAI_JSON_PATH) as f:
        data = json.load(f)
    return {
        p["paper_id"]
        for p in data.get("papers", [])
        if p.get("actual_year", 9999) < 2026
    }


async def _phase1_repair(dry_run: bool) -> dict:
    """Fix dates and versions for the 1,083 papers with 2026 actual dates."""
    corrections = _load_date_corrections()
    if not corrections:
        return {"phase": 1, "error": "oai_dates_results.jsonl not found or empty"}

    # Map arxiv_id -> paper in DB (paginated scan)
    to_fix = []
    already_ok = 0
    last_id = None

    while True:
        query = {"arxiv_id": {"$in": list(corrections.keys())}}
        if last_id:
            query["_id"] = {"$gt": last_id}
        batch = await db.papers.find(
            query,
            {"_id": 1, "id": 1, "arxiv_id": 1, "published": 1,
             "arxiv_id_base": 1, "current_version": 1, "title": 1},
        ).sort("_id", 1).limit(500).to_list(500)
        if not batch:
            break
        for doc in batch:
            aid = doc["arxiv_id"]
            corr = corrections.get(aid)
            if not corr:
                continue
            pub = str(doc.get("published", ""))
            # Already fixed? (published is a full ISO timestamp)
            if len(pub) > 10 and pub.startswith("20") and "T" in pub:
                already_ok += 1
                continue
            to_fix.append({
                "paper_id": doc["id"],
                "arxiv_id": aid,
                "old_published": pub,
                "new_published": corr["rest_api_published"],
                "new_version": corr.get("current_version"),  # e.g. "v2"
                "title": doc.get("title", "")[:60],
            })
        last_id = batch[-1]["_id"]

    if dry_run:
        version_dist = Counter(p["new_version"] for p in to_fix)
        return {
            "phase": 1, "dry_run": True,
            "papers_to_fix": len(to_fix),
            "already_fixed": already_ok,
            "corrections_loaded": len(corrections),
            "version_distribution": dict(sorted(version_dist.items())),
            "sample": to_fix[:15],
        }

    # Apply fixes in batches
    fixed_papers = 0
    fixed_rankings = 0
    for p in to_fix:
        paper_update = {"published": p["new_published"]}
        ranking_update = {"published": p["new_published"]}

        # Add versioning fields if we have a version
        ver_str = p.get("new_version")  # e.g. "v2"
        if ver_str:
            ver_num = int(ver_str.lstrip("v"))
            versioned_id = f"{p['arxiv_id']}{ver_str}"
            paper_update["arxiv_id"] = versioned_id
            paper_update["arxiv_id_base"] = p["arxiv_id"]
            paper_update["current_version"] = ver_num
            paper_update["is_latest_version"] = True
            ranking_update["arxiv_id"] = versioned_id

        result = await db.papers.update_one(
            {"id": p["paper_id"]}, {"$set": paper_update}
        )
        if result.modified_count:
            fixed_papers += 1

        result2 = await db.rankings.update_one(
            {"paper_id": p["paper_id"]}, {"$set": ranking_update}
        )
        if result2.modified_count:
            fixed_rankings += 1

    return {
        "phase": 1, "dry_run": False,
        "fixed_papers": fixed_papers,
        "fixed_rankings": fixed_rankings,
        "already_fixed": already_ok,
        "total_attempted": len(to_fix),
    }


async def _phase2_remove(dry_run: bool) -> dict:
    """Remove pre-2026 OAI ghost papers and all their matches/references."""
    ghost_ids = _load_older_paper_ids()
    if not ghost_ids:
        return {"phase": 2, "error": "oai_papers.json not found or no older papers"}

    # Verify how many actually exist in DB
    existing_count = await db.papers.count_documents(
        {"id": {"$in": list(ghost_ids)}}
    )
    existing_rankings = await db.rankings.count_documents(
        {"paper_id": {"$in": list(ghost_ids)}}
    )

    # Count matches to delete (paper1_id OR paper2_id is a ghost)
    ghost_list = list(ghost_ids)
    match_count = await db.matches.count_documents({
        "$or": [
            {"paper1_id": {"$in": ghost_list}},
            {"paper2_id": {"$in": ghost_list}},
        ]
    })

    # Count reading_list references
    reading_list_refs = await db.reading_lists.count_documents(
        {"paper_ids": {"$in": ghost_list}}
    )

    # Count other collection refs
    other_counts = {}
    for coll_name, field in _CLEANUP_COLLECTIONS:
        coll = db[coll_name]
        cnt = await coll.count_documents({field: {"$in": ghost_list}})
        if cnt > 0:
            other_counts[coll_name] = cnt

    if dry_run:
        # Category distribution of ghosts
        cat_dist = Counter()
        with open(OAI_JSON_PATH) as f:
            data = json.load(f)
        for p in data["papers"]:
            if p.get("actual_year", 9999) < 2026:
                cat_dist[p["category"]] += 1

        return {
            "phase": 2, "dry_run": True,
            "ghost_paper_ids": len(ghost_ids),
            "papers_in_db": existing_count,
            "rankings_in_db": existing_rankings,
            "matches_to_delete": match_count,
            "reading_lists_affected": reading_list_refs,
            "other_collections": other_counts,
            "category_distribution": dict(sorted(cat_dist.items())),
        }

    # ── Execute deletions in batches ──
    log = {}

    # 2a. Delete matches (batched by ghost_id chunks to avoid timeout)
    deleted_matches = 0
    for i in range(0, len(ghost_list), 200):
        chunk = ghost_list[i : i + 200]
        result = await db.matches.delete_many({
            "$or": [
                {"paper1_id": {"$in": chunk}},
                {"paper2_id": {"$in": chunk}},
            ]
        })
        deleted_matches += result.deleted_count
    log["deleted_matches"] = deleted_matches

    # 2b. Delete rankings
    result = await db.rankings.delete_many({"paper_id": {"$in": ghost_list}})
    log["deleted_rankings"] = result.deleted_count

    # 2c. Delete paper documents (batched)
    deleted_papers = 0
    for i in range(0, len(ghost_list), 500):
        chunk = ghost_list[i : i + 500]
        result = await db.papers.delete_many({"id": {"$in": chunk}})
        deleted_papers += result.deleted_count
    log["deleted_papers"] = deleted_papers

    # 2d. Clean reading_lists (pull ghost IDs from paper_ids arrays)
    if reading_list_refs > 0:
        result = await db.reading_lists.update_many(
            {"paper_ids": {"$in": ghost_list}},
            {"$pullAll": {"paper_ids": ghost_list}},
        )
        log["reading_lists_updated"] = result.modified_count

    # 2e. Clean other collections
    for coll_name, field in _CLEANUP_COLLECTIONS:
        coll = db[coll_name]
        result = await coll.delete_many({field: {"$in": ghost_list}})
        if result.deleted_count > 0:
            log[f"deleted_{coll_name}"] = result.deleted_count

    log["note"] = "Run POST /api/admin2/backfill to rebuild daily_stats after this migration"

    return {"phase": 2, "dry_run": False, **log}


async def run_migration(dry_run: bool = True, phase: int = 0) -> dict:
    """Run the OAI-PMH migration.
    phase=0: both phases, phase=1: repair only, phase=2: remove only."""
    results = {}
    if phase in (0, 1):
        results["phase1_repair"] = await _phase1_repair(dry_run)
    if phase in (0, 2):
        results["phase2_remove"] = await _phase2_remove(dry_run)
    return results
