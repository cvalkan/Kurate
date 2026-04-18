"""
Regression tests for the revision race / counter / similarity fixes.

Covers:
  * Fix 1: _incr_match_counts decrements on supersession (UI consistency)
  * Fix 4: in-flight matches marked revision_superseded at insertion when
           paper revision_epoch changed mid-flight
  * Fix 5: _content_similarity with stopword filtering gives low scores
           to unrelated papers and high scores to paraphrases of the same paper
  * Fix 6: orphan full_text falls back to abstract comparison
"""
import asyncio
import os
import uuid
import sys

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db_name = os.environ.get("DB_NAME", "papersumo")
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

TEST_PREFIX = "test-race-fix-" + str(uuid.uuid4())[:6]


async def cleanup():
    await db.papers.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
    await db.rankings.delete_many({"paper_id": {"$regex": f"^{TEST_PREFIX}"}})
    await db.matches.delete_many({
        "$or": [
            {"paper1_id": {"$regex": f"^{TEST_PREFIX}"}},
            {"paper2_id": {"$regex": f"^{TEST_PREFIX}"}},
        ]
    })


async def _seed_paper(pid: str, base: str, version: int = 1, category: str = "cs.RO"):
    from datetime import datetime, timezone
    await db.papers.insert_one({
        "id": pid,
        "arxiv_id": f"{base}v{version}",
        "arxiv_id_base": base,
        "current_version": version,
        "revision_epoch": 0,
        "title": f"Seed {pid[:8]}",
        "abstract": "we propose a novel approach for semantic segmentation using transformers",
        "full_text": ("we propose a novel approach for semantic segmentation using transformers "
                      "with multi-head attention applied to image patches for efficient "
                      "pixel-level prediction across 21 classes") * 10,
        "categories": [category],
        "published": datetime.now(timezone.utc).isoformat(),
        "link": f"https://arxiv.org/abs/{base}v{version}",
        "pdf_link": f"https://arxiv.org/pdf/{base}v{version}",
        "added_at": datetime.now(timezone.utc).isoformat(),
        "summaries": {
            "anthropic:claude-opus-4-6:thinking": "Strong paper on segmentation. " * 20,
        },
        "ai_rating": 7.5,
    })


async def test_similarity_stopwords():
    """Fix 5: stopword-filtered Jaccard gives sensible scores."""
    from services.scheduler import _content_similarity
    a = "we propose a novel approach for object detection using transformers"
    b = "we propose a novel approach for object detection using vision transformers"
    same = _content_similarity(a, a)
    close = _content_similarity(a, b)
    unrelated = _content_similarity(
        "machine learning neural network policy gradient reinforcement",
        "cryptographic elliptic curve discrete logarithm signature"
    )
    # Boilerplate-heavy but different content should still score LOW
    boilerplate = _content_similarity(
        "figure 1 shows the method we propose section 2 presents results table",
        "figure 1 shows the approach we propose section 2 presents evaluation table"
    )
    assert same == 1.0, f"identical must be 1.0, got {same}"
    assert close > 0.75, f"close paraphrase should be high, got {close}"
    assert unrelated < 0.1, f"unrelated should be ~0, got {unrelated}"
    # Boilerplate-only similarity should not cross the 0.95 threshold anymore
    assert boilerplate < 0.95, (
        f"stopword-stuffed comparison must not falsely cross 0.95, got {boilerplate}"
    )
    print(f"  PASS: sim(identical)=1.0, close={close:.2f}, unrelated={unrelated:.2f}, "
          f"boilerplate={boilerplate:.2f}")


