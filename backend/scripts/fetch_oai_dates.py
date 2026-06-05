"""
Fetch correct REST API publication dates for OAI-PMH papers.

Writes results DIRECTLY into /app/oai_papers.json (in-place update).
Resumable: papers that already have 'rest_api_published' are skipped.

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
ARXIV_API = "https://export.arxiv.org/api/query"
SLEEP_SEC = 3


def save_json(data: dict):
    with open(OAI_JSON, "w") as f:
        json.dump(data, f, indent=2)


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

    # Build index: position of each 2026 paper in the papers list
    remaining = []
    already_done = 0
    for idx, p in enumerate(data["papers"]):
        if p.get("actual_year") != 2026:
            continue
        if p.get("rest_api_published"):
            already_done += 1
            continue
        remaining.append(idx)

    if args.limit > 0:
        remaining = remaining[: args.limit]

    total = len(remaining)
    print(f"Already fetched: {already_done} | Remaining this run: {total}")

    with httpx.Client() as client:
        for i, idx in enumerate(remaining, 1):
            paper = data["papers"][idx]
            aid = paper["arxiv_id"]
            try:
                info = fetch_paper_info(aid, client)
                data["papers"][idx]["rest_api_published"] = info["rest_api_published"]
                data["papers"][idx]["rest_api_updated"] = info["rest_api_updated"]
                data["papers"][idx]["current_version"] = info["current_version"]
                status = f"{info['rest_api_published'] or 'NOT_FOUND'}  {info['current_version'] or '?'}"
            except Exception as e:
                data["papers"][idx]["rest_api_published"] = None
                data["papers"][idx]["rest_api_updated"] = None
                data["papers"][idx]["current_version"] = None
                data["papers"][idx]["fetch_error"] = str(e)
                status = f"ERROR: {e}"

            print(f"[{i}/{total}] {aid} -> {status}")

            # Persist after EVERY fetch — survives interruptions
            save_json(data)

            if i < total:
                time.sleep(SLEEP_SEC)

    print(f"\nDone. {already_done + len(remaining)} of 1083 papers now have REST API dates.")
    print(f"Results saved in-place to {OAI_JSON}")


if __name__ == "__main__":
    main()
