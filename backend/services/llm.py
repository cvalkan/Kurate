import asyncio
import json
import os
import re
import uuid
import random
import httpx
import io
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from PyPDF2 import PdfReader
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core.config import EMERGENT_LLM_KEY, TOURNAMENT_MODELS, DEFAULT_EVALUATION_PROMPT, logger, db

# Dedicated thread pool for LLM calls — default pool (8 threads) bottlenecks parallel evals
_llm_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="llm")

# Direct Anthropic API key — fallback when Emergent proxy fails for Claude
_ANTHROPIC_DIRECT_KEY = os.environ.get("ANTHROPIC_API_KEY")


async def _log_llm_error(provider: str, model: str, error: str, context: str = ""):
    """Persist LLM errors to MongoDB for production debugging."""
    try:
        await db.llm_error_logs.insert_one({
            "ts": datetime.now(timezone.utc),
            "provider": provider,
            "model": model,
            "error_type": type(error).__name__ if not isinstance(error, str) else "str",
            "error": str(error)[:1000],
            "context": context,
        })
    except Exception:
        pass  # never let logging break the caller

_TOKEN_LIMIT_KEYWORDS = ("token", "context_length", "context length", "too long", "too many tokens",
                         "maximum context", "max_tokens", "content_too_large", "request too large",
                         "input too long", "payload too large")

# Circuit breaker: after N consecutive Emergent proxy failures for a provider,
# skip the proxy entirely and go straight to the direct key fallback.
# Resets on backend restart (in-memory only).
_PROXY_FAIL_COUNTS = {}  # {provider: consecutive_failure_count}
_PROXY_CIRCUIT_THRESHOLD = 2  # skip proxy after this many consecutive failures


async def download_and_extract_pdf(pdf_url: str, doi: str = None) -> Optional[str]:
    try:
        headers = {"User-Agent": "paperscraper/1.0 (+https)"}
        async with httpx.AsyncClient(headers=headers) as http_client:
            response = await http_client.get(pdf_url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()

        # Run CPU-bound PDF parsing in thread pool to avoid blocking the event loop
        def _parse_pdf(content):
            pdf_bytes = io.BytesIO(content)
            reader = PdfReader(pdf_bytes)
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            full_text = "\n".join(text_parts)
            full_text = " ".join(full_text.split())
            full_text = full_text.encode("utf-8", errors="replace").decode("utf-8")
            return full_text

        import asyncio as _aio
        loop = _aio.get_event_loop()
        return await loop.run_in_executor(None, _parse_pdf, response.content)
    except Exception as e:
        logger.warning(f"Direct PDF download failed for {pdf_url}: {e}")
        # Fallback for ChemRxiv: use Playwright to bypass Cloudflare, then paperscraper
        if doi and "chemrxiv" in (doi + (pdf_url or "")).lower():
            result = await _download_pdf_via_playwright(pdf_url)
            if result:
                return result
            return await _download_pdf_via_paperscraper(doi)
        return None


async def _download_pdf_via_playwright(pdf_url: str) -> Optional[str]:
    """Download PDF via Playwright to bypass Cloudflare JS challenge."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        # Add download=true parameter
        if "?" not in pdf_url:
            pdf_url += "?download=true"
        elif "download=true" not in pdf_url:
            pdf_url += "&download=true"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path="/pw-browsers/chromium-1208/chrome-linux/chrome",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            page = await ctx.new_page()

            resp = await page.goto(pdf_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            # Get the raw response body if it's a PDF
            content_type = resp.headers.get("content-type", "") if resp else ""
            if "pdf" in content_type:
                body = await resp.body()
            else:
                # The page might have resolved the challenge; try getting content
                raw = await page.content()
                if raw.startswith("%PDF"):
                    body = raw.encode("latin-1")
                else:
                    await browser.close()
                    return None

            await browser.close()

            reader = PdfReader(io.BytesIO(body))
            text_parts = [page_obj.extract_text() or "" for page_obj in reader.pages]
            full_text = " ".join("\n".join(text_parts).split())
            full_text = full_text.encode("utf-8", errors="replace").decode("utf-8")

            if len(full_text) > 100:
                logger.info(f"PDF downloaded via Playwright for {pdf_url[:60]}... ({len(full_text)} chars)")
                return full_text
            return None
    except Exception as e:
        logger.warning(f"Playwright PDF download failed for {pdf_url}: {e}")
        return None


async def _download_pdf_via_paperscraper(doi: str) -> Optional[str]:
    """Fallback: use paperscraper's save_pdf to download ChemRxiv PDFs via Cambridge API."""
    try:
        from paperscraper.pdf import save_pdf
        import tempfile

        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "paper")

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            None,
            lambda: save_pdf({"doi": doi}, filepath=path)
        )

        pdf_path = path + ".pdf" if not path.endswith(".pdf") else path
        if success and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                reader = PdfReader(f)
                text_parts = [page.extract_text() or "" for page in reader.pages]
            full_text = " ".join("\n".join(text_parts).split())
            full_text = full_text.encode("utf-8", errors="replace").decode("utf-8")

            # Cleanup
            for fn in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, fn))
            os.rmdir(tmpdir)

            if len(full_text) > 100:
                logger.info(f"PDF downloaded via paperscraper for {doi} ({len(full_text)} chars)")
                return full_text
        return None
    except Exception as e:
        logger.warning(f"paperscraper PDF fallback failed for {doi}: {e}")
        return None


