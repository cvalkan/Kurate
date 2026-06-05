"""
Fetch correct REST API publication dates for OAI-PMH papers.

Resumable: saves progress to a separate JSON after each successful fetch.
Usage:
  python fetch_oai_dates.py              # fetch ALL remaining
  python fetch_oai_dates.py --limit 20   # fetch first 20 remaining
"""

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OAI_JSON = Path("/app/oai_papers.json")
PROGRESS_JSON = Path("/app/oai_dates_progress.json")
ARXIV_API = "https://export.arxiv.org/api/query"
SLEEP_SEC = 3


def load_progress() -> dict:
    if PROGRESS_JSON.exists():
        with open(PROGRESS_JSON) as f:
            return json.load(f)
    return {}


def save_progress(progress: dict):
    with open(PROGRESS_JSON, "w") as f:
        json.dump(progress, f, indent=2)


def fetch_paper_info(arxiv_id: str, client: httpx.Client) -> dict:
    """Query arXiv REST API for a single paper's published date + version."""
    resp = client.get(ARXIV_API, params={"id_list": arxiv_id, "max_results": 1}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return {"rest_api_published": None, "rest_api_updated": None, "current_version": None}

    pub_el = entry.find("a:published", ns)
    upd_el = entry.find("a:updated", ns)
    id_el = entry.find("a:id", ns)

    # Version from <id> e.g. "http://arxiv.org/abs/2601.18175v2" -> "v2"
    version = None
    if id_el is not None and id_el.text:
        import re
        m = re.search(r"(v\d+)$", id_el.text.strip())
        if m:
            version = m.group(1)

    return {
        "rest_api_published": pub_el.text.strip() if pub_el is not None and pub_el.text else None,
        "rest_api_updated": upd_el.text.strip() if upd_el is not None and upd_el.text else None,
        "current_version": version,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max papers to fetch (0=all)")
    args = parser.parse_args()

    with open(OAI_JSON) as f:
        data = json.load(f)

    papers_2026 = [p for p in data["papers"] if p.get("actual_year") == 2026]
    progress = load_progress()

    remaining = [p for p in papers_2026 if p["arxiv_id"] not in progress]
    if args.limit > 0:
        remaining = remaining[: args.limit]

    total = len(remaining)
    already = len(progress)
    print(f"Already fetched: {already} | Remaining this run: {total}")

    with httpx.Client() as client:
        for i, paper in enumerate(remaining, 1):
            aid = paper["arxiv_id"]
            try:
                info = fetch_paper_info(aid, client)
                progress[aid] = {
                    **info,
                    "published_in_db": paper["published_in_db"],
                    "title": paper["title"],
                }
                status = f"{info['rest_api_published'] or 'NOT_FOUND'}  {info['current_version'] or '?'}"
            except Exception as e:
                progress[aid] = {
                    "rest_api_published": None,
                    "rest_api_updated": None,
                    "current_version": None,
                    "error": str(e),
                    "published_in_db": paper["published_in_db"],
                    "title": paper["title"],
                }
                status = f"ERROR: {e}"

            print(f"[{i}/{total}] {aid} -> {status}")
            save_progress(progress)

            if i < total:
                time.sleep(SLEEP_SEC)

    print(f"\nDone. Total in progress file: {len(progress)}")
    print(f"Saved to {PROGRESS_JSON}")


if __name__ == "__main__":
    main()
