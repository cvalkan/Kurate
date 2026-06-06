import asyncio, os, sys, time, httpx
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')
from core.config import db

PDF_DIR = "/tmp/defi_papers/pdfs"
os.makedirs(PDF_DIR, exist_ok=True)
PARALLEL = 10

async def run():
    # Find papers in group with missing PDFs on disk
    to_download = []
    async for doc in db.defi_papers.find(
        {"group": "blockchain_ai_agents"},
        {"_id": 1, "title": 1, "pdf_url": 1, "pdf_path": 1, "doi": 1}
    ):
        path = doc.get("pdf_path", "")
        if path and os.path.exists(path):
            continue
        pdf_url = doc.get("pdf_url")
        if pdf_url:
            to_download.append(doc)

    total = len(to_download)
    print(f"Downloading {total} PDFs ({PARALLEL}x parallel)", flush=True)

    sem = asyncio.Semaphore(PARALLEL)
    downloaded = 0
    failed = 0
    t0 = time.time()

    async def dl_one(doc):
        nonlocal downloaded, failed
        async with sem:
            pdf_url = doc["pdf_url"]
            safe_name = (doc.get("doi") or doc["title"][:50]).replace("/", "_").replace(" ", "_").replace(":", "_")
            pdf_path = os.path.join(PDF_DIR, f"{safe_name}.pdf")

            try:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                    r = await client.get(pdf_url, headers={"User-Agent": "Mozilla/5.0 (KurateBot)"})
                    if r.status_code == 200 and len(r.content) > 5000:
                        with open(pdf_path, "wb") as f:
                            f.write(r.content)
                        await db.defi_papers.update_one(
                            {"_id": doc["_id"]},
                            {"$set": {"pdf_path": pdf_path, "pdf_downloaded": True}}
                        )
                        downloaded += 1
                    else:
                        failed += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  Error: {doc['title'][:40]}: {str(e)[:80]}", flush=True)

            done = downloaded + failed
            if done % 20 == 0 or done == total:
                elapsed = time.time() - t0
                print(f"  [{done}/{total}] {downloaded} ok, {failed} fail ({elapsed:.0f}s)", flush=True)

    await asyncio.gather(*[dl_one(doc) for doc in to_download])

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s: {downloaded} downloaded, {failed} failed", flush=True)

    # Final count
    exists = 0
    async for doc in db.defi_papers.find({"group": "blockchain_ai_agents"}, {"_id": 0, "pdf_path": 1}):
        if doc.get("pdf_path") and os.path.exists(doc["pdf_path"]):
            exists += 1
    print(f"Total PDFs on disk: {exists}/237")

asyncio.run(run())
