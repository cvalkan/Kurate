"""Dump a finalised `convergence_all_<dataset>` cache entry from MongoDB into the
frontend's static-data folder so the chart is served without hitting the API.

Usage:
    python -m scripts.export_convergence_static iclr-2026-validation
    python -m scripts.export_convergence_static --all-finalised

The output path is:
    /app/frontend/public/static-data/convergence-<dataset_id>.json
    /app/frontend/build/static-data/convergence-<dataset_id>.json  (if build/ exists)

Registered datasets are consumed by `ConvergenceSection.jsx`'s
`STATIC_CONVERGENCE_DATASETS` map — new additions must be wired there too.
"""

import argparse
import asyncio
import datetime as _dt
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

PUBLIC_DIR = Path("/app/frontend/public/static-data")
BUILD_DIR = Path("/app/frontend/build/static-data")


async def _dump(db, dataset_id: str) -> None:
    entry = await db.computation_cache.find_one(
        {"key": f"convergence_all_{dataset_id}"}, {"_id": 0, "data": 1}
    )
    if not entry:
        print(f"[skip] no cache entry for {dataset_id}")
        return
    data = dict(entry["data"])
    data["finalised"] = True
    data["static_snapshot"] = True
    data["snapshot_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    payload = json.dumps(data, separators=(",", ":"))

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / f"convergence-{dataset_id}.json").write_text(payload)
    if BUILD_DIR.parent.exists():
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        (BUILD_DIR / f"convergence-{dataset_id}.json").write_text(payload)

    print(f"[ok] {dataset_id}: {len(payload)} bytes, {len(data.get('modes') or {})} mode(s)")


async def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dataset_ids", nargs="*", help="Dataset IDs to export")
    ap.add_argument("--all-finalised", action="store_true", help="Export every dataset with finalised=True")
    args = ap.parse_args(argv)

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    targets = list(args.dataset_ids)
    if args.all_finalised:
        async for d in db.validation_datasets.find({"finalised": True}, {"_id": 0, "dataset_id": 1}):
            if d["dataset_id"] not in targets:
                targets.append(d["dataset_id"])

    if not targets:
        print("No dataset ids given. Use positional args or --all-finalised.")
        return 1

    for ds in targets:
        await _dump(db, ds)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