# Field-specific marker configurations
# Markers are ordered by specificity (more specific first)
FIELD_MARKERS = {
    "default": {
        "introduction": [
            "1. introduction", "1 introduction", "i. introduction", "ii. introduction",
            "introduction", "background", "overview", "motivation", "preliminaries",
        ],
        "methodology": [
            "materials and methods", "methods and materials", "experimental setup",
            "proposed method", "our approach", "system design", "technical approach",
            "methodology", "method", "approach", "model", "framework", "algorithm",
            "implementation", "architecture", "setup", "formulation",
        ],
        "results": [
            "results and discussion", "experimental results", "main results",
            "result", "experiment", "evaluation", "analysis", "finding",
            "empirical", "performance", "benchmark", "ablation", "comparison",
            "simulation", "numerical results", "case study",
        ],
        "conclusion": [
            "conclusion and future work", "conclusions and future work",
            "concluding remarks", "final remarks", "broader impact",
            "conclusion", "conclusions", "discussion", "summary", 
            "limitation", "future work", "closing remarks",
        ],
    },
    "econ": {
        "introduction": [
            "1. introduction", "1 introduction", "i. introduction",
            "introduction", "background", "motivation", "overview",
        ],
        "methodology": [
            "empirical strategy", "identification strategy", "estimation strategy",
            "data and methodology", "model and data",
            "methodology", "method", "data", "identification", "estimation", 
            "model", "framework", "econometric",
        ],
        "results": [
            "main results", "empirical results", "estimation results",
            "result", "finding", "evidence", "analysis", "robustness",
        ],
        "conclusion": [
            "conclusion and policy", "policy implications",
            "conclusion", "conclusions", "discussion", "summary",
            "limitation", "future work", "concluding remarks",
        ],
    },
    "physics": {
        "introduction": [
            "1. introduction", "i. introduction",
            "introduction", "background", "motivation", "overview",
        ],
        "methodology": [
            "theoretical framework", "numerical method", "computational method",
            "theory", "formalism", "model", "method", "methodology",
            "setup", "simulation setup",
        ],
        "results": [
            "numerical results", "simulation results",
            "result", "analysis", "calculation", "computation", "simulation",
        ],
        "conclusion": [
            "summary and conclusion", "conclusion and outlook",
            "conclusion", "conclusions", "discussion", "summary",
            "outlook", "future work",
        ],
    },
    "q-bio": {
        "introduction": [
            "1. introduction", "i. introduction",
            "introduction", "background", "overview",
        ],
        "methodology": [
            "materials and methods", "methods and materials", "experimental procedure",
            "method", "methodology", "protocol", "computational method",
            "data collection", "experimental design",
        ],
        "results": [
            "experimental results",
            "result", "finding", "observation", "analysis",
        ],
        "conclusion": [
            "conclusion", "conclusions", "discussion", "summary",
            "limitation", "future direction",
        ],
    },
    "cs": {
        "introduction": [
            "1. introduction", "1 introduction", "i. introduction",
            "introduction", "background", "motivation", "overview", "preliminaries",
        ],
        "methodology": [
            "proposed method", "our approach", "system design", "system overview",
            "method", "methodology", "approach", "architecture", "framework", 
            "algorithm", "implementation", "model", "design",
        ],
        "results": [
            "experimental results", "main results",
            "result", "experiment", "evaluation", "analysis",
            "performance", "benchmark", "ablation", "comparison",
        ],
        "conclusion": [
            "conclusion and future work", "conclusions and future work",
            "conclusion", "conclusions", "discussion", "summary",
            "limitation", "future work", "broader impact",
        ],
    },
}


def _get_field_markers(category: str = None) -> dict:
    """Get field-specific markers based on paper category."""
    if not category:
        return FIELD_MARKERS["default"]
    
    cat_lower = category.lower()
    if cat_lower.startswith("econ") or cat_lower.startswith("q-fin"):
        return FIELD_MARKERS["econ"]
    elif cat_lower.startswith("physics") or cat_lower.startswith("astro") or cat_lower.startswith("cond-mat"):
        return FIELD_MARKERS["physics"]
    elif cat_lower.startswith("q-bio"):
        return FIELD_MARKERS["q-bio"]
    elif cat_lower.startswith("cs"):
        return FIELD_MARKERS["cs"]
    return FIELD_MARKERS["default"]


def _find_section_header(text: str, markers: list, start_pos: int = 0, end_pos: int = None) -> tuple:
    """
    Find a section header using regex-based detection.
    Returns (position, matched_marker) or (-1, None) if not found.
    
    Looks for patterns like:
    - "1. Introduction", "2 Methods" (Arabic numerals)
    - "I. Introduction", "II. Methods" (Roman numerals)
    - "Introduction" at start of line
    - "INTRODUCTION" (all caps)
    """
    if end_pos is None:
        end_pos = len(text)
    
    search_text = text[start_pos:end_pos]
    text_lower = search_text.lower()
    
    best_match = (-1, None)
    
    for marker in markers:
        marker_lower = marker.lower()
        marker_escaped = re.escape(marker_lower)
        
        # Pattern 1: Arabic numbered section header (e.g., "1. Introduction", "2 Methods", "3.1 Setup")
        pattern1 = rf'(?:^|\n)\s*(?:[0-9]+(?:\.[0-9]+)?\.?\s+)?{marker_escaped}(?:\s*\n|$|:)'
        match1 = re.search(pattern1, text_lower, re.IGNORECASE | re.MULTILINE)
        
        # Pattern 2: Roman numeral section header (e.g., "I. Introduction", "II. Methods", "III. Results")
        pattern2 = rf'(?:^|\n)\s*(?:[IVXLC]+\.?\s+)?{marker_escaped}(?:\s*\n|$|:)'
        match2 = re.search(pattern2, text_lower, re.IGNORECASE | re.MULTILINE)
        
        # Pattern 3: All caps header (e.g., "INTRODUCTION", "METHODS AND MATERIALS")
        marker_upper = marker.upper()
        pattern3 = rf'(?:^|\n)\s*{re.escape(marker_upper)}\s*(?:\n|$)'
        match3 = re.search(pattern3, search_text, re.MULTILINE)
        
        # Pattern 4: Simple marker at line start with colon or newline
        pattern4 = rf'(?:^|\n)\s*{marker_escaped}\s*(?:\n|:)'
        match4 = re.search(pattern4, text_lower, re.IGNORECASE | re.MULTILINE)
        
        # Find the earliest valid match
        for match in [match1, match2, match3, match4]:
            if match:
                pos = start_pos + match.start()
                if best_match[0] == -1 or pos < best_match[0]:
                    best_match = (pos, marker)
    
    return best_match


