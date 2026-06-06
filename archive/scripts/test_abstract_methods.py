#!/usr/bin/env python3
"""Compare forum HTML scraping vs PDF+regex for abstract extraction."""

import asyncio
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from playwright.async_api import async_playwright
from scripts.iclr_batch_summaries import anonymize_text, download_pdf_playwright
from scripts.fetch_abstracts_jsonl import extract_abstract

TEST_IDS = ["wJgaHyJaDD", "uvRApnkdbk", "FSMCUSOTfY", "iiBjaiikJG", "Fn2rSOnpNf"]


async def test_forum_scrape(browser, oid):
    t0 = time.time()
    page = await browser.new_page()
    try:
        await page.goto(
            f"https://openreview.net/forum?id={oid}",
            wait_until="networkidle",
            timeout=30000,
        )
        await page.wait_for_timeout(2000)
        elements = await page.query_selector_all(".note-content-value")
        abstract = ""
        for el in elements:
            parent = await el.evaluate_handle("el => el.parentElement")
            label_el = await parent.query_selector("strong.note-content-field")
            if label_el:
                label = await label_el.inner_text()
                if "Abstract" in label:
                    abstract = await el.inner_text()
                    break
        return abstract.strip(), time.time() - t0, None
    except Exception as e:
        return "", time.time() - t0, str(e)
    finally:
        await page.close()


async def test_pdf_regex(oid):
    t0 = time.time()
    try:
        text = await download_pdf_playwright(oid, max_retries=2)
        if text:
            anon = anonymize_text(text)
            abstract = extract_abstract(anon)
            return abstract.strip(), time.time() - t0, None
        return "", time.time() - t0, "download_failed"
    except Exception as e:
        return "", time.time() - t0, str(e)


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)

    hdr = f"{'ID':<15} {'Method':<12} {'Chars':>6} {'Time':>6} Status"
    print(hdr)
    print("-" * 70)

    forum_ok, pdf_ok = 0, 0
    forum_times, pdf_times = [], []

    for oid in TEST_IDS:
        # Forum scrape
        abs_forum, t_forum, err_forum = await test_forum_scrape(browser, oid)
        status_f = f"ERR: {err_forum[:40]}" if err_forum else ("OK" if abs_forum else "EMPTY")
        print(f"{oid:<15} {'forum':<12} {len(abs_forum):>6} {t_forum:>5.1f}s {status_f}")
        if abs_forum:
            forum_ok += 1
        forum_times.append(t_forum)

        # PDF regex
        abs_pdf, t_pdf, err_pdf = await test_pdf_regex(oid)
        status_p = f"ERR: {err_pdf[:40]}" if err_pdf else ("OK" if abs_pdf else "EMPTY")
        print(f"{'':<15} {'pdf+regex':<12} {len(abs_pdf):>6} {t_pdf:>5.1f}s {status_p}")
        if abs_pdf:
            pdf_ok += 1
        pdf_times.append(t_pdf)

        # Compare overlap
        if abs_forum and abs_pdf:
            nf = set(abs_forum.lower().split())
            np_ = set(abs_pdf.lower().split())
            overlap = len(nf & np_) / max(len(nf | np_), 1)
            print(f"{'':<15} {'overlap':<12} {overlap*100:>5.1f}%")
        print()

    # Summary
    print("=" * 70)
    print(f"Forum:     {forum_ok}/{len(TEST_IDS)} OK, avg {sum(forum_times)/len(forum_times):.1f}s")
    print(f"PDF+regex: {pdf_ok}/{len(TEST_IDS)} OK, avg {sum(pdf_times)/len(pdf_times):.1f}s")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
