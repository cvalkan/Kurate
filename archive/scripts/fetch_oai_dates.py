"""
Fetch correct REST API publication dates for OAI-PMH papers.

Writes results to /app/oai_dates_results.jsonl (one JSON line per paper).
Resumable: papers already in the JSONL are skipped on re-run.

Usage:
  python fetch_oai_dates.py              # fetch ALL remaining
  python fetch_oai_dates.py --limit 20   # fetch first 20 remaining
"""

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OAI_JSON = Path("/app/oai_papers.json")
RESULTS_JSONL = Path("/app/oai_dates_results.jsonl")
ARXIV_API = "https://export.arxiv.org/api/query"
SLEEP_SEC = 3


def load_done_ids() -> set:
    """Read already-fetched arxiv_ids from the JSONL."""
    done = set()
    if RESULTS_JSONL.exists():
        for line in RESULTS_JSONL.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["arxiv_id"])
    return done


def append_result(record: dict):
    """Append one JSON line and flush immediately."""
    with open(RESULTS_JSONL, "a") as f:
        f.write(json.dumps(record) + "\n")


def fetch_paper_info(arxiv_id: str, client: httpx.Client) -> dict:
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

    version = None
    if id_el is not None and id_el.text:
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
    done_ids = load_done_ids()

    remaining = [p for p in papers_2026 if p["arxiv_id"] not in done_ids]
    if args.limit > 0:
        remaining = remaining[: args.limit]

    total = len(remaining)
    print(f"Already fetched: {len(done_ids)} | Remaining this run: {total}")

    with httpx.Client() as client:
        for i, paper in enumerate(remaining, 1):
            aid = paper["arxiv_id"]
            try:
                info = fetch_paper_info(aid, client)
                record = {
                    "arxiv_id": aid,
                    "paper_id": paper["paper_id"],
                    "category": paper["category"],
                    "published_in_db": paper["published_in_db"],
                    "rest_api_published": info["rest_api_published"],
                    "rest_api_updated": info["rest_api_updated"],
                    "current_version": info["current_version"],
                    "title": paper["title"],
                }
                status = f"{info['rest_api_published'] or 'NOT_FOUND'}  {info['current_version'] or '?'}"
            except Exception as e:
                record = {
                    "arxiv_id": aid,
                    "paper_id": paper["paper_id"],
                    "category": paper["category"],
                    "published_in_db": paper["published_in_db"],
                    "rest_api_published": None,
                    "rest_api_updated": None,
                    "current_version": None,
                    "error": str(e),
                    "title": paper["title"],
                }
                status = f"ERROR: {e}"

            append_result(record)
            print(f"[{i}/{total}] {aid} -> {status}")

            if i < total:
                time.sleep(SLEEP_SEC)

    final_count = len(load_done_ids())
    print(f"\nDone. {final_count} / 1083 total in {RESULTS_JSONL}")


if __name__ == "__main__":
    main()
