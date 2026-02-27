"""
Access Microbiology Scraper — Fetches papers + structured reviewer ratings from Sciety.

Extracts:
- Paper metadata (DOI, title, abstract)
- Per-reviewer ratings: methodological rigour, presentation quality, conclusions supported
- Composite numerical score
- Full review text

Stores in validation_papers + validation_matches format for tournament integration.
"""
import asyncio
import re
import time
import hashlib
import uuid
import requests
from datetime import datetime, timezone
from collections import defaultdict
from core.config import db, logger

DATASET_ID = "acmi-microbiology"
SCIETY_GROUP_URL = "https://sciety.org/groups/access-microbiology"

# Rating scales → numerical values
RIGOUR_SCALE = {"poor": 1, "satisfactory": 2, "good": 3, "very good": 4, "excellent": 5}
PRESENTATION_SCALE = {"poor": 1, "satisfactory": 2, "good": 3, "very good": 4, "excellent": 5}
CONCLUSIONS_SCALE = {"not at all": 1, "partially support": 2, "strongly support": 3}

# Normalize to 0-1 range for composite
RIGOUR_MAX = 5
PRESENTATION_MAX = 5
CONCLUSIONS_MAX = 3


def _normalize_rating(value: str, scale: dict, max_val: int) -> float:
    """Convert ordinal rating to 0-1 normalized score."""
    v = scale.get(value.lower().strip(), 0)
    return v / max_val if max_val > 0 else 0


def _composite_score(ratings: list) -> float:
    """Compute composite score (0-5) from a list of reviewer rating dicts."""
    if not ratings:
        return 0
    scores = []
    for r in ratings:
        components = []
        if r.get("rigour"):
            components.append(_normalize_rating(r["rigour"], RIGOUR_SCALE, RIGOUR_MAX))
        if r.get("presentation"):
            components.append(_normalize_rating(r["presentation"], PRESENTATION_SCALE, PRESENTATION_MAX))
        if r.get("conclusions"):
            components.append(_normalize_rating(r["conclusions"], CONCLUSIONS_SCALE, CONCLUSIONS_MAX))
        if components:
            scores.append(sum(components) / len(components))
    return round(sum(scores) / len(scores) * 5, 2) if scores else 0


def _scrape_article_list(max_pages: int = 70) -> list:
    """Scrape all article DOIs from the Sciety group pages."""
    all_dois = []
    for page in range(1, max_pages + 1):
        url = f"{SCIETY_GROUP_URL}?page={page}"
        try:
            resp = requests.get(url, timeout=30)
            dois = re.findall(r'articles/activity/(10\.\d+/[^"]+)', resp.text)
            if not dois:
                break
            all_dois.extend(dois)
            logger.info(f"ACMI scraper: page {page}, {len(dois)} articles (total: {len(all_dois)})")
        except Exception as e:
            logger.warning(f"ACMI scraper: page {page} failed: {e}")
            break
        time.sleep(0.3)
    return list(dict.fromkeys(all_dois))  # dedupe preserving order


