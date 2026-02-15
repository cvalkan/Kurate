"""
F1000Prime Archive Scraper — Alzheimer's Dataset Builder

Strategy:
1. Seed from the Alzheimer's collection page
2. Scrape each article for evaluations (evaluator name, rating, member ID)
3. Follow evaluator profiles to discover more papers they've rated
4. Filter to neuro/Alzheimer's-relevant papers
5. Build a corpus of 50-80 papers with overlapping evaluators
"""
import asyncio
import re
import uuid
import logging
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://archive.connect.h1.co"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Neuro/Alzheimer's-relevant specialty keywords for filtering
RELEVANT_SPECIALTIES = {
    "neuroscience", "alzheimer", "dementia", "neurological", "neurodegenerative",
    "neurobiology", "neuronal", "neural", "brain", "cognitive", "amyloid",
    "tau", "neuroinflammation", "glia", "astrocyte", "microglia", "synap",
    "hippocamp", "cortex", "cortical", "memory", "ageing", "aging",
    "molecular medicine", "cell biology", "developmental biology",
    "biochemistry", "pharmacology", "physiology",
}

RATING_MAP = {"Exceptional": 3, "Very Good": 2, "Good": 1}

# Scraper state for progress tracking
_scraper_state = {
    "running": False,
    "phase": "",
    "articles_found": 0,
    "articles_scraped": 0,
    "members_scraped": 0,
    "papers_saved": 0,
    "log": [],
}


def get_state():
    return dict(_scraper_state)