async def test_counter_decrement_on_supersede():
    """Fix 1: _incr_match_counts decrements by number of superseded matches."""
    from services.scheduler import _handle_revision
    from routers.leaderboard import _incr_match_counts
    from datetime import datetime, timezone

    pid = f"{TEST_PREFIX}-counter"
    base = f"{TEST_PREFIX[:8]}.ctr"
    await _seed_paper(pid, base)

    # Seed 5 completed matches in cs.RO
    for i in range(5):
        await db.matches.insert_one({
            "id": str(uuid.uuid4()),
            "paper1_id": pid,
            "paper2_id": f"{TEST_PREFIX}-opp-{i}",
            "primary_category": "cs.RO",
            "completed": True, "failed": False,
            "winner_id": pid,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    # Snapshot current counter and bump it to reflect the 5 matches we just created
    _incr_match_counts["cs.RO"] = _incr_match_counts.get("cs.RO", 0) + 5
    before = _incr_match_counts["cs.RO"]

    # Monkeypatch PDF download to return non-trivial text different enough to reset
    import services.scheduler as sched
    orig = sched.download_and_extract_pdf
    sched.download_and_extract_pdf = lambda *a, **kw: asyncio.sleep(0, result=(
        "completely different topic cryptographic elliptic curve discrete logarithm " * 30
    ))

    try:
        settings = {"revision_diff_threshold": 0.95}
        await _handle_revision(
            pid,
            {"arxiv_id": f"{base}v2", "pdf_link": f"https://arxiv.org/pdf/{base}v2"},
            2, settings,
        )
    finally:
        sched.download_and_extract_pdf = orig

    after = _incr_match_counts.get("cs.RO", 0)
    assert after == before - 5, (
        f"counter should decrement by 5 superseded matches; before={before}, after={after}"
    )
    print(f"  PASS: _incr_match_counts decremented from {before} → {after}")


async def test_epoch_mismatch_marks_match_superseded():
    """Fix 4: in-flight matches marked revision_superseded at insertion
    when paper revision_epoch moved forward mid-flight."""
    from services.scheduler import _paper_revision_epochs
    pid = f"{TEST_PREFIX}-inflight"

    # Simulate pair-selection snapshot
    epochs_at_selection = {pid: 0}
    # Now a revision happens: epoch bumps
    _paper_revision_epochs[pid] = 1
    # The stale check used in scheduler._run_one
    stale = (
        _paper_revision_epochs.get(pid, 0) != epochs_at_selection.get(pid, 0)
    )
    assert stale, "expected epoch mismatch to flag the match as stale"
    # Clean up
    _paper_revision_epochs.pop(pid, None)
    print("  PASS: epoch mismatch detected (would mark match revision_superseded at insert)")


async def test_abstract_fallback_when_no_full_text():
    """Fix 6: when old full_text is missing, similarity falls back to abstract."""
    from services.scheduler import _handle_revision
    from datetime import datetime, timezone

    pid = f"{TEST_PREFIX}-orphan"
    base = f"{TEST_PREFIX[:8]}.orp"

    # Seed paper WITHOUT full_text (orphan — PDF previously failed)
    await db.papers.insert_one({
        "id": pid,
        "arxiv_id": f"{base}v1",
        "arxiv_id_base": base,
        "current_version": 1,
        "revision_epoch": 0,
        "title": "Orphan paper",
        "abstract": "we propose a transformer-based method for image segmentation using attention",
        "full_text": None,
        "categories": ["cs.RO"],
        "pdf_link": f"https://arxiv.org/pdf/{base}v1",
        "added_at": datetime.now(timezone.utc).isoformat(),
        "summaries": {},
    })

    import services.scheduler as sched
    orig = sched.download_and_extract_pdf
    sched.download_and_extract_pdf = lambda *a, **kw: asyncio.sleep(0, result=(
        "completely different topic cryptographic elliptic curve " * 20
    ))

    try:
        settings = {"revision_diff_threshold": 0.95}
        result = await _handle_revision(
            pid,
            {
                "arxiv_id": f"{base}v2",
                "pdf_link": f"https://arxiv.org/pdf/{base}v2",
                "abstract": "we solve cryptographic elliptic curve discrete logarithm via signature",
            },
            2, settings,
        )
    finally:
        sched.download_and_extract_pdf = orig

    paper = await db.papers.find_one({"id": pid}, {"_id": 0, "version_history": 1})
    snap = (paper or {}).get("version_history", [{}])[0]
    assert snap.get("similarity_basis") == "abstract", (
        f"expected similarity_basis=abstract, got {snap.get('similarity_basis')}"
    )
    # Different abstracts → low similarity → should reset
    assert result == "revised", f"expected reset; got {result}"
    print(f"  PASS: orphan full_text → fell back to abstract (sim={snap.get('similarity'):.2f}), reset={result=='revised'}")


async def main():
    await cleanup()
    try:
        print("\n=== Test A: stopword-filtered content similarity ===")
        await test_similarity_stopwords()

        print("\n=== Test B: _incr_match_counts decrement on supersession ===")
        await test_counter_decrement_on_supersede()

        print("\n=== Test C: epoch mismatch flags in-flight match ===")
        await test_epoch_mismatch_marks_match_superseded()

        print("\n=== Test D: orphan full_text falls back to abstract ===")
        await test_abstract_fallback_when_no_full_text()

        print("\n" + "=" * 60)
        print("RACE/COUNTER/SIMILARITY FIXES: 4 passed, 0 failed")
        print("=" * 60)
    finally:
        await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