def _scrape_article(doi: str) -> dict:
    """Scrape a single article's reviews and ratings from Sciety."""
    url = f"https://sciety.org/articles/activity/{doi}"
    resp = requests.get(url, timeout=30)
    text = resp.text

    # Extract title
    title_match = re.search(r'<h1[^>]*>\s*([^<]+)', text)
    title = title_match.group(1).strip() if title_match else doi

    # Extract abstract
    abstract = ""
    abs_match = re.search(r'<h2[^>]*>Abstract</h2>\s*<p>(.*?)</p>', text, re.DOTALL)
    if abs_match:
        abstract = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip()

    # Extract authors from the article info section
    authors = []
    # The article info section lists authors in an ordered list
    article_section = text[:text.find('Article activity feed')] if 'Article activity feed' in text else text[:8000]
    auth_list = re.findall(r'<li>\s*([A-Z][a-z]+ [A-Z][^<]{2,40})\s*</li>', article_section)
    if auth_list:
        authors = [a.strip() for a in auth_list]

    # Extract per-reviewer ratings
    # Split by "Read the original source" to separate review blocks
    review_blocks = re.split(r'Read the original source', text)

    reviewers = []
    for block in review_blocks:
        rigour = re.search(
            r'rate the manuscript for methodological rigour.*?<p>\s*(Poor|Satisfactory|Good|Very good|Excellent)\s*</p>',
            block, re.DOTALL | re.IGNORECASE
        )
        presentation = re.search(
            r'quality of the presentation.*?<p>\s*(Poor|Satisfactory|Good|Very good|Excellent)\s*</p>',
            block, re.DOTALL | re.IGNORECASE
        )
        conclusions = re.search(
            r'conclusions supported.*?<p>\s*(Not at all|Partially support|Strongly support)\s*</p>',
            block, re.DOTALL | re.IGNORECASE
        )

        if rigour or presentation or conclusions:
            # Extract review text (comments to author)
            review_text = ""
            comments_match = re.search(r'Comments to Author.*?(?=Please rate|Please confirm|$)', block, re.DOTALL | re.IGNORECASE)
            if comments_match:
                review_text = re.sub(r'<[^>]+>', ' ', comments_match.group()).strip()
                review_text = re.sub(r'\s+', ' ', review_text)[:5000]

            reviewer_id = f"reviewer_{len(reviewers)+1}"
            reviewers.append({
                "reviewer_id": reviewer_id,
                "rigour": rigour.group(1).strip() if rigour else None,
                "rigour_score": RIGOUR_SCALE.get(rigour.group(1).strip().lower(), 0) if rigour else None,
                "presentation": presentation.group(1).strip() if presentation else None,
                "presentation_score": PRESENTATION_SCALE.get(presentation.group(1).strip().lower(), 0) if presentation else None,
                "conclusions": conclusions.group(1).strip() if conclusions else None,
                "conclusions_score": CONCLUSIONS_SCALE.get(conclusions.group(1).strip().lower(), 0) if conclusions else None,
                "review_text": review_text[:2000],
            })

    return {
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "reviewers": reviewers,
        "composite_score": _composite_score(reviewers),
    }


async def run_scraper(max_pages: int = 70):
    """Full scraper: fetch all articles and store in DB."""
    progress_key = "acmi_scraper_progress"
    await db.settings.update_one(
        {"key": progress_key},
        {"$set": {"key": progress_key, "running": True, "phase": "listing", "done": 0, "total": 0}},
        upsert=True,
    )

    # Phase 1: Get article list
    logger.info("ACMI scraper: fetching article list...")
    loop = asyncio.get_event_loop()
    dois = await loop.run_in_executor(None, lambda: _scrape_article_list(max_pages))
    logger.info(f"ACMI scraper: found {len(dois)} articles")

    # Check which are already scraped
    existing = set()
    async for p in db.validation_papers.find({"dataset_id": DATASET_ID}, {"_id": 0, "source_doi": 1}):
        existing.add(p.get("source_doi", ""))
    remaining = [d for d in dois if d not in existing]

    total = len(remaining)
    await db.settings.update_one(
        {"key": progress_key},
        {"$set": {"phase": "scraping", "total": len(dois), "done": len(existing), "remaining": total}},
    )

    # Phase 2: Scrape each article
    done = len(existing)
    errors = 0
    for i, doi in enumerate(remaining):
        try:
            article = await loop.run_in_executor(None, lambda d=doi: _scrape_article(d))

            if not article["reviewers"]:
                done += 1
                continue

            paper_id = str(uuid.uuid4())

            # Build evaluations in our standard format
            evaluations = []
            for rev in article["reviewers"]:
                # Composite per-reviewer score (1-5)
                components = []
                if rev["rigour_score"]:
                    components.append(rev["rigour_score"] / RIGOUR_MAX)
                if rev["presentation_score"]:
                    components.append(rev["presentation_score"] / PRESENTATION_MAX)
                if rev["conclusions_score"]:
                    components.append(rev["conclusions_score"] / CONCLUSIONS_MAX)
                rating = round(sum(components) / len(components) * 5, 2) if components else 0

                evaluations.append({
                    "evaluator": rev["reviewer_id"],
                    "rating_value": rating,
                    "source": "Access Microbiology",
                    "rigour": rev["rigour"],
                    "rigour_score": rev["rigour_score"],
                    "presentation": rev["presentation"],
                    "presentation_score": rev["presentation_score"],
                    "conclusions": rev["conclusions"],
                    "conclusions_score": rev["conclusions_score"],
                })

            paper_doc = {
                "id": paper_id,
                "dataset_id": DATASET_ID,
                "title": article["title"],
                "abstract": article["abstract"],
                "authors": article["authors"],
                "source": "access_microbiology",
                "source_doi": doi,
                "link": f"https://doi.org/{doi}",
                "evaluations": evaluations,
                "composite_score": article["composite_score"],
                "n_reviewers": len(article["reviewers"]),
            }

            await db.validation_papers.insert_one(paper_doc)
            done += 1

            if done % 10 == 0:
                await db.settings.update_one(
                    {"key": progress_key},
                    {"$set": {"done": done, "errors": errors}},
                )
                logger.info(f"ACMI scraper: {done}/{len(dois)} ({len(article['reviewers'])} reviewers for {article['title'][:40]})")

        except Exception as e:
            errors += 1
            done += 1
            logger.warning(f"ACMI scraper failed for {doi}: {e}")

        await asyncio.sleep(0.3)  # Rate limit

    await db.settings.update_one(
        {"key": progress_key},
        {"$set": {"running": False, "done": done, "total": len(dois), "errors": errors, "phase": "complete"}},
    )
    logger.info(f"ACMI scraper complete: {done} articles, {errors} errors")


