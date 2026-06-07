"""Kurate.org live data proxy.

Fetches from the live kurate.org public JSON API, reshapes responses
into the contract the homepage already consumes, and caches results
in memory for KURATE_CACHE_TTL seconds so we don't hammer upstream.
"""
from fastapi import FastAPI, APIRouter, Query, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import time
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

UPSTREAM = "https://kurate.org"
CACHE_TTL = 60  # seconds

app = FastAPI(title="Kurate Live Proxy")
api_router = APIRouter(prefix="/api")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}


def _field_for(code: str, group: str) -> str:
    c = code.lower()
    g = (group or "").lower()
    if c.startswith("cs.ai") or c.startswith("cs.lg") or "machine learning" in g.replace("computer", ""):
        return "ai"
    if c.startswith("cs.ro"):
        return "robotics"
    if c.startswith("cs.cr"):
        return "security"
    if c.startswith("cs."):
        return "cs"
    if c.startswith("quant-ph") or "physics" in g or c.startswith("astro") or c.startswith("cond-mat"):
        return "quantum"
    if c.startswith("math.") or "mathematics" in g:
        return "math"
    if c.startswith("q-bio") or "biology" in g or "life" in g:
        return "biology"
    if c.startswith("econ") or "economic" in g:
        return "econ"
    if c.startswith("stat"):
        return "math"
    return "cs"


async def _get(path: str, params: Optional[dict] = None) -> Any:
    key = f"{path}?{sorted((params or {}).items())}"
    now = time.time()
    if key in _cache and (now - _cache[key][0]) < CACHE_TTL:
        return _cache[key][1]
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{UPSTREAM}{path}", params=params or None, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    _cache[key] = (now, data)
    return data


