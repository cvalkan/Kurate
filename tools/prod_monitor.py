#!/usr/bin/env python3
"""
Production health monitor for kurate.org
Checks every 5 minutes for 3 hours. Logs results to MongoDB and stdout.
"""
import asyncio
import httpx
import time
from datetime import datetime, timezone

ENDPOINTS = [
    ("health", "https://kurate.org/api/health", 5),
    ("leaderboard_wr", "https://kurate.org/api/leaderboard?category=cs.RO&period=all&limit=5", 10),
    ("leaderboard_ts", "https://kurate.org/api/leaderboard?category=cs.RO&period=all&limit=5&sort_by=ts_score&sort_dir=desc", 10),
]

CHECK_INTERVAL = 300  # 5 minutes
DURATION = 3 * 3600   # 3 hours


async def check_endpoint(client, name, url, timeout):
    try:
        t0 = time.monotonic()
        resp = await client.get(url, timeout=timeout)
        elapsed = round(time.monotonic() - t0, 2)
        return {"name": name, "status": resp.status_code, "time_s": elapsed, "ok": resp.status_code == 200}
    except httpx.TimeoutException:
        return {"name": name, "status": "TIMEOUT", "time_s": timeout, "ok": False}
    except Exception as e:
        return {"name": name, "status": f"ERROR: {type(e).__name__}", "time_s": 0, "ok": False}


async def run_monitor():
    import pymongo
    mongo = pymongo.MongoClient("mongodb://localhost:27017")
    db = mongo["test_database"]

    start = time.monotonic()
    check_num = 0

    async with httpx.AsyncClient() as client:
        while time.monotonic() - start < DURATION:
            check_num += 1
            ts = datetime.now(timezone.utc)
            results = await asyncio.gather(*[
                check_endpoint(client, name, url, timeout)
                for name, url, timeout in ENDPOINTS
            ])

            all_ok = all(r["ok"] for r in results)
            summary = " | ".join(f"{r['name']}={r['status']}({r['time_s']}s)" for r in results)
            icon = "OK" if all_ok else "FAIL"
            ts_str = ts.strftime("%H:%M:%S")

            print(f"[{ts_str}] #{check_num} {icon}: {summary}")

            # Log to MongoDB
            db.system_logs.insert_one({
                "ts": ts,
                "level": "monitor",
                "label": f"prod_check {'ok' if all_ok else 'FAIL'}",
                "check_num": check_num,
                "results": results,
                "all_ok": all_ok,
            })

            if not all_ok:
                print(f"  *** ALERT: Production endpoint(s) DOWN ***")

            await asyncio.sleep(CHECK_INTERVAL)

    print(f"\nMonitoring complete. {check_num} checks over {DURATION/3600:.0f}h.")


if __name__ == "__main__":
    asyncio.run(run_monitor())