def extract_key_sections(full_text: str, category: str = None, char_limit: int = 2000) -> Dict[str, str]:
    """
    Extract key sections from paper text using:
    1. Regex-based header detection (not just substring matching)
    2. Field-adaptive markers based on paper category
    3. Smart truncation: first half + last half of section (captures intro and conclusion of each section)
    4. Fallback: If sections not found, extract first/last N chars
    
    Args:
        full_text: The full paper text
        category: Paper category for field-specific markers
        char_limit: Maximum chars per section (first half from start, second half from end)
    
    Returns dict with keys: introduction, methodology, results, conclusion
    Each value is the extracted text (up to char_limit chars) or empty string.
    """
    sections = {"introduction": "", "methodology": "", "results": "", "conclusion": ""}
    text_len = len(full_text)
    
    if text_len < 100:
        return sections
    
    markers = _get_field_markers(category)
    text_lower = full_text.lower()
    
    # Find introduction
    intro_pos, _ = _find_section_header(full_text, markers["introduction"])
    if intro_pos == -1:
        for marker in markers["introduction"]:
            idx = text_lower.find(marker.lower())
            if idx != -1:
                intro_pos = idx
                break
    
    # Find methodology (search after introduction if found)
    method_start = intro_pos + 500 if intro_pos != -1 else 0
    method_pos, _ = _find_section_header(full_text, markers["methodology"], method_start)
    if method_pos == -1:
        for marker in markers["methodology"]:
            idx = text_lower.find(marker.lower(), method_start)
            if idx != -1:
                method_pos = idx
                break
    
    # Find results (search after methodology if found)
    results_start = method_pos + 500 if method_pos != -1 else method_start
    results_pos, _ = _find_section_header(full_text, markers["results"], results_start)
    if results_pos == -1:
        for marker in markers["results"]:
            idx = text_lower.find(marker.lower(), results_start)
            if idx != -1:
                results_pos = idx
                break
    
    # Find conclusion (search after results if found)
    conclusion_start = results_pos + 500 if results_pos != -1 else results_start
    conclusion_pos, _ = _find_section_header(full_text, markers["conclusion"], conclusion_start)
    if conclusion_pos == -1:
        for marker in markers["conclusion"]:
            idx = text_lower.find(marker.lower(), conclusion_start)
            if idx != -1:
                conclusion_pos = idx
                break
    
    # Smart extraction: if section is longer than limit, take first half + last half
    # This captures both the section introduction and its conclusions
    def extract_section_text(start_pos: int, next_pos: int = None) -> str:
        if start_pos == -1:
            return ""
        end_pos = next_pos if next_pos and next_pos != -1 else len(full_text)
        section_text = full_text[start_pos:end_pos].strip()
        section_len = len(section_text)
        
        if section_len <= char_limit:
            # Section fits within limit, return as-is
            return section_text
        
        # Section is too long - take first half + last half
        half_limit = char_limit // 2
        first_half = section_text[:half_limit]
        last_half = section_text[-half_limit:]
        
        # Add separator to indicate truncation
        return f"{first_half}\n\n[...middle content truncated...]\n\n{last_half}"
    
    # Track which sections were found via header detection vs fallback
    found_via_header = {
        "introduction": intro_pos != -1,
        "methodology": method_pos != -1,
        "results": results_pos != -1,
        "conclusion": conclusion_pos != -1,
    }
    
    sections["introduction"] = extract_section_text(intro_pos, method_pos)
    sections["methodology"] = extract_section_text(method_pos, results_pos)
    sections["results"] = extract_section_text(results_pos, conclusion_pos)
    sections["conclusion"] = extract_section_text(conclusion_pos)
    
    # FALLBACK: If sections missing, extract from document positions
    # Track fallback usage
    used_fallback = {
        "introduction": False,
        "methodology": False,
        "results": False,
        "conclusion": False,
    }
    
    sections_found = sum(1 for s in sections.values() if s)
    if sections_found == 0:
        # No sections detected - use fallback strategy
        # Take first 1.5x limit for intro, last limit for conclusion
        sections["introduction"] = full_text[:int(char_limit * 1.5)].strip()
        sections["conclusion"] = full_text[-char_limit:].strip()
        used_fallback["introduction"] = True
        used_fallback["conclusion"] = True
    else:
        # Partial extraction - fill in missing sections intelligently
        if not sections["introduction"]:
            sections["introduction"] = full_text[:char_limit].strip()
            used_fallback["introduction"] = True
        
        if not sections["conclusion"]:
            # Search more aggressively in last 30%
            last_30_pct = full_text[int(text_len * 0.7):]
            last_30_lower = last_30_pct.lower()
            
            found_in_last = False
            for marker in ["conclusion", "summary", "discussion", "future work"]:
                idx = last_30_lower.find(marker)
                if idx != -1:
                    sections["conclusion"] = last_30_pct[idx:idx+char_limit].strip()
                    found_in_last = True
                    break
            
            if not found_in_last:
                sections["conclusion"] = full_text[-char_limit:].strip()
            used_fallback["conclusion"] = True
        
        if not sections["methodology"]:
            middle_start = int(text_len * 0.15)
            middle_end = int(text_len * 0.5)
            middle_text = full_text[middle_start:middle_end]
            middle_lower = middle_text.lower()
            
            for marker in ["method", "approach", "model", "framework"]:
                idx = middle_lower.find(marker)
                if idx != -1:
                    sections["methodology"] = middle_text[idx:idx+char_limit].strip()
                    break
            used_fallback["methodology"] = True
        
        if not sections["results"]:
            mid_start = int(text_len * 0.4)
            mid_end = int(text_len * 0.8)
            mid_text = full_text[mid_start:mid_end]
            mid_lower = mid_text.lower()
            
            for marker in ["result", "experiment", "evaluation", "analysis"]:
                idx = mid_lower.find(marker)
                if idx != -1:
                    sections["results"] = mid_text[idx:idx+char_limit].strip()
                    break
            used_fallback["results"] = True
    
    # Store metadata for stats (will be stripped before returning to caller if needed)
    sections["_meta"] = {
        "found_via_header": found_via_header,
        "used_fallback": used_fallback,
        "char_limit": char_limit,
    }
    
    return sections