def _humanise(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return "—"
    delta = datetime.now(timezone.utc) - dt
    h = int(delta.total_seconds() // 3600)
    if h < 1:
        return "just now"
    if h < 24:
        return f"{h}h ago"
    return f"{h // 24}d ago"


async def _categories_raw() -> list[dict[str, Any]]:
    data = await _get("/api/categories")
    return data.get("categories", [])


async def _leaderboard_raw(category: str = "all", limit: int = 200) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if category and category != "all":
        params["category"] = category
    return await _get("/api/leaderboard", params)


def _reshape_paper(p: dict[str, Any], idx: int, cat_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # Upstream uses arxiv_id like "2604.21017v2". We attempt to attach the most plausible category from
    # the title-less metadata using the first author group or fall back to the requested filter.
    cat_code = p.get("category") or p.get("primary_category") or ""
    cat_meta = cat_lookup.get(cat_code, {})
    field = _field_for(cat_code, cat_meta.get("group", ""))
    return {
        "id": p.get("id"),
        "rank": p.get("rank", idx + 1),
        "title": p.get("title", "").strip(),
        "authors": p.get("authors", []),
        "arxiv_id": p.get("arxiv_id"),
        "link": p.get("link"),
        "category_code": cat_code or "—",
        "category_name": cat_meta.get("name", ""),
        "field": field,
        "score": p.get("score", p.get("ts_score", 0)),
        "rating": p.get("ai_rating", 0),
        "gap": p.get("gap_score", 0),
        "wins": p.get("wins", 0),
        "losses": p.get("losses", 0),
        "comparisons": p.get("comparisons", 0),
        "added_at": p.get("published", datetime.now(timezone.utc).isoformat()),
        "published_at": p.get("published"),
        "signal_badge": f"{int(p.get('win_rate', 0))}% win rate",
    }


def _sort(papers: list[dict[str, Any]], rank_type: str) -> list[dict[str, Any]]:
    if rank_type == "rating":
        return sorted(papers, key=lambda p: p["rating"] or 0, reverse=True)
    if rank_type == "gap":
        return sorted(papers, key=lambda p: p["gap"] or 0, reverse=True)
    if rank_type == "recent" or rank_type == "newly_ranked":
        return sorted(papers, key=lambda p: p["added_at"] or "", reverse=True)
    return sorted(papers, key=lambda p: p["score"] or 0, reverse=True)


def _filter(papers: list[dict[str, Any]], q: Optional[str], period: Optional[str]) -> list[dict[str, Any]]:
    out = papers
    if q and q.strip():
        ql = q.lower().strip()
        out = [p for p in out if ql in (p["title"] or "").lower()
               or ql in (p["category_code"] or "").lower()
               or any(ql in (a or "").lower() for a in p["authors"])]
    if period and period != "all":
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - {"new": 3, "7d": 7, "30d": 30}.get(period, 0) * 86400
        def _ts(p: dict[str, Any]) -> float:
            try:
                return datetime.fromisoformat((p["added_at"] or "").replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0
        out = [p for p in out if _ts(p) >= cutoff]
    return out


@api_router.get("/")
async def root():
    return {"service": "kurate-live-proxy", "status": "ok", "upstream": UPSTREAM}


@api_router.get("/categories")
async def get_categories():
    cats = await _categories_raw()
    # paper counts approximated from the cached global top-200 leaderboard
    lb = await _leaderboard_raw("all", 200)
    counts: dict[str, int] = {}
    latest_by_cat: dict[str, str] = {}
    for p in lb.get("leaderboard", []):
        c = p.get("category") or p.get("primary_category") or ""
        if not c:
            continue
        counts[c] = counts.get(c, 0) + 1
        if c not in latest_by_cat or (p.get("published") or "") > latest_by_cat[c]:
            latest_by_cat[c] = p.get("published") or ""
    out = []
    for c in cats:
        code = c.get("id")
        out.append({
            "code": code,
            "name": c.get("name"),
            "field": _field_for(code, c.get("group", "")),
            "broad": c.get("group", ""),
            "description": c.get("name", ""),
            "paper_count": counts.get(code, 0),
            "latest_update": _humanise(latest_by_cat.get(code) or datetime.now(timezone.utc).isoformat()),
        })
    return out


@api_router.get("/years")
async def get_years():
    lb = await _leaderboard_raw("all", 200)
    years = sorted({(p.get("published") or "")[:4] for p in lb.get("leaderboard", []) if p.get("published")}, reverse=True)
    return [{"value": y, "label": y} for y in years if y]


@api_router.get("/papers")
async def get_papers(
    category: Optional[str] = "all",
    year: Optional[str] = "all",
    period: Optional[str] = "all",
    rank_type: Optional[str] = "score",
    q: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=200),
):
    cats = await _categories_raw()
    cat_lookup = {c["id"]: c for c in cats}
    lb = await _leaderboard_raw(category or "all", 200)
    raw = lb.get("leaderboard", [])
    # Attach category code from the upstream filter context if upstream omits it
    if category and category != "all":
        for p in raw:
            p.setdefault("category", category)
    papers = [_reshape_paper(p, i, cat_lookup) for i, p in enumerate(raw)]
    papers = _filter(papers, q, period)
    papers = _sort(papers, rank_type or "score")
    return {
        "total": len(papers),
        "results": [{**p, "rank": i + 1} for i, p in enumerate(papers[:limit])],
    }


@api_router.get("/metrics")
async def get_metrics():
    lb = await _leaderboard_raw("all", 50)
    cats = await _categories_raw()
    return {
        "papers_ranked": lb.get("total_papers", 0),
        "active_categories": len(cats),
        "total_comparisons": lb.get("total_matches", 0),
        "ai_judges": 3,
        "latest_update": _humanise(lb["leaderboard"][0]["published"]) if lb.get("leaderboard") else "—",
    }


@api_router.get("/recent")
async def get_recent():
    cats = await _categories_raw()
    cat_lookup = {c["id"]: c for c in cats}
    lb = await _leaderboard_raw("all", 200)
    raw = lb.get("leaderboard", [])
    counts: dict[str, int] = {}
    latest_by_cat: dict[str, str] = {}
    for p in raw:
        c = p.get("category") or ""
        if not c: continue
        counts[c] = counts.get(c, 0) + 1
        if c not in latest_by_cat or (p.get("published") or "") > latest_by_cat[c]:
            latest_by_cat[c] = p.get("published") or ""

    cards: list[dict[str, Any]] = [{
        "key": "newly_ranked",
        "kind": "feed",
        "title": "Newly Ranked Papers",
        "category_code": None,
        "field": "cs",
        "description": "Latest papers added to the live Kurate ranking pipeline.",
        "count": lb.get("total_papers", 0),
        "latest_update": _humanise(raw[0]["published"]) if raw else "—",
    }]
    top_cats = sorted(cats, key=lambda c: counts.get(c["id"], 0), reverse=True)[:7]
    for c in top_cats:
        code = c["id"]
        cards.append({
            "key": code,
            "kind": "category",
            "title": f"{c['name']} Papers",
            "category_code": code,
            "field": _field_for(code, c.get("group", "")),
            "description": c.get("group", c["name"]),
            "count": counts.get(code, 0),
            "latest_update": _humanise(latest_by_cat.get(code) or ""),
        })
    recent_papers = [_reshape_paper(p, i, cat_lookup) for i, p in enumerate(raw[:8])]
    return {"cards": cards, "recent_papers": recent_papers}


@api_router.get("/activity")
async def get_activity():
    cats = await _categories_raw()
    cat_lookup = {c["id"]: c for c in cats}
    lb = await _leaderboard_raw("all", 6)
    return [
        {
            "id": p.get("id"),
            "kind": "paper_ranked",
            "title": p.get("title"),
            "category_code": p.get("category") or "—",
            "field": _field_for(p.get("category") or "", cat_lookup.get(p.get("category") or "", {}).get("group", "")),
            "timestamp": p.get("published"),
            "status": f"Ranked at score {p.get('score')}",
        }
        for p in lb.get("leaderboard", [])
    ]


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def warm():
    try:
        await _categories_raw()
        await _leaderboard_raw("all", 200)
        logger.info("Warmed Kurate live cache.")
    except Exception as e:
        logger.warning("Warm-up failed (will retry on demand): %s", e)
