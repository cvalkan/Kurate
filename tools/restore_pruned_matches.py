"""Backfill ALL match data from production (kurate.org) into preview DB.

Gets paper IDs from preview DB, fetches matches from production API.
Batches 50 requests then pauses 60s to respect rate limits.
Saves progress to disk for resumability.

Run: cd /app/backend && python3 /app/tools/restore_pruned_matches.py &>/app/tools/restore.log &
Monitor: tail -f /app/tools/restore.log
"""
import asyncio
import json
import urllib.request
import time
import os
import sys
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

PROD_URL = "https://kurate.org/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
PROGRESS_FILE = "/app/tools/restore_progress.json"
BATCH_SIZE = 50       # requests per burst
BATCH_PAUSE = 65      # seconds to wait between bursts
REQ_DELAY = 1.2       # seconds between individual requests within a burst


def fetch_json(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kurate-restore/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if "429" in str(e) or "Rate limit" in str(e):
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s, 120s
                print(f"    429 — sleeping {wait}s (attempt {attempt+1})", flush=True)
                time.sleep(wait)
            elif attempt == retries - 1:
                print(f"    FAILED {url[:60]}: {e}", flush=True)
                return None
            else:
                time.sleep(3)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"done_pids": [], "restored": 0}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Load progress for resumability
    progress = load_progress()
    done_pids = set(progress.get("done_pids", []))
    total_restored = progress.get("restored", 0)
    print(f"Resuming: {len(done_pids)} papers already done, {total_restored} matches restored so far\n", flush=True)

    # Get ALL paper IDs from preview DB
    cat_papers = {}
    async for doc in db.rankings.find({}, {"_id": 0, "paper_id": 1, "category": 1}):
        cat = doc.get("category", "")
        pid = doc.get("paper_id", "")
        if cat and pid:
            cat_papers.setdefault(cat, []).append(pid)

    all_papers = [(cat, pid) for cat in sorted(cat_papers) for pid in cat_papers[cat]]
    remaining = [(cat, pid) for cat, pid in all_papers if pid not in done_pids]
    print(f"Total papers: {len(all_papers)}, remaining: {len(remaining)}", flush=True)
    print(f"Estimated time: ~{len(remaining) * REQ_DELAY / 60 + (len(remaining) // BATCH_SIZE) * BATCH_PAUSE / 60:.0f} min\n", flush=True)

    # Load existing match IDs
    existing_ids = set()
    async for doc in db.matches.find({}, {"_id": 0, "id": 1}):
        existing_ids.add(doc["id"])
    print(f"Existing matches in preview: {len(existing_ids)}\n", flush=True)

    batch_to_insert = []
    affected_cats = set()
    req_in_burst = 0
    t0 = time.time()

    for i, (category, pid) in enumerate(remaining):
        # Rate limit: pause between bursts
        if req_in_burst >= BATCH_SIZE:
            # Flush pending inserts
            if batch_to_insert:
                try:
                    result = await db.matches.insert_many(batch_to_insert, ordered=False)
                    total_restored += len(result.inserted_ids)
                except Exception as e:
                    if hasattr(e, "details"):
                        total_restored += e.details.get("nInserted", 0)
                batch_to_insert = []

            # Save progress
            done_pids.update(pid for _, pid in remaining[:i])
            save_progress({"done_pids": list(done_pids), "restored": total_restored})

            elapsed = time.time() - t0
            fetched_so_far = i
            rate = fetched_so_far / elapsed if elapsed > 0 else 0
            eta = ((len(remaining) - i) / rate) / 60 if rate > 0 else 0
            print(f"\n  --- Burst done. {i}/{len(remaining)} papers, +{total_restored} matches. ETA {eta:.0f} min. Cooling {BATCH_PAUSE}s... ---\n", flush=True)
            time.sleep(BATCH_PAUSE)
            req_in_burst = 0

        time.sleep(REQ_DELAY)
        data = fetch_json(f"{PROD_URL}/papers/{pid}")
        req_in_burst += 1

        if not data:
            done_pids.add(pid)
            continue

        paper = data.get("paper", data)
        paper_id = paper.get("id", pid)
        matches = data.get("matches", [])

        for m in matches:
            mid = m.get("id")
            if not mid or mid in existing_ids:
                continue

            opponent_id = m.get("opponent_id", "")
            won = m.get("won", False)

            batch_to_insert.append({
                "id": mid,
                "paper1_id": paper_id,
                "paper2_id": opponent_id,
                "winner_id": paper_id if won else opponent_id,
                "primary_category": category,
                "shared_categories": [category],
                "content_mode": "abstract_plus_summary",
                "reasoning": m.get("reasoning", ""),
                "model_used": m.get("model_used", {}),
                "created_at": m.get("created_at", ""),
                "completed": True,
                "failed": m.get("failed", False),
            })
            existing_ids.add(mid)
            affected_cats.add(category)

        done_pids.add(pid)

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(remaining)}] {category} — pending inserts: {len(batch_to_insert)}", flush=True)

    # Final flush
    if batch_to_insert:
        try:
            result = await db.matches.insert_many(batch_to_insert, ordered=False)
            total_restored += len(result.inserted_ids)
        except Exception as e:
            if hasattr(e, "details"):
                total_restored += e.details.get("nInserted", 0)

    save_progress({"done_pids": list(done_pids), "restored": total_restored})

    elapsed = time.time() - t0
    print(f"\n  Fetch complete: +{total_restored} matches restored in {elapsed/60:.1f} min", flush=True)

    # Rerank affected categories
    if affected_cats:
        print(f"\nReranking {len(affected_cats)} categories...", flush=True)
        from services.ranking import rerank_category
        for cat in sorted(affected_cats):
            try:
                await rerank_category(db, cat)
                print(f"  [{cat}] Reranked", flush=True)
            except Exception as e:
                print(f"  [{cat}] Rerank failed: {e}", flush=True)

    # Clear pruning migration flag
    r = await db.migrations.delete_one({"_id": "prune_duplicate_matches_v1"})
    if r.deleted_count:
        print(f"\nCleared pruning migration flag.", flush=True)

    # Cleanup progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print(f"\n{'='*60}", flush=True)
    print(f"  DONE. Restored {total_restored} matches in {elapsed/60:.1f} min", flush=True)
    print(f"  Affected: {sorted(affected_cats)}", flush=True)
    print(f"{'='*60}", flush=True)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
