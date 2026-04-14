"""
SVG to PNG renderer.

Default: CairoSVG (works everywhere, no external browser dependency).
Optional: Playwright headless Chromium for pixel-perfect Google Fonts rendering.

To switch to Playwright, set environment variable: BADGE_RENDERER=playwright
(requires Chromium installed at PLAYWRIGHT_BROWSERS_PATH=/pw-browsers)

Usage:
    from services.svg_renderer import svg_to_png
    png_bytes = await svg_to_png(svg_string, width=2400, height=1260)
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_RENDERER = os.environ.get("BADGE_RENDERER", "cairosvg").lower()


def _svg_to_png_cairosvg(svg: str, output_width: int, output_height: int) -> bytes:
    """Render SVG to PNG using CairoSVG."""
    import cairosvg
    return cairosvg.svg2png(
        bytestring=svg.encode("utf-8") if isinstance(svg, str) else svg,
        output_width=output_width,
        output_height=output_height,
    )


# ── Playwright (optional, activated via BADGE_RENDERER=playwright) ──

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

_browser = None
_lock = asyncio.Lock()
_playwright_available = None


async def _get_browser():
    """Lazy singleton Playwright browser. Returns None if unavailable."""
    global _browser, _playwright_available
    if _playwright_available is False:
        return None
    if _browser and _browser.is_connected():
        return _browser
    async with _lock:
        if _playwright_available is False:
            return None
        if _browser and _browser.is_connected():
            return _browser
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            _browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            _playwright_available = True
            logger.info("Playwright Chromium browser launched")
        except Exception as e:
            _playwright_available = False
            logger.warning(f"Playwright unavailable ({e}), falling back to CairoSVG")
            return None
    return _browser


async def _svg_to_png_playwright(svg: str, output_width: int, output_height: int) -> bytes:
    """Render SVG to PNG using headless Chromium (pixel-perfect fonts)."""
    browser = await _get_browser()
    if browser is None:
        return _svg_to_png_cairosvg(svg, output_width, output_height)

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
        return await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": output_width, "height": output_height},
        )
    except Exception as e:
        logger.warning(f"Playwright render failed ({e}), falling back to CairoSVG")
        return _svg_to_png_cairosvg(svg, output_width, output_height)
    finally:
        await page.close()


# ── Public API ──

async def svg_to_png(
    svg: str,
    output_width: int = 2400,
    output_height: int = 1260,
) -> bytes:
    """Render SVG string to PNG.

    Uses CairoSVG by default. Set BADGE_RENDERER=playwright for Chromium rendering.
    """
    if _RENDERER == "playwright":
        return await _svg_to_png_playwright(svg, output_width, output_height)
    return _svg_to_png_cairosvg(svg, output_width, output_height)
