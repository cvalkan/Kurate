import asyncio
import json
import re
import uuid
import random
import httpx
import io
from typing import Dict, Optional
from PyPDF2 import PdfReader
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core.config import EMERGENT_LLM_KEY, TOURNAMENT_MODELS, DEFAULT_EVALUATION_PROMPT, logger


async def download_and_extract_pdf(pdf_url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(pdf_url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()

        pdf_bytes = io.BytesIO(response.content)
        reader = PdfReader(pdf_bytes)

        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        full_text = "\n".join(text_parts)
        full_text = " ".join(full_text.split())
        # Remove Unicode surrogate characters that can't be encoded to UTF-8
        full_text = full_text.encode("utf-8", errors="replace").decode("utf-8")
        return full_text
    except Exception as e:
        logger.error(f"Failed to download/extract PDF from {pdf_url}: {e}")
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


def extract_key_sections(full_text: str, category: str = None) -> Dict[str, str]:
    """
    Extract key sections from paper text using:
    1. Regex-based header detection (not just substring matching)
    2. Field-adaptive markers based on paper category
    3. Fallback: If sections not found, extract first/last N chars
    
    Returns dict with keys: introduction, methodology, results, conclusion
    Each value is the extracted text (up to 2000 chars) or empty string.
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
    
    # Extract text for each section (up to 2500 chars, trimmed to 2000)
    def extract_section_text(start_pos: int, next_pos: int = None) -> str:
        if start_pos == -1:
            return ""
        end_pos = next_pos if next_pos and next_pos != -1 else len(full_text)
        section_text = full_text[start_pos:min(start_pos + 2500, end_pos)]
        return section_text[:2000].strip()
    
    sections["introduction"] = extract_section_text(intro_pos, method_pos)
    sections["methodology"] = extract_section_text(method_pos, results_pos)
    sections["results"] = extract_section_text(results_pos, conclusion_pos)
    sections["conclusion"] = extract_section_text(conclusion_pos)
    
    # FALLBACK: If no sections found, extract first and last portions of document
    sections_found = sum(1 for s in sections.values() if s)
    if sections_found == 0:
        # No sections detected - use fallback strategy
        # Extract first 3000 chars as "introduction" (covers abstract + early content)
        # Extract last 2000 chars as "conclusion"
        sections["introduction"] = full_text[:3000].strip()
        sections["conclusion"] = full_text[-2000:].strip()
    elif sections_found < 3:
        # Partial extraction - fill in missing critical sections
        if not sections["introduction"] and intro_pos == -1:
            # No introduction found - use first 2000 chars
            sections["introduction"] = full_text[:2000].strip()
        if not sections["conclusion"] and conclusion_pos == -1:
            # No conclusion found - use last 2000 chars
            sections["conclusion"] = full_text[-2000:].strip()
    
    return sections


def get_extraction_stats(full_text: str, category: str = None) -> Dict:
    """
    Get detailed extraction statistics for a single paper.
    Used for the admin extraction stats page.
    """
    sections = extract_key_sections(full_text, category)
    
    stats = {
        "total_chars": len(full_text),
        "total_tokens_est": len(full_text) // 4,
        "sections": {},
        "sections_found": 0,
        "total_extracted_chars": 0,
    }
    
    for name, text in sections.items():
        found = len(text) > 0
        chars = len(text)
        stats["sections"][name] = {
            "found": found,
            "chars": chars,
            "tokens_est": chars // 4,
        }
        if found:
            stats["sections_found"] += 1
        stats["total_extracted_chars"] += chars
    
    stats["extraction_ratio"] = stats["total_extracted_chars"] / max(stats["total_chars"], 1)
    
    return stats


def _build_paper_content(paper: dict) -> str:
    if paper.get("full_text"):
        category = paper.get("categories", [None])[0]
        sections = extract_key_sections(paper["full_text"], category)
        content = f"Abstract: {paper['abstract'][:500]}\n\n"
        if sections["introduction"]:
            content += f"Introduction: {sections['introduction'][:1000]}\n\n"
        if sections["methodology"]:
            content += f"Methodology: {sections['methodology'][:1000]}\n\n"
        if sections["results"]:
            content += f"Results: {sections['results'][:800]}\n\n"
        if sections["conclusion"]:
            content += f"Conclusion: {sections['conclusion'][:500]}\n"
        return content
    return f"Abstract: {paper['abstract'][:1200]}"


_model_counter = 0
_model_lock = None


def _pick_round_robin_model() -> Dict[str, str]:
    """Round-robin model selection for even distribution across all models."""
    global _model_counter
    model = TOURNAMENT_MODELS[_model_counter % len(TOURNAMENT_MODELS)]
    _model_counter += 1
    return model


async def compare_papers(paper1: dict, paper2: dict, prompt_config: dict = None, abstract_only: bool = False) -> Dict:
    if prompt_config is None:
        prompt_config = DEFAULT_EVALUATION_PROMPT

    model_info = _pick_round_robin_model()
    provider = model_info["provider"]
    model = model_info["model"]

    system_msg = prompt_config["system_prompt"]
    user_template = prompt_config["user_prompt"]

    if abstract_only:
        p1_content = f"Abstract: {paper1.get('abstract', '')[:1500]}"
        p2_content = f"Abstract: {paper2.get('abstract', '')[:1500]}"
    else:
        p1_content = _build_paper_content(paper1)
        p2_content = _build_paper_content(paper2)

    prompt = user_template.format(
        paper1_title=paper1["title"],
        paper1_content=p1_content,
        paper2_title=paper2["title"],
        paper2_content=p2_content,
    )

    # Estimate input tokens (~4 chars per token)
    input_chars = len(system_msg) + len(prompt)
    input_tokens_est = input_chars // 4

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"compare-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model(provider, model)

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
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
            if "winner" not in result or result["winner"] not in ["paper1", "paper2"]:
                raise ValueError(f"Invalid response format: {result}")

            result["model_used"] = model_info
            result["tokens"] = {
                "input_est": input_tokens_est,
                "output_est": output_tokens_est,
            }
            return result

        except Exception as e:
            last_error = e
            logger.warning(f"LLM comparison attempt {attempt+1}/{max_retries} failed ({provider}/{model}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    logger.error(f"Comparison failed after {max_retries} attempts: {last_error}")
    raise Exception(f"Comparison failed after {max_retries} retries: {last_error}")


async def generate_impact_summary(paper: dict, match_logs: list, prompt_config: dict = None) -> Optional[str]:
    """Generate a scientific impact summary for a converged paper using its content and match logs."""
    model_info = _pick_round_robin_model()
    provider = model_info["provider"]
    model = model_info["model"]

    paper_content = _build_paper_content(paper)

    # Build match context — sample of wins and losses with reasoning
    wins = [m for m in match_logs if m.get("won") and m.get("reasoning")]
    losses = [m for m in match_logs if not m.get("won") and m.get("reasoning")]

    win_sample = wins[:8]
    loss_sample = losses[:5]

    match_context = ""
    if win_sample:
        match_context += "Key wins (why experts preferred this paper):\n"
        for m in win_sample:
            match_context += f"- vs \"{m['opponent_title']}\": {m['reasoning'][:200]}\n"
    if loss_sample:
        match_context += "\nNotable losses (where other papers were preferred):\n"
        for m in loss_sample:
            match_context += f"- vs \"{m['opponent_title']}\": {m['reasoning'][:200]}\n"

    win_rate = len(wins) / max(len(wins) + len(losses), 1) * 100

    if prompt_config:
        system_msg = prompt_config.get("system_prompt", "")
        user_template = prompt_config.get("user_prompt", "")
    else:
        system_msg = "You are a scientific impact analyst. Write a 150-200 word summary of the paper's impact."
        user_template = "Paper: \"{title}\"\n{paper_content}\n\nTournament: {win_rate}% win rate across {num_matches} comparisons.\n{match_context}\n\nWrite the summary."

    prompt = user_template.format(
        title=paper["title"],
        authors=", ".join(paper.get("authors", [])[:5]),
        paper_content=paper_content,
        win_rate=f"{win_rate:.0f}",
        num_matches=str(len(wins) + len(losses)),
        match_context=match_context,
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"summary-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model(provider, model)

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: asyncio.run(chat.send_message(UserMessage(text=prompt))),
        )
        if response and response.strip():
            return response.strip()
    except Exception as e:
        logger.error(f"Summary generation failed for {paper.get('title', '')[:50]}: {e}")

    return None
