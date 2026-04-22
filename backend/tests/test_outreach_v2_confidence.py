"""Unit + integration tests for P0+P1 confidence upgrade and
/confidence-preview, /recompute-confidence endpoints.

Covers:
- services.twitter.score_candidate_v2 edge cases
- routers.outreach._resolve_user_id nested-vs-flat TweetAPI response
- GET  /api/admin/outreach/confidence-preview shape
- POST /api/admin/outreach/recompute-confidence dry_run arithmetic
"""

import os
import sys
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import requests

# Make /app/backend importable so we can unit-test helpers
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "papersumo2025")
if not BASE_URL:
    # Read from frontend env as a fallback
    try:
        with open("/app/frontend/.env", "r") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass


# ------------------------- fixtures -------------------------

@pytest.fixture(scope="session")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PW}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("admin_token")
    assert tok, f"No admin token in {r.json()}"
    return {"X-Admin-Token": tok}


# ------------------------- score_candidate_v2 unit tests -------------------------

class TestScoreCandidateV2:
    """Unit-level verification of the P0+P1 heuristics in services/twitter.py."""

    def setup_method(self):
        from services.twitter import score_candidate_v2
        self.score = score_candidate_v2
        self.authors = ["Rain Ozhang", "Gregor Schub"]

    def test_curator_bio_forces_low(self):
        cand = {
            "handle": "AstroPHYPapers", "name": "AstroPhys Papers",
            "bio": "New Astrophysics papers from arxiv every day",
            "tweet_text": "Check this one out!", "followers": 10000,
        }
        conf, sig = self.score(self.authors, cand)
        assert conf == "low"
        assert "curator_bio" in sig["reasons"]

    def test_curator_handle_no_bio_match_low(self):
        cand = {
            "handle": "QFinancePapers", "name": "QFinance Digest",
            "bio": "Tracking papers in finance",  # no author mention
            "tweet_text": "New paper", "followers": 500,
        }
        conf, sig = self.score(self.authors, cand)
        assert conf == "low"
        assert "curator_handle" in sig["reasons"]

    def test_curator_tweet_keywords_low(self):
        cand = {
            "handle": "someone", "name": "Some One",
            "bio": "Researcher", "tweet_text": "I've gathered today's papers for you",
            "followers": 100,
        }
        conf, sig = self.score(self.authors, cand)
        assert conf == "low"
        assert "curator_tweet" in sig["reasons"]

    def test_reply_tweet_caps_at_medium_without_strong_match(self):
        cand = {
            "handle": "ralphie", "name": "Ralph Random",
            "bio": "ML scientist",
            "tweet_text": "@somebody Congrats on the great paper!",
            "followers": 300,
        }
        conf, sig = self.score(self.authors, cand)
        # No meaningful match to the authors -> low, and "reply" reason recorded
        assert conf in ("low", "medium")
        assert "reply" in sig["reasons"]

    def test_strong_fuzzy_plus_full_token_match_high(self):
        cand = {
            "handle": "rainozhang", "name": "Rain Ozhang",
            "bio": "PhD student @ Caltech",
            "tweet_text": "Excited to share our new paper on x.",
            "followers": 800,
        }
        conf, sig = self.score(self.authors, cand)
        assert conf == "high"
        assert sig["name_fuzzy"] >= 85
        assert sig["name_full_match"] is True

    def test_author_language_boosts(self):
        cand = {
            "handle": "gregorschub", "name": "Gregor Schub",
            "bio": "Astrophysicist",
            "tweet_text": "Happy to share our new preprint on dark matter.",
            "followers": 1200,
        }
        conf, sig = self.score(self.authors, cand)
        assert conf == "high"
        assert "author_language" in sig["reasons"] or sig["author_language"] is True

    def test_reply_tweet_keeps_high_with_bio_fullname_match(self):
        cand = {
            "handle": "rain_oz", "name": "R. O.",
            "bio": "Personal page of Rain Ozhang, PhD",
            "tweet_text": "@friend thanks!",
            "followers": 200,
        }
        conf, sig = self.score(self.authors, cand)
        # bio_match provides strength even on a reply tweet
        assert conf == "high"
        assert sig["bio_match"] is True


# ------------------------- _resolve_user_id parser tests -------------------------

class TestResolveUserIdParser:
    """Confirms the nested-response parse bug is fixed — the resolver now
    correctly unwraps TweetAPI's {'data': {'id': ..., 'username': ...}}."""

    def _run(self, fake_resp, handle="AstroPHYPapers"):
        from routers import outreach as r

        # Patch the DB cache lookup + insert and the TweetAPI client
        async def _none(*a, **kw): return None
        async def _upsert(*a, **kw): return SimpleNamespace(matched_count=0, upserted_id="x")

        fake_db = SimpleNamespace(
            twitter_user_cache=SimpleNamespace(
                find_one=AsyncMock(return_value=None),
                update_one=AsyncMock(return_value=None),
            )
        )
        fake_client = SimpleNamespace(user=SimpleNamespace(
            get_by_username=lambda username: fake_resp
        ))

        with patch.object(r, "db", fake_db), \
             patch.object(r, "TWEETAPI_KEY", "stub-key"), \
             patch("tweetapi.TweetAPI", lambda api_key: fake_client):
            return asyncio.get_event_loop().run_until_complete(
                r._resolve_user_id(handle)
            )

    def test_nested_data_envelope(self):
        # Real TweetAPI shape: resp.data = {'data': {'id': '129992461', 'username': 'AstroPHYPapers'}}
        resp = SimpleNamespace(data={"data": {"id": "129992461", "username": "AstroPHYPapers"}})
        uid = self._run(resp)
        assert uid == "129992461"

    def test_flat_response_still_works(self):
        resp = SimpleNamespace(data={"id": "42", "username": "foo"})
        uid = self._run(resp, handle="foo")
        assert uid == "42"

    def test_non_numeric_raises(self):
        from fastapi import HTTPException
        resp = SimpleNamespace(data={"data": {"id": "not-a-number"}})
        with pytest.raises(HTTPException):
            self._run(resp)


# ------------------------- endpoint integration tests -------------------------

class TestConfidencePreviewEndpoint:
    def test_shape_has_v1_v2_signals(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/outreach/confidence-preview",
            params={"period": "monthly:2026-3", "top_n": 3},
            headers=admin_headers, timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "categories" in body and isinstance(body["categories"], list)

        cand_count = 0
        for cat in body["categories"]:
            for p in cat.get("papers", []):
                for c in p.get("candidates", []):
                    cand_count += 1
                    assert "confidence_v1" in c, f"missing v1 in {c}"
                    assert "confidence_v2" in c, f"missing v2 in {c}"
                    assert "signals_v2" in c and "reasons" in c["signals_v2"]
                    assert c["confidence_v1"] in ("high", "medium", "low")
                    assert c["confidence_v2"] in ("high", "medium", "low")
        # Preview should have at least one candidate in monthly:2026-3
        assert cand_count >= 1, "No candidates returned from preview"


class TestRecomputeConfidenceEndpoint:
    def test_dry_run_arithmetic(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/admin/outreach/recompute-confidence",
            params={"dry_run": "true"},
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True
        assert "total_candidates" in body and "transitions" in body
        t = body["transitions"]
        unchanged = t.get("unchanged", 0)
        changed = sum(v for k, v in t.items() if k != "unchanged")
        # Total = unchanged + changed
        assert body["total_candidates"] == unchanged + changed, \
            f"total {body['total_candidates']} != unchanged {unchanged} + changed {changed}"