async def _get_section_char_limit() -> int:
    """Get the section char limit from settings, with fallback to default."""
    from core.auth import get_settings
    from core.config import DEFAULT_SETTINGS
    settings = await get_settings()
    return settings.get("section_char_limit", DEFAULT_SETTINGS.get("section_char_limit", 2000))


def _build_paper_content(paper: dict, char_limit: int = 2000) -> str:
    """Build paper content for LLM comparison using extracted sections."""
    if paper.get("full_text"):
        category = paper.get("categories", [None])[0]
        sections = extract_key_sections(paper["full_text"], category, char_limit)
        # Remove metadata
        sections.pop("_meta", None)
        
        # Use proportional limits based on char_limit
        # Total budget: roughly char_limit * 2 for the whole paper content
        intro_limit = int(char_limit * 0.5)
        method_limit = int(char_limit * 0.5)
        results_limit = int(char_limit * 0.4)
        conclusion_limit = int(char_limit * 0.25)
        abstract_limit = int(char_limit * 0.25)
        
        content = f"Abstract: {paper['abstract'][:abstract_limit]}\n\n"
        if sections["introduction"]:
            content += f"Introduction: {sections['introduction'][:intro_limit]}\n\n"
        if sections["methodology"]:
            content += f"Methodology: {sections['methodology'][:method_limit]}\n\n"
        if sections["results"]:
            content += f"Results: {sections['results'][:results_limit]}\n\n"
        if sections["conclusion"]:
            content += f"Conclusion: {sections['conclusion'][:conclusion_limit]}\n"
        return content
    return f"Abstract: {paper['abstract'][:int(char_limit * 0.6)]}"


_model_counter = 0
_model_lock = None


def _pick_round_robin_model() -> Dict[str, str]:
    """Round-robin model selection for even distribution across all models."""
    global _model_counter
    model = TOURNAMENT_MODELS[_model_counter % len(TOURNAMENT_MODELS)]
    _model_counter += 1
    return model


def _build_full_pdf_content(paper: dict, char_limit: int = None) -> str:
    """Build paper content using the full PDF text. No truncation unless char_limit is set."""
    abstract = paper.get("abstract", "")
    full_text = paper.get("full_text", "")
    if full_text:
        text = full_text[:char_limit] if char_limit else full_text
        return f"Abstract: {abstract}\n\nFull Paper Text:\n{text}"
    return f"Abstract: {abstract}"


async def compare_papers(paper1: dict, paper2: dict, prompt_config: dict = None, abstract_only: bool = False, char_limit: int = None, model_override: dict = None, content_mode: str = None, allow_tie: bool = False, multi_aspect: bool = False) -> Dict:
    if prompt_config is None:
        prompt_config = DEFAULT_EVALUATION_PROMPT

    model_info = model_override or _pick_round_robin_model()
    provider = model_info["provider"]
    model = model_info["model"]

    system_msg = prompt_config["system_prompt"]
    user_template = prompt_config["user_prompt"]

    # Use pre-fetched char_limit if provided, otherwise fetch from settings
    if char_limit is None:
        char_limit = await _get_section_char_limit()

    # Resolve content_mode from legacy abstract_only flag
    if content_mode is None:
        content_mode = "abstract" if abstract_only else "abstract_plus_summary"

    if content_mode == "abstract":
        p1_content = f"Abstract: {paper1.get('abstract', '')}"
        p2_content = f"Abstract: {paper2.get('abstract', '')}"
    elif content_mode == "full_pdf":
        p1_content = _build_full_pdf_content(paper1)
        p2_content = _build_full_pdf_content(paper2)
    elif content_mode == "ai_summary":
        p1_content = f"AI Impact Assessment:\n{paper1.get('ai_impact_summary', paper1.get('abstract', ''))}"
        p2_content = f"AI Impact Assessment:\n{paper2.get('ai_impact_summary', paper2.get('abstract', ''))}"
    elif content_mode == "abstract_plus_summary":
        p1_abs = paper1.get('abstract', '')
        p1_sum = paper1.get('ai_impact_summary_thinking', '') or paper1.get('ai_impact_summary_opus46', '') or paper1.get('ai_impact_summary', '')
        p1_content = f"Abstract: {p1_abs}\n\nAI Impact Assessment:\n{p1_sum}" if p1_sum else f"Abstract: {p1_abs}"
        p2_abs = paper2.get('abstract', '')
        p2_sum = paper2.get('ai_impact_summary_thinking', '') or paper2.get('ai_impact_summary_opus46', '') or paper2.get('ai_impact_summary', '')
        p2_content = f"Abstract: {p2_abs}\n\nAI Impact Assessment:\n{p2_sum}" if p2_sum else f"Abstract: {p2_abs}"
    elif content_mode == "abstract_plus_3summaries":
        def _build_multi_summary(paper):
            parts = [f"Abstract: {paper.get('abstract', '')}"]
            for key, label in [("ai_impact_summary_claude", "Assessment A (Claude)"), ("ai_impact_summary_gpt", "Assessment B (GPT)"), ("ai_impact_summary_gemini", "Assessment C (Gemini)")]:
                s = paper.get(key, '')
                if s:
                    parts.append(f"{label}:\n{s}")
            return "\n\n".join(parts)
        p1_content = _build_multi_summary(paper1)
        p2_content = _build_multi_summary(paper2)
    elif content_mode == "abstract_plus_random_summary":
        import random as _rnd
        _sum_keys = ["ai_impact_summary_claude", "ai_impact_summary_gpt", "ai_impact_summary_gemini"]
        def _pick_random_summary(paper):
            available = [paper.get(k, '') for k in _sum_keys if paper.get(k)]
            return _rnd.choice(available) if available else ''
        p1_abs = paper1.get('abstract', '')
        p1_sum = _pick_random_summary(paper1)
        p1_content = f"Abstract: {p1_abs}\n\nAI Impact Assessment:\n{p1_sum}" if p1_sum else f"Abstract: {p1_abs}"
        p2_abs = paper2.get('abstract', '')
        p2_sum = _pick_random_summary(paper2)
        p2_content = f"Abstract: {p2_abs}\n\nAI Impact Assessment:\n{p2_sum}" if p2_sum else f"Abstract: {p2_abs}"
    elif content_mode == "abstract_plus_impact":
        p1_abs = paper1.get('abstract', '')
        p1_imp = paper1.get('impact_statement', '')
        p1_content = f"Abstract: {p1_abs}\n\nEditorial Impact Statement: {p1_imp}" if p1_imp else f"Abstract: {p1_abs}"
        p2_abs = paper2.get('abstract', '')
        p2_imp = paper2.get('impact_statement', '')
        p2_content = f"Abstract: {p2_abs}\n\nEditorial Impact Statement: {p2_imp}" if p2_imp else f"Abstract: {p2_abs}"
    elif content_mode == "extract":
        # Legacy: section-extracted content. Kept for backward compatibility with old validation experiments.
        p1_content = _build_paper_content(paper1, char_limit)
        p2_content = _build_paper_content(paper2, char_limit)
    else:
        # Unknown mode — fall back to abstract_plus_summary
        logger.warning(f"Unknown content_mode '{content_mode}', falling back to abstract_plus_summary")
        p1_abs = paper1.get('abstract', '')
        p1_sum = paper1.get('ai_impact_summary_thinking', '') or paper1.get('ai_impact_summary', '')
        p1_content = f"Abstract: {p1_abs}\n\nAI Impact Assessment:\n{p1_sum}" if p1_sum else f"Abstract: {p1_abs}"
        p2_abs = paper2.get('abstract', '')
        p2_sum = paper2.get('ai_impact_summary_thinking', '') or paper2.get('ai_impact_summary', '')
        p2_content = f"Abstract: {p2_abs}\n\nAI Impact Assessment:\n{p2_sum}" if p2_sum else f"Abstract: {p2_abs}"

    prompt = user_template.format(
        paper1_title=paper1["title"],
        paper1_content=p1_content,
        paper2_title=paper2["title"],
        paper2_content=p2_content,
    )

    # Estimate input tokens (~4 chars per token)
    input_chars = len(system_msg) + len(prompt)
    input_tokens_est = input_chars // 4

    # Circuit breaker: if proxy has failed repeatedly, skip straight to fallback
    skip_proxy = (provider == "anthropic" and _ANTHROPIC_DIRECT_KEY
                  and _PROXY_FAIL_COUNTS.get(provider, 0) >= _PROXY_CIRCUIT_THRESHOLD)

    max_retries = 3
    last_error = None

    if not skip_proxy:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"compare-{uuid.uuid4()}",
            system_message=system_msg,
        ).with_model(provider, model)

        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    _llm_executor,
                    lambda: asyncio.run(chat.send_message(UserMessage(text=prompt))),
                )

                if not response or not response.strip():
                    raise ValueError("Empty response from LLM")

                output_tokens_est = len(response) // 4

                response_text = response.strip()
                if response_text.startswith("```"):
                    parts = response_text.split("```")
                    if len(parts) >= 2:
                        response_text = parts[1]
                        if response_text.startswith("json"):
                            response_text = response_text[4:]
                        response_text = response_text.strip()

                if not response_text.startswith("{"):
                    json_match = re.search(r'\{[^{}]*"winner"[^{}]*\}', response_text, re.DOTALL)
                    if json_match:
                        response_text = json_match.group()
                    else:
                        raise ValueError(f"No JSON found in response: {response_text[:200]}")

                result = json.loads(response_text)
                if multi_aspect:
                    from core.config import MULTI_ASPECT_DIMENSIONS
                    missing = [d for d in MULTI_ASPECT_DIMENSIONS if d not in result or result[d] not in ["paper1", "paper2"]]
                    if missing:
                        raise ValueError(f"Multi-aspect response missing dimensions: {missing}")
                    from collections import Counter as _Counter
                    votes = [result[d] for d in MULTI_ASPECT_DIMENSIONS]
                    vc = _Counter(votes)
                    result["winner"] = vc.most_common(1)[0][0]
                else:
                    valid_winners = ["paper1", "paper2", "tie"] if allow_tie else ["paper1", "paper2"]
                    if "winner" not in result or result["winner"] not in valid_winners:
                        raise ValueError(f"Invalid response format: {result}")

                result["model_used"] = model_info
                result["tokens"] = {
                    "input_est": input_tokens_est,
                    "output_est": output_tokens_est,
                }
                _PROXY_FAIL_COUNTS[provider] = 0  # Reset circuit breaker on success
                return result

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                await _log_llm_error(provider, model, e, context="compare_papers")
                is_budget = any(kw in err_str for kw in ("budget", "balance", "insufficient", "credit", "quota"))
                is_overloaded = "overloaded" in err_str or "rate" in err_str
                is_token_limit = any(kw in err_str for kw in _TOKEN_LIMIT_KEYWORDS)
                is_proxy_broken = any(kw in err_str for kw in ("authentication", "invalid x-api-key", "invalid api key", "not allowed", "timeout", "timed out", "502", "bad gateway"))
                if is_proxy_broken and provider == "anthropic" and _ANTHROPIC_DIRECT_KEY:
                    _PROXY_FAIL_COUNTS[provider] = _PROXY_FAIL_COUNTS.get(provider, 0) + 1
                    logger.warning(f"Emergent proxy error ({provider}/{model}), skipping to direct fallback (circuit: {_PROXY_FAIL_COUNTS[provider]})")
                    break
                elif is_budget:
                    logger.warning(f"LLM budget/credit error ({provider}/{model}): {e}. Waiting 15s for auto-topup...")
                    await asyncio.sleep(15)
                elif is_token_limit and content_mode == "full_pdf":
                    cur_len = max(len(paper1.get("full_text", "")), len(paper2.get("full_text", "")))
                    new_limit = max(cur_len // 2, 40_000)
                    p1_content = _build_full_pdf_content(paper1, char_limit=new_limit)
                    p2_content = _build_full_pdf_content(paper2, char_limit=new_limit)
                    prompt = user_template.format(paper1_title=paper1["title"], paper1_content=p1_content, paper2_title=paper2["title"], paper2_content=p2_content)
                    input_chars = len(system_msg) + len(prompt)
                    input_tokens_est = input_chars // 4
                    logger.warning(f"Token limit hit in comparison ({provider}/{model}), retrying with {new_limit:,} chars per paper")
                elif is_overloaded:
                    logger.warning(f"LLM overloaded ({provider}/{model}), attempt {attempt+1}/{max_retries}")
                    await asyncio.sleep(5 * (attempt + 1))
                else:
                    logger.warning(f"LLM comparison attempt {attempt+1}/{max_retries} failed ({provider}/{model}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)

    if not skip_proxy:
        logger.error(f"Comparison failed after {max_retries} attempts via Emergent proxy: {last_error}")

    # Fallback: if Anthropic failed through Emergent proxy, retry with direct API key
    if provider == "anthropic" and _ANTHROPIC_DIRECT_KEY:
        try:
            import litellm
            litellm.suppress_debug_info = True
            litellm.set_verbose = False
            logger.info(f"Falling back to direct Anthropic key for {model}")
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                _llm_executor,
                lambda: litellm.completion(
                    model=f"anthropic/{model}",
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    api_key=_ANTHROPIC_DIRECT_KEY,
                    timeout=60,
                ),
            )
            response_text = resp.choices[0].message.content.strip()
            output_tokens_est = resp.usage.completion_tokens if resp.usage else len(response_text) // 4
            input_tokens_est = resp.usage.prompt_tokens if resp.usage else input_tokens_est

            if response_text.startswith("```"):
                parts = response_text.split("```")
                if len(parts) >= 2:
                    response_text = parts[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                    response_text = response_text.strip()
            if not response_text.startswith("{"):
                json_match = re.search(r'\{[^{}]*"winner"[^{}]*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group()
                else:
                    raise ValueError(f"No JSON in fallback response: {response_text[:200]}")

            result = json.loads(response_text)
            if multi_aspect:
                from core.config import MULTI_ASPECT_DIMENSIONS
                from collections import Counter as _Counter
                missing = [d for d in MULTI_ASPECT_DIMENSIONS if d not in result or result[d] not in ["paper1", "paper2"]]
                if missing:
                    raise ValueError(f"Multi-aspect fallback response missing dimensions: {missing}")
                votes = [result[d] for d in MULTI_ASPECT_DIMENSIONS]
                result["winner"] = _Counter(votes).most_common(1)[0][0]
            else:
                valid_winners = ["paper1", "paper2", "tie"] if allow_tie else ["paper1", "paper2"]
                if "winner" not in result or result["winner"] not in valid_winners:
                    raise ValueError(f"Invalid fallback response: {result}")

            result["model_used"] = model_info
            result["tokens"] = {"input_est": input_tokens_est, "output_est": output_tokens_est}
            logger.info(f"Direct Anthropic fallback succeeded for {model}")
            return result
        except Exception as fallback_err:
            await _log_llm_error(provider, model, fallback_err, context="compare_papers_FALLBACK")
            logger.error(f"Direct Anthropic fallback also failed: {fallback_err}")

    raise Exception(f"Comparison failed after {max_retries} retries: {last_error}")


IMPACT_ASSESSMENT_PROMPT = {
    "system_prompt": """You are a scientific impact analyst. Your task is to write a detailed scientific impact assessment of a research paper. This assessment will later be used in a pairwise tournament to compare papers' scientific impact.

Write up to 1000 words (can be shorter if the paper warrants it). Structure your assessment around:

1. **Core Contribution**: What is the main novelty? What problem does it solve and how?
2. **Methodological Rigor**: How sound is the approach? Are the experiments/proofs convincing?
3. **Potential Impact**: What are the real-world applications? How broadly could this influence the field or adjacent fields?
4. **Timeliness & Relevance**: Does this address a current bottleneck or emerging need?
5. **Strengths & Limitations**: Key strengths that make this paper stand out, and notable weaknesses or gaps.

Feel free to add any other observations you deem important for judging scientific impact (e.g., scalability, reproducibility, dataset contributions, theoretical insights, comparison to prior art).

Be specific and analytical — avoid generic praise. Your assessment should give enough detail for another evaluator to judge this paper's impact without reading the full text.

After your assessment, provide numerical ratings on a JSON line. Rate each dimension from 1.0 to 10.0 (one decimal place):

```json
{"score": 7.5, "significance": 8.0, "rigor": 7.0, "novelty": 7.5, "clarity": 8.0}
```""",

    "user_prompt": """Write a scientific impact assessment for the following paper:

**Title:** {title}

**Content:**
{content}

Write your impact assessment (up to 1000 words), then provide your numerical ratings as a JSON line at the end:""",
}


async def generate_precomparison_impact_summary(paper: dict, model_override: dict = None) -> Optional[Dict]:
    """Generate a scientific impact assessment from the paper's full text.
    
    Sends the complete paper text with no truncation. On token-limit errors,
    retries with halved content until it fits.
    Returns dict with 'summary', 'model_used', and 'tokens' (actual usage), or None on failure.
    """
    import litellm
    from emergentintegrations.llm.utils import get_integration_proxy_url

    model_info = model_override or {"provider": "anthropic", "model": "claude-opus-4-6"}
    provider = model_info["provider"]
    model = model_info["model"]
    extra_params = model_info.get("extra_params", {})
    # Allow custom API key (e.g., for models not yet on Emergent proxy)
    api_key = model_info.get("api_key") or EMERGENT_LLM_KEY

    full_text = paper.get("full_text", "")
    abstract = paper.get("abstract", "")
    if not full_text:
        return None  # Require full PDF text — never summarize from abstract alone

    # Start with the full text, no limit
    char_limit = len(full_text)

    def _build_content(limit: int) -> str:
        return f"Abstract: {abstract}\n\nFull Paper Text:\n{full_text[:limit]}"

    content = _build_content(char_limit)

    def _build_litellm_params(prompt_text: str) -> dict:
        """Build litellm.completion params matching LlmChat._execute_completion logic."""
        messages = [
            {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
            {"role": "user", "content": prompt_text},
        ]
        params = {
            "model": f"{provider}/{model}",
            "messages": messages,
            "api_key": api_key,
        }
        is_emergent = api_key and api_key.startswith("sk-emergent")
        if is_emergent:
            proxy_url = get_integration_proxy_url()
            params["api_base"] = proxy_url + "/llm"
            params["custom_llm_provider"] = "openai"
            params["model"] = f"gemini/{model}" if provider == "gemini" else model
        params.update(extra_params)
        return params

    max_retries = 4
    original_char_limit = char_limit
    was_truncated = False

    # Circuit breaker: skip proxy if it's been failing
    skip_proxy = (provider == "anthropic" and _ANTHROPIC_DIRECT_KEY
                  and _PROXY_FAIL_COUNTS.get(provider, 0) >= _PROXY_CIRCUIT_THRESHOLD)

    for attempt in range(max_retries):
        if skip_proxy:
            break
        prompt = IMPACT_ASSESSMENT_PROMPT["user_prompt"].format(
            title=paper.get("title", "Untitled"),
            content=content,
        )
        params = _build_litellm_params(prompt)

        try:
            loop = asyncio.get_event_loop()
            raw_response = await loop.run_in_executor(
                _llm_executor,
                lambda: litellm.completion(**params),
            )
            response_text = raw_response.choices[0].message.content if raw_response.choices else ""
            if response_text and response_text.strip():
                summary_text = response_text.strip()

                # Append truncation note if the paper was truncated for this model
                if was_truncated:
                    pct = round(100 * char_limit / original_char_limit)
                    summary_text += f"\n\n[Note: This summary was generated from {pct}% of the paper ({char_limit:,} of {original_char_limit:,} characters) due to {provider}/{model} context window limits.]"

                # Extract actual token usage from response
                usage = raw_response.usage
                tokens = {}
                if usage:
                    tokens["input"] = getattr(usage, "prompt_tokens", 0) or 0
                    tokens["output"] = getattr(usage, "completion_tokens", 0) or 0
                    # Check for thinking/reasoning tokens in completion_tokens_details
                    details = getattr(usage, "completion_tokens_details", None)
                    if details:
                        tokens["thinking"] = getattr(details, "reasoning_tokens", 0) or 0

                _PROXY_FAIL_COUNTS[provider] = 0  # Reset circuit breaker on proxy success
                return {
                    "summary": summary_text,
                    "model_used": model_info,
                    "char_count": len(summary_text),
                    "word_count": len(summary_text.split()),
                    "tokens": tokens,
                    "truncated": was_truncated,
                    "truncated_pct": round(100 * char_limit / original_char_limit) if was_truncated else 100,
                }
        except Exception as e:
            err_str = str(e).lower()
            await _log_llm_error(provider, model, e, context="generate_summary")
            is_budget = any(kw in err_str for kw in ("budget", "balance", "insufficient", "credit", "quota"))
            is_token_limit = any(kw in err_str for kw in _TOKEN_LIMIT_KEYWORDS)
            is_auth = any(kw in err_str for kw in ("authentication", "invalid x-api-key", "invalid api key", "not allowed", "timeout", "timed out", "502", "bad gateway"))

            if is_auth and provider == "anthropic" and _ANTHROPIC_DIRECT_KEY:
                _PROXY_FAIL_COUNTS[provider] = _PROXY_FAIL_COUNTS.get(provider, 0) + 1
                logger.warning(f"Emergent proxy error ({provider}/{model}), skipping to direct fallback (circuit: {_PROXY_FAIL_COUNTS[provider]})")
                break  # Skip remaining retries, go straight to fallback
            elif is_budget:
                logger.warning(f"Budget/credit error during impact assessment ({provider}/{model}): {e}. Waiting 15s...")
                await asyncio.sleep(15)
            elif is_token_limit:
                # Halve the content and retry
                char_limit = max(char_limit // 2, 20_000)
                was_truncated = True
                content = _build_content(char_limit)
                logger.warning(f"Token limit hit for '{paper.get('title', '')[:50]}' ({provider}/{model}), retrying with {char_limit:,} chars")
            else:
                logger.warning(f"Impact assessment attempt {attempt+1}/{max_retries} failed ({provider}/{model}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

    logger.error(f"Impact assessment failed for {paper.get('title', '')[:50]} via Emergent proxy")

    # Fallback: if Anthropic failed through Emergent proxy, retry with direct API key
    if provider == "anthropic" and _ANTHROPIC_DIRECT_KEY:
        try:
            logger.info(f"Falling back to direct Anthropic key for summary ({model})")
            prompt = IMPACT_ASSESSMENT_PROMPT["user_prompt"].format(
                title=paper.get("title", "Untitled"),
                content=_build_content(char_limit),
            )
            params = {
                "model": f"anthropic/{model}",
                "messages": [
                    {"role": "system", "content": IMPACT_ASSESSMENT_PROMPT["system_prompt"]},
                    {"role": "user", "content": prompt},
                ],
                "api_key": _ANTHROPIC_DIRECT_KEY,
                "timeout": 120,
            }
            # Pass through LLM-relevant extra_params, translating proxy format
            # to native Anthropic format (extra_body.thinking → thinking)
            _PROXY_ONLY_KEYS = {"api_base", "custom_llm_provider"}
            for k, v in extra_params.items():
                if k in _PROXY_ONLY_KEYS:
                    continue
                if k == "extra_body" and isinstance(v, dict):
                    # Unwrap extra_body: move nested params to top level
                    for bk, bv in v.items():
                        params[bk] = bv
                    # Anthropic thinking requires max_tokens to exceed budget
                    if "thinking" in v and "max_tokens" not in params:
                        budget = v["thinking"].get("budget_tokens", 10000)
                        params["max_tokens"] = budget + 8000
                else:
                    params[k] = v
            loop = asyncio.get_event_loop()
            raw_response = await loop.run_in_executor(
                _llm_executor,
                lambda: litellm.completion(**params),
            )
            response_text = raw_response.choices[0].message.content if raw_response.choices else ""
            if response_text and response_text.strip():
                usage = raw_response.usage
                tokens = {}
                if usage:
                    tokens["input"] = getattr(usage, "prompt_tokens", 0) or 0
                    tokens["output"] = getattr(usage, "completion_tokens", 0) or 0
                logger.info(f"Direct Anthropic fallback succeeded for summary ({model})")
                return {
                    "summary": response_text.strip(),
                    "model_used": model_info,
                    "char_count": len(response_text.strip()),
                    "word_count": len(response_text.strip().split()),
                    "tokens": tokens,
                    "truncated": was_truncated,
                    "truncated_pct": round(100 * char_limit / original_char_limit) if was_truncated else 100,
                }
        except Exception as fallback_err:
            await _log_llm_error(provider, model, fallback_err, context="generate_summary_FALLBACK")
            logger.error(f"Direct Anthropic fallback also failed for summary: {fallback_err}")
    else:
        if provider == "anthropic" and not _ANTHROPIC_DIRECT_KEY:
            await _log_llm_error(provider, model, "ANTHROPIC_API_KEY not set — fallback unavailable", context="generate_summary_NO_FALLBACK")

    return None



def parse_ratings_from_summary(summary_text: str) -> Optional[dict]:
    """Extract JSON ratings block from the end of a summary text.
    Returns dict with score/significance/rigor/novelty/clarity, or None."""
    if not summary_text:
        return None
    import re as _re
    # Look for JSON block near the end of the text
    matches = list(_re.finditer(r'\{[^{}]*"score"[^{}]*\}', summary_text))
    if not matches:
        return None
    try:
        data = json.loads(matches[-1].group())
        score = float(data.get("score", 0))
        if 1.0 <= score <= 10.0:
            return {
                "score": round(score, 1),
                "significance": round(float(data.get("significance", 0)), 1),
                "rigor": round(float(data.get("rigor", 0)), 1),
                "novelty": round(float(data.get("novelty", 0)), 1),
                "clarity": round(float(data.get("clarity", 0)), 1),
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


async def call_llm(prompt: str, system: str = "", model_override: dict = None) -> str:
    """Generic LLM call that returns the raw text response.
    
    Args:
        prompt: The user prompt
        system: System message (optional)
        model_override: Dict with 'provider' and 'model' keys to use specific model
        
    Returns:
        Raw text response from the model
    """
    model_info = model_override or _pick_round_robin_model()
    provider = model_info["provider"]
    model = model_info["model"]
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"call-{uuid.uuid4()}",
        system_message=system or "You are a helpful assistant.",
    ).with_model(provider, model)
    
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            _llm_executor,
            lambda: asyncio.run(chat.send_message(UserMessage(text=prompt))),
        )
        return response.strip() if response else ""
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise
