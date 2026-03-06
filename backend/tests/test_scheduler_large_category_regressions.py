import asyncio
import copy
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import scheduler
from services import ranking


def _apply_projection(doc, projection):
    if not projection:
        return copy.deepcopy(doc)
    include_keys = [key for key, value in projection.items() if value and key != "_id"]
    if not include_keys:
        clone = copy.deepcopy(doc)
        clone.pop("_id", None)
        return clone
    return {key: copy.deepcopy(doc.get(key)) for key in include_keys if key in doc}


def _matches_query(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(_matches_query(doc, subquery) for subquery in value):
                return False
            continue

        if key == "categories.0":
            actual = (doc.get("categories") or [None])[0]
            exists = bool(doc.get("categories"))
        else:
            actual = doc.get(key)
            exists = key in doc

        if isinstance(value, dict):
            if "$exists" in value and bool(value["$exists"]) != exists:
                return False
            if "$ne" in value and actual == value["$ne"]:
                return False
            if "$in" in value and actual not in value["$in"]:
                return False
        elif actual != value:
            return False

    return True


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self.index = 0

    async def to_list(self, length):
        if self.index >= len(self.docs):
            return []
        if length is None:
            length = len(self.docs) - self.index
        batch = self.docs[self.index:self.index + length]
        self.index += len(batch)
        return [copy.deepcopy(doc) for doc in batch]


class FakeCollection:
    def __init__(self, docs):
        self.docs = {doc["id"]: copy.deepcopy(doc) for doc in docs}

    def find(self, query=None, projection=None):
        query = query or {}
        filtered = [_apply_projection(doc, projection) for doc in self.docs.values() if _matches_query(doc, query)]
        return FakeCursor(filtered)

    async def count_documents(self, query=None):
        query = query or {}
        return sum(1 for doc in self.docs.values() if _matches_query(doc, query))

    async def update_one(self, selector, update):
        doc = self.docs[selector["id"]]
        for key, value in update.get("$set", {}).items():
            target = doc
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value


class FakeDb:
    def __init__(self, papers, matches):
        self.papers = FakeCollection(papers)
        self.matches = FakeCollection(matches)


def test_generate_paper_summaries_processes_more_than_500_papers(monkeypatch):
    papers = [
        {
            "id": f"paper-{idx}",
            "title": f"Paper {idx}",
            "abstract": "Abstract",
            "full_text": "Full text",
            "categories": ["cs.RO"],
            "summaries": {},
        }
        for idx in range(501)
    ]
    fake_db = FakeDb(papers=papers, matches=[])

    async def fake_get_settings():
        return {"summary_parallel": 32, "paused": False}

    async def fake_generate_summary(paper, model_override=None):
        return {
            "summary": (
                f"summary for {paper['id']} via {model_override['model']} "
                "with enough detail to clear the minimum storage threshold"
            )
        }

    monkeypatch.setattr(scheduler, "db", fake_db)
    monkeypatch.setattr(scheduler, "get_settings", fake_get_settings)
    monkeypatch.setattr(scheduler, "generate_precomparison_impact_summary", fake_generate_summary)
    scheduler._category_status.clear()

    generated = asyncio.run(scheduler._generate_paper_summaries(category="cs.RO", force=True))

    assert generated == 501 * len(scheduler._SUMMARY_GENERATION_MODELS)
    for paper in fake_db.papers.docs.values():
        assert len(paper.get("summaries", {})) == len(scheduler._SUMMARY_GENERATION_MODELS)


def test_check_goals_met_includes_papers_beyond_first_500(monkeypatch):
    papers = [
        {
            "id": f"paper-{idx}",
            "categories": ["cs.RO"],
            "summaries": {"anthropic:claude-opus-4-6:thinking": "ready summary"},
        }
        for idx in range(501)
    ]

    matches = []
    match_id = 0

    for left in range(10):
        for right in range(left + 1, 10):
            matches.append({
                "id": f"match-{match_id}",
                "paper1_id": f"paper-{left}",
                "paper2_id": f"paper-{right}",
                "winner_id": f"paper-{left}",
                "completed": True,
                "primary_category": "cs.RO",
            })
            match_id += 1

    for idx in range(10, 500):
        matches.append({
            "id": f"match-{match_id}",
            "paper1_id": "paper-0",
            "paper2_id": f"paper-{idx}",
            "winner_id": "paper-0",
            "completed": True,
            "primary_category": "cs.RO",
        })
        match_id += 1

    fake_db = FakeDb(papers=papers, matches=matches)

    async def fake_get_settings():
        return {"top_k_focus": 10, "ci_target": 10, "ci_target_general": 15}

    def fake_margin(_wins, comparisons):
        return 1 if comparisons else 100

    monkeypatch.setattr(scheduler, "db", fake_db)
    monkeypatch.setattr(scheduler, "get_settings", fake_get_settings)
    monkeypatch.setattr(ranking, "wilson_margin_pct", fake_margin)

    goals_met = asyncio.run(scheduler._check_goals_met(category="cs.RO"))

    assert goals_met is False