"""
Fetch real PubMed papers matching synthetic H1 validation paper topics.
Downloads open-access PDFs from PMC and extracts full text.
"""
import asyncio
import re
import httpx
import io
import time
from PyPDF2 import PdfReader
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


async def find_real_paper(title: str) -> dict:
    """Search PubMed for a real open-access paper matching this topic."""
    # Strip common prefixes to get core topic
    clean = re.sub(
        r'^(Systematic review of|Meta-analysis of|Clinical implications of|'
        r'Preclinical evaluation of|Molecular basis of|Therapeutic targeting of|'
        r'Novel insights into|A comprehensive analysis of|Genetic determinants of|'
        r'Longitudinal study of|Performance of the)\s+',
        '', title, flags=re.IGNORECASE
    ).strip()

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Search PubMed for free full text articles
        for query in [
            f'{clean}[Title] AND free full text[Filter]',
            f'{clean} AND free full text[Filter]',
        ]:
            r = await client.get(f"{NCBI_BASE}/esearch.fcgi", params={
                "db": "pubmed", "term": query, "retmode": "json", "retmax": 3, "sort": "relevance"
            })
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if ids:
                break

        if not ids:
            return None

        pmid = ids[0]

        # Get article details
        dr = await client.get(f"{NCBI_BASE}/esummary.fcgi", params={
            "db": "pubmed", "id": pmid, "retmode": "json"
        })
        detail = dr.json().get("result", {}).get(pmid, {})
        real_title = detail.get("title", "")

        # Check for PMC ID
        pmc_r = await client.get(
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params={"ids": pmid, "format": "json"}
        )
        pmc_id = None
        for rec in pmc_r.json().get("records", []):
            if rec.get("pmcid"):
                pmc_id = rec["pmcid"]

        # Get abstract from PubMed
        abs_r = await client.get(f"{NCBI_BASE}/efetch.fcgi", params={
            "db": "pubmed", "id": pmid, "retmode": "xml"
        })
        abstract = ""
        xml = abs_r.text
        # Simple XML extract
        abs_match = re.search(r'<AbstractText[^>]*>(.*?)</AbstractText>', xml, re.DOTALL)
        if abs_match:
            abstract = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip()

        return {
            "pmid": pmid,
            "pmc_id": pmc_id,
            "real_title": real_title,
            "real_abstract": abstract,
            "doi": detail.get("elocationid", ""),
        }


async def download_pmc_pdf(pmc_id: str) -> str:
    """Download PDF from PMC and extract text."""
    pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/"
    
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        r = await client.get(pdf_url)
        if r.status_code != 200:
            # Try alternate URL format
            r = await client.get(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/main.pdf")
        
        if r.status_code != 200:
            return ""
        
        try:
            reader = PdfReader(io.BytesIO(r.content))
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            full_text = "\n".join(text_parts)
            full_text = " ".join(full_text.split())
            full_text = full_text.encode("utf-8", errors="replace").decode("utf-8")
            return full_text
        except Exception as e:
            print(f"  PDF parse error for {pmc_id}: {e}")
            return ""


async def main():
    papers = await db.validation_papers.find({}, {"_id": 0}).to_list(100)
    print(f"Processing {len(papers)} validation papers...")

    matched = 0
    pdf_downloaded = 0
    failed = 0

    for i, p in enumerate(papers):
        title = p["title"]
        print(f"\n[{i+1}/{len(papers)}] {title[:55]}...")

        # Search for real paper
        result = await find_real_paper(title)
        await asyncio.sleep(0.5)  # Rate limit

        if not result:
            print(f"  ✗ No PubMed match found")
            failed += 1
            continue

        matched += 1
        print(f"  → [{result['pmid']}] {result['real_title'][:55]}")

        update = {
            "real_pmid": result["pmid"],
            "real_title": result["real_title"],
            "real_doi": result.get("doi", ""),
        }

        # Update abstract with real one if available
        if result["real_abstract"] and len(result["real_abstract"]) > 50:
            update["abstract"] = result["real_abstract"]
            print(f"  ✓ Real abstract ({len(result['real_abstract'])} chars)")

        # Download PDF if PMC available
        if result["pmc_id"]:
            print(f"  Downloading {result['pmc_id']}...", end="", flush=True)
            full_text = await download_pmc_pdf(result["pmc_id"])
            if full_text and len(full_text) > 500:
                update["full_text"] = full_text
                update["pmc_id"] = result["pmc_id"]
                pdf_downloaded += 1
                print(f" ✓ {len(full_text)} chars")
            else:
                print(f" ✗ failed or too short")
            await asyncio.sleep(0.5)

        # Update the paper in DB
        await db.validation_papers.update_one({"id": p["id"]}, {"$set": update})

    print(f"\n{'='*50}")
    print(f"Matched to real papers: {matched}/{len(papers)}")
    print(f"PDFs downloaded: {pdf_downloaded}")
    print(f"No match: {failed}")

    # Final stats
    has_text = await db.validation_papers.count_documents({"full_text": {"$exists": True, "$ne": None, "$ne": ""}})
    has_real_abs = await db.validation_papers.count_documents({"real_pmid": {"$exists": True}})
    print(f"\nDB state: {has_real_abs} with real PMID, {has_text} with full text")


asyncio.run(main())