async def get_scraper_status() -> dict:
    doc = await db.settings.find_one({"key": "acmi_scraper_progress"}, {"_id": 0})
    return doc or {"running": False, "done": 0, "total": 0}


async def get_dataset_stats() -> dict:
    """Get stats about the scraped dataset."""
    papers = await db.validation_papers.find(
        {"dataset_id": DATASET_ID},
        {"_id": 0, "id": 1, "title": 1, "composite_score": 1, "n_reviewers": 1, "evaluations": 1},
    ).to_list(5000)

    if not papers:
        return {"status": "no_data"}

    from collections import Counter

    n_papers = len(papers)
    total_evals = sum(p.get("n_reviewers", 0) for p in papers)
    scores = [p.get("composite_score", 0) for p in papers if p.get("composite_score")]

    # Rating distributions across all dimensions
    rigour_dist = Counter()
    presentation_dist = Counter()
    conclusions_dist = Counter()
    for p in papers:
        for ev in p.get("evaluations", []):
            if ev.get("rigour"):
                rigour_dist[ev["rigour"]] += 1
            if ev.get("presentation"):
                presentation_dist[ev["presentation"]] += 1
            if ev.get("conclusions"):
                conclusions_dist[ev["conclusions"]] += 1

    # Pairwise GT potential: how many pairs have different composite scores?
    import statistics
    pairs_with_diff = 0
    total_pairs = n_papers * (n_papers - 1) // 2
    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            s1 = papers[i].get("composite_score", 0)
            s2 = papers[j].get("composite_score", 0)
            if abs(s1 - s2) > 0.1:
                pairs_with_diff += 1

    return {
        "status": "ok",
        "dataset_id": DATASET_ID,
        "papers": n_papers,
        "total_evaluations": total_evals,
        "avg_reviewers_per_paper": round(total_evals / n_papers, 1) if n_papers else 0,
        "composite_score_stats": {
            "mean": round(statistics.mean(scores), 2) if scores else 0,
            "median": round(statistics.median(scores), 2) if scores else 0,
            "stdev": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
            "min": round(min(scores), 2) if scores else 0,
            "max": round(max(scores), 2) if scores else 0,
        },
        "rating_distributions": {
            "rigour": dict(rigour_dist.most_common()),
            "presentation": dict(presentation_dist.most_common()),
            "conclusions": dict(conclusions_dist.most_common()),
        },
        "pairwise_gt": {
            "total_pairs": total_pairs,
            "pairs_with_different_scores": pairs_with_diff,
            "coverage": round(pairs_with_diff / max(total_pairs, 1) * 100, 1),
        },
    }
