"""
Playwright-based SVG to PNG renderer.
Uses headless Chromium for pixel-perfect font rendering that matches
the browser exactly (proper Inter weight mapping, Google Fonts, etc.)

Usage:
    from services.svg_renderer import svg_to_png
    png_bytes = await svg_to_png(svg_string, width=2400, height=1260)
"""

import asyncio
import os
from playwright.async_api import async_playwright, Browser

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

_browser: Browser | None = None
_lock = asyncio.Lock()


async def _get_browser() -> Browser:
    """Lazy singleton browser instance."""
    global _browser
    if _browser and _browser.is_connected():
        return _browser
    async with _lock:
        if _browser and _browser.is_connected():
            return _browser
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
    return _browser


async def svg_to_png(
    svg: str,
    output_width: int = 2400,
    output_height: int = 1260,
) -> bytes:
    """Render SVG string to PNG using headless Chromium.

    The SVG is forced to fill the full output dimensions via CSS.
    Google Fonts Inter is loaded so all font-weight values render correctly.
    """
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=block" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; }}
  html, body {{ width: {output_width}px; height: {output_height}px; overflow: hidden; }}
  body {{ background: transparent; }}
  svg {{ display: block; width: {output_width}px; height: {output_height}px; }}
</style>
</head>
<body>{svg}</body></html>"""

    browser = await _get_browser()
    page = await browser.new_page(
        viewport={"width": output_width, "height": output_height},
    )
    try:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_function(
            "document.fonts.ready.then(() => true)",
            timeout=5000,
        )
        await page.wait_for_timeout(200)
        png_bytes = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": output_width, "height": output_height},
        )
        return png_bytes
    finally:
        await page.close()