def _log(msg: str):
    logger.info(f"[F1000] {msg}")
    _scraper_state["log"].append(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}")
    if len(_scraper_state["log"]) > 200:
        _scraper_state["log"] = _scraper_state["log"][-100:]


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Fetch a URL with retries and rate limiting."""
    for attempt in range(3):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429:
                _log(f"Rate limited on {url}, waiting...")
                await asyncio.sleep(5 * (attempt + 1))
                continue
            _log(f"HTTP {resp.status_code} for {url}")
            return None
        except Exception as e:
            _log(f"Error fetching {url}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
    return None


def _parse_article_ids_from_page(html: str) -> list[str]:
    """Extract article IDs from any page containing article links."""
    ids = []
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=re.compile(r"/article/\d+")):
        m = re.search(r"/article/(\d+)", a["href"])
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _parse_member_ids_from_page(html: str) -> list[str]:
    """Extract member IDs from any page containing member links."""
    ids = []
    for m in re.finditer(r"/member/(\d+)", html):
        mid = m.group(1)
        if mid not in ids:
            ids.append(mid)
    return ids


def _parse_article_page(html: str, article_id: str) -> Optional[dict]:
    """Parse a full article page into structured data."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # Title
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Unknown"
    if not title or title == "Unknown":
        return None

    # DOI
    doi = None
    doi_link = soup.find("a", href=re.compile(r"doi\.org"))
    if doi_link:
        doi = doi_link["href"].replace("https://doi.org/", "").replace("http://doi.org/", "")

    # PMID
    pmid = None
    pmid_link = soup.find("a", href=re.compile(r"pubmed\.ncbi"))
    if pmid_link:
        pm = re.search(r"/(\d+)", pmid_link["href"])
        if pm:
            pmid = pm.group(1)

    # Abstract
    abstract = None
    ab_match = re.search(r"Abstract.*?(?:Authors|Funding|Affiliations|Classifications|\u00a9)", text, re.DOTALL | re.I)
    if ab_match:
        raw = ab_match.group(0)
        # Clean up the captured text
        raw = re.sub(r"^Abstract\s*", "", raw, flags=re.I)
        raw = re.sub(r"(Authors|Funding|Affiliations|Classifications|\u00a9).*$", "", raw, flags=re.I)
        abstract = raw.strip()[:2000]

    # Journal + year
    journal = None
    year = None
    # Pattern like "eLife. 2020 02 19" or "Nature. 2021 Jan"
    j_match = re.search(r"([A-Za-z][A-Za-z\s&.]+?)\.\s*(\d{4})\s", text)
    if j_match:
        journal = j_match.group(1).strip().rstrip(".")
        year = j_match.group(2)

    # Authors (from the "et al." line near the top)
    authors = []
    author_line = soup.find("h1")
    if author_line:
        next_text = ""
        for sib in author_line.next_siblings:
            t = sib.get_text(strip=True) if hasattr(sib, "get_text") else str(sib).strip()
            if t:
                next_text = t
                break
        if "et al" in next_text:
            authors = [next_text.replace(" et al.", "").strip()]

    # Evaluations — find rating blocks
    evaluations = []
    eval_sections = soup.find_all(string=re.compile(r"^(Exceptional|Very Good|Good)$"))
    for rating_elem in eval_sections:
        rating_text = rating_elem.strip()
        if rating_text not in RATING_MAP:
            continue

        # Find the nearest member link after this rating
        parent = rating_elem.parent
        if not parent:
            continue
        # Walk up to find the evaluation container
        container = parent
        for _ in range(8):
            if container.parent:
                container = container.parent
            else:
                break

        # Find evaluator name and ID
        evaluator_name = None
        evaluator_id = None
        member_links = container.find_all("a", href=re.compile(r"/member/\d+"))
        if member_links:
            evaluator_name = member_links[0].get_text(strip=True)
            m = re.search(r"/member/(\d+)", member_links[0]["href"])
            if m:
                evaluator_id = m.group(1)

        # Find date near the rating
        date_text = None
        date_match = re.search(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", container.get_text())
        if date_match:
            date_text = date_match.group(1)

        if evaluator_name:
            evaluations.append({
                "rating": rating_text,
                "rating_value": RATING_MAP[rating_text],
                "evaluator": evaluator_name,
                "evaluator_id": evaluator_id,
                "date": date_text,
            })

    # Deduplicate evaluations (same evaluator)
    seen_evaluators = set()
    unique_evals = []
    for ev in evaluations:
        key = ev["evaluator"]
        if key not in seen_evaluators:
            seen_evaluators.add(key)
            unique_evals.append(ev)
    evaluations = unique_evals

    # Classifications
    classifications = []
    class_keywords = [
        "Confirmation", "Good for Teaching", "Interesting Hypothesis",
        "New Finding", "Novel Drug Target", "Review", "Controversial",
        "Refutation", "Technical Advance", "Changes Clinical Practice",
    ]
    for kw in class_keywords:
        if kw in text:
            classifications.append(kw)

    # Relevant specialties (full text from the "Relevant Specialties" section)
    specialties_text = ""
    spec_match = re.search(r"Relevant Specialties(.*?)(?:Clinical Trials|Related Articles|$)", text, re.DOTALL)
    if spec_match:
        specialties_text = spec_match.group(1).lower()

    # Related article IDs
    related_ids = []
    related_section = soup.find_all("a", href=re.compile(r"/article/\d+"))
    for a in related_section:
        m = re.search(r"/article/(\d+)", a["href"])
        if m and m.group(1) != article_id:
            related_ids.append(m.group(1))

    return {
        "article_id": article_id,
        "title": title,
        "doi": doi,
        "pmid": pmid,
        "abstract": abstract,
        "journal": journal,
        "year": year,
        "authors": authors,
        "evaluations": evaluations,
        "classifications": classifications,
        "specialties_text": specialties_text,
        "related_article_ids": list(set(related_ids)),
    }


async def _scrape_collection_page(client: httpx.AsyncClient, collection: str) -> list[str]:
    """Get all article IDs from a collection page."""
    html = await _fetch(client, f"{BASE}/collections/{collection}")
    if not html:
        return []
    return _parse_article_ids_from_page(html)


async def _scrape_article(client: httpx.AsyncClient, article_id: str) -> Optional[dict]:
    """Scrape a single article page."""
    html = await _fetch(client, f"{BASE}/article/{article_id}")
    if not html:
        return None
    return _parse_article_page(html, article_id)


async def _scrape_member_articles(client: httpx.AsyncClient, member_id: str) -> list[str]:
    """Get all article IDs recommended by a member."""
    html = await _fetch(client, f"{BASE}/member/{member_id}")
    if not html:
        return []
    return _parse_article_ids_from_page(html)


def _is_relevant(article: dict) -> bool:
    """Check if an article is relevant to neuroscience/Alzheimer's."""
    check_text = (
        (article.get("title") or "").lower() + " " +
        (article.get("abstract") or "").lower() + " " +
        (article.get("specialties_text") or "").lower() + " " +
        " ".join(article.get("classifications", [])).lower()
    )
    return any(kw in check_text for kw in RELEVANT_SPECIALTIES)


async def run_scraper(db, target_papers: int = 75) -> dict:
    """
    Main scraper pipeline.
    Returns summary of what was collected.
    """
    if _scraper_state["running"]:
        return {"status": "already_running"}

    _scraper_state.update({
        "running": True, "phase": "starting", "articles_found": 0,
        "articles_scraped": 0, "members_scraped": 0, "papers_saved": 0, "log": [],
    })

    try:
        return await _run_scraper_impl(db, target_papers)
    finally:
        _scraper_state["running"] = False


async def _run_scraper_impl(db, target_papers: int) -> dict:
    all_articles = {}  # article_id -> parsed article dict
    all_member_ids = set()
    scraped_members = set()
    article_queue = []  # article IDs to scrape

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:

        # ── Phase 1: Seed from Alzheimer's collection ──
        _scraper_state["phase"] = "Phase 1: Scraping Alzheimer's collection"
        _log("Phase 1: Getting seed articles from Alzheimer's collection...")

        seed_ids = await _scrape_collection_page(client, "alzheimers")
        _log(f"Found {len(seed_ids)} articles in Alzheimer's collection")
        article_queue.extend(seed_ids)

        # Also try the opioids collection (shares neuroscience evaluators)
        opioid_ids = await _scrape_collection_page(client, "opioids")
        _log(f"Found {len(opioid_ids)} articles in Opioids collection")
        article_queue.extend(opioid_ids)

        # ── Phase 2: Scrape seed articles ──
        _scraper_state["phase"] = "Phase 2: Scraping seed articles"
        _log(f"Phase 2: Scraping {len(article_queue)} seed articles...")

        scraped_ids = set()
        batch_size = 5

        for i in range(0, len(article_queue), batch_size):
            batch = [aid for aid in article_queue[i:i+batch_size] if aid not in scraped_ids]
            tasks = [_scrape_article(client, aid) for aid in batch]
            results = await asyncio.gather(*tasks)

            for aid, result in zip(batch, results):
                scraped_ids.add(aid)
                if result and _is_relevant(result):
                    all_articles[aid] = result
                    for ev in result.get("evaluations", []):
                        if ev.get("evaluator_id"):
                            all_member_ids.add(ev["evaluator_id"])
                    # Add related articles to queue
                    for rel_id in result.get("related_article_ids", []):
                        if rel_id not in scraped_ids and rel_id not in article_queue:
                            article_queue.append(rel_id)

            _scraper_state["articles_scraped"] = len(scraped_ids)
            _scraper_state["articles_found"] = len(all_articles)
            await asyncio.sleep(0.5)  # rate limit

        _log(f"Phase 2 complete: {len(all_articles)} relevant articles, {len(all_member_ids)} unique evaluators")

        # ── Phase 3: Follow evaluator profiles ──
        _scraper_state["phase"] = "Phase 3: Following evaluator profiles"
        _log(f"Phase 3: Scraping {len(all_member_ids)} evaluator profiles...")

        new_article_ids = []
        for mid in list(all_member_ids):
            if mid in scraped_members:
                continue
            scraped_members.add(mid)

            member_article_ids = await _scrape_member_articles(client, mid)
            _scraper_state["members_scraped"] = len(scraped_members)

            for aid in member_article_ids:
                if aid not in scraped_ids and aid not in new_article_ids:
                    new_article_ids.append(aid)

            await asyncio.sleep(0.5)

        _log(f"Found {len(new_article_ids)} new article IDs from evaluator profiles")

        # ── Phase 4: Scrape new articles discovered from profiles ──
        _scraper_state["phase"] = "Phase 4: Scraping discovered articles"
        _log(f"Phase 4: Scraping up to {min(len(new_article_ids), 200)} discovered articles...")

        for i in range(0, min(len(new_article_ids), 200), batch_size):
            batch = [aid for aid in new_article_ids[i:i+batch_size] if aid not in scraped_ids]
            if not batch:
                continue
            tasks = [_scrape_article(client, aid) for aid in batch]
            results = await asyncio.gather(*tasks)

            for aid, result in zip(batch, results):
                scraped_ids.add(aid)
                if result and _is_relevant(result):
                    all_articles[aid] = result
                    # Discover more evaluator IDs
                    for ev in result.get("evaluations", []):
                        if ev.get("evaluator_id") and ev["evaluator_id"] not in scraped_members:
                            all_member_ids.add(ev["evaluator_id"])

            _scraper_state["articles_scraped"] = len(scraped_ids)
            _scraper_state["articles_found"] = len(all_articles)
            await asyncio.sleep(0.5)

            # Early stop if we have enough
            if len(all_articles) >= target_papers * 2:
                _log(f"Reached {len(all_articles)} articles, stopping early")
                break

        _log(f"Phase 4 complete: {len(all_articles)} total relevant articles")

        # ── Phase 5: Second pass on new evaluator profiles (if needed) ──
        new_members = all_member_ids - scraped_members
        if new_members and len(all_articles) < target_papers:
            _scraper_state["phase"] = "Phase 5: Second-pass evaluator profiles"
            _log(f"Phase 5: Scraping {len(new_members)} additional evaluator profiles...")

            for mid in list(new_members)[:30]:
                scraped_members.add(mid)
                member_article_ids = await _scrape_member_articles(client, mid)
                _scraper_state["members_scraped"] = len(scraped_members)

                for aid in member_article_ids:
                    if aid not in scraped_ids:
                        html = await _fetch(client, f"{BASE}/article/{aid}")
                        scraped_ids.add(aid)
                        if html:
                            result = _parse_article_page(html, aid)
                            if result and _is_relevant(result):
                                all_articles[aid] = result

                _scraper_state["articles_scraped"] = len(scraped_ids)
                _scraper_state["articles_found"] = len(all_articles)
                await asyncio.sleep(0.5)

                if len(all_articles) >= target_papers * 2:
                    break

    # ── Phase 6: Select best papers and save ──
    _scraper_state["phase"] = "Phase 6: Selecting papers and saving"
    _log(f"Phase 6: Selecting best {target_papers} papers from {len(all_articles)} candidates...")

    result = await _select_and_save(db, all_articles, target_papers)
    _scraper_state["papers_saved"] = result["papers_saved"]
    _scraper_state["phase"] = "Complete"
    _log(f"Done! Saved {result['papers_saved']} papers with {result['unique_evaluators']} evaluators")

    return result


async def _select_and_save(db, all_articles: dict, target: int) -> dict:
    """Select papers with best evaluator overlap and save to DB."""

    # Build evaluator -> [article_ids] map
    evaluator_articles = defaultdict(set)
    article_evaluators = defaultdict(set)

    for aid, art in all_articles.items():
        for ev in art.get("evaluations", []):
            name = ev.get("evaluator", "")
            if name:
                evaluator_articles[name].add(aid)
                article_evaluators[aid].add(name)

    # Find evaluators who rated 2+ papers (these create pairwise preferences)
    prolific = {name: aids for name, aids in evaluator_articles.items() if len(aids) >= 2}
    _log(f"Evaluators with 2+ papers: {len(prolific)} (of {len(evaluator_articles)} total)")

    # Score each article by how many "prolific" evaluators it has
    article_scores = {}
    for aid in all_articles:
        score = sum(1 for ev_name in article_evaluators[aid] if ev_name in prolific)
        article_scores[aid] = score

    # Sort by score (most connected first), take top N
    ranked = sorted(article_scores.items(), key=lambda x: -x[1])
    selected_ids = [aid for aid, _ in ranked[:target]]

    # Log evaluator coverage
    selected_evaluators = set()
    for aid in selected_ids:
        for ev_name in article_evaluators[aid]:
            if ev_name in prolific:
                selected_evaluators.add(ev_name)

    # Count pairwise preferences we can derive
    total_pairs = 0
    for ev_name in selected_evaluators:
        papers_in_selection = [aid for aid in prolific[ev_name] if aid in selected_ids]
        n = len(papers_in_selection)
        total_pairs += n * (n - 1) // 2

    _log(f"Selected {len(selected_ids)} papers, {len(selected_evaluators)} overlapping evaluators, {total_pairs} derivable pairwise preferences")

    # Save dataset metadata
    dataset_id = "f1000-alzheimers"
    await db.validation_datasets.update_one(
        {"dataset_id": dataset_id},
        {"$set": {
            "dataset_id": dataset_id,
            "name": "F1000Prime Alzheimer's",
            "description": f"Alzheimer's & neuroscience papers from F1000Prime with expert faculty ratings (Good=1, Very Good=2, Exceptional=3). {len(selected_evaluators)} evaluators, {total_pairs} derivable pairwise preferences.",
            "source": "F1000Prime Archive (archive.connect.h1.co)",
            "rating_scale": "Good=1, Very Good=2, Exceptional=3",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    # Save papers
    saved = 0
    for aid in selected_ids:
        art = all_articles[aid]
        evals = []
        for ev in art.get("evaluations", []):
            evals.append({
                "rating_value": ev["rating_value"],
                "evaluator": ev["evaluator"],
                "source": "F1000Prime",
                "rating_label": ev["rating"],
                "date": ev.get("date"),
            })

        avg_rating = sum(e["rating_value"] for e in evals) / len(evals) if evals else 0

        paper_doc = {
            "id": str(uuid.uuid4()),
            "dataset_id": dataset_id,
            "title": art["title"],
            "abstract": art.get("abstract") or "",
            "authors": art.get("authors", []),
            "doi": art.get("doi"),
            "pmid": art.get("pmid"),
            "journal": art.get("journal"),
            "year": art.get("year"),
            "evaluations": evals,
            "h1_avg_rating": round(avg_rating, 2),
            "h1_rating_count": len(evals),
            "classifications": art.get("classifications", []),
            "source": "F1000Prime",
            "f1000_article_id": aid,
            "f1000_url": f"{BASE}/article/{aid}",
            "label": art.get("year", ""),
            "scores": [e["rating_value"] for e in evals],
            "keywords": art.get("classifications", []),
        }

        await db.validation_papers.update_one(
            {"dataset_id": dataset_id, "f1000_article_id": aid},
            {"$set": paper_doc},
            upsert=True,
        )
        saved += 1

    return {
        "status": "complete",
        "papers_saved": saved,
        "total_candidates": len(all_articles),
        "unique_evaluators": len(selected_evaluators),
        "derivable_pairs": total_pairs,
        "dataset_id": dataset_id,
    }



async def enrich_papers_from_semantic_scholar(db, dataset_id: str = "f1000-alzheimers") -> dict:
    """Fetch abstracts and metadata from Semantic Scholar for papers missing abstracts."""
    if _scraper_state["running"]:
        return {"status": "already_running"}

    _scraper_state.update({"running": True, "phase": "Enriching via Semantic Scholar", "log": []})

    try:
        papers = await db.validation_papers.find(
            {"dataset_id": dataset_id},
            {"_id": 0, "id": 1, "doi": 1, "pmid": 1, "title": 1, "abstract": 1}
        ).to_list(500)

        _log(f"Enriching {len(papers)} papers from Semantic Scholar...")
        enriched = 0
        failed = 0

        async with httpx.AsyncClient(timeout=20.0) as client:
            for i, p in enumerate(papers):
                doi = p.get("doi")
                pmid = p.get("pmid")
                title = p.get("title", "")

                # Skip f1000 DOIs (recommendation DOIs, not paper DOIs)
                if doi and doi.startswith("10.3410/"):
                    doi = None

                paper_id = None
                if doi:
                    paper_id = f"DOI:{doi}"
                elif pmid:
                    paper_id = f"PMID:{pmid}"

                if not paper_id:
                    try:
                        resp = await client.get(
                            "https://api.semanticscholar.org/graph/v1/paper/search",
                            params={"query": title[:100], "limit": 1, "fields": "abstract,venue,year,title,authors"}
                        )
                        if resp.status_code == 200:
                            hits = resp.json().get("data", [])
                            if hits:
                                ss = hits[0]
                                update = {}
                                if ss.get("abstract"):
                                    update["abstract"] = ss["abstract"]
                                if ss.get("venue"):
                                    update["journal"] = ss["venue"]
                                if ss.get("year"):
                                    update["year"] = str(ss["year"])
                                    update["label"] = str(ss["year"])
                                if ss.get("authors"):
                                    update["authors"] = [a.get("name", "") for a in ss["authors"]]
                                if update:
                                    await db.validation_papers.update_one({"id": p["id"]}, {"$set": update})
                                    enriched += 1
                                else:
                                    failed += 1
                            else:
                                failed += 1
                    except Exception as e:
                        failed += 1
                    await asyncio.sleep(0.3)
                    continue

                try:
                    resp = await client.get(
                        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
                        params={"fields": "abstract,venue,year,title,authors"}
                    )
                    if resp.status_code == 200:
                        ss = resp.json()
                        update = {}
                        if ss.get("abstract"):
                            update["abstract"] = ss["abstract"]
                        if ss.get("venue"):
                            update["journal"] = ss["venue"]
                        if ss.get("year"):
                            update["year"] = str(ss["year"])
                            update["label"] = str(ss["year"])
                        if ss.get("authors"):
                            update["authors"] = [a.get("name", "") for a in ss["authors"]]
                        if update:
                            await db.validation_papers.update_one({"id": p["id"]}, {"$set": update})
                            enriched += 1
                            _log(f"[{i+1}/{len(papers)}] Enriched: {title[:50]}")
                        else:
                            failed += 1
                    elif resp.status_code == 429:
                        _log("Rate limited, waiting 5s...")
                        await asyncio.sleep(5)
                        failed += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                await asyncio.sleep(0.3)

        _log(f"Enrichment complete: {enriched} enriched, {failed} failed")
        _scraper_state["phase"] = "Enrichment complete"
        return {"status": "complete", "enriched": enriched, "failed": failed, "total": len(papers)}
    finally:
        _scraper_state["running"] = False
