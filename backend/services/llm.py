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
        return full_text
    except Exception as e:
        logger.error(f"Failed to download/extract PDF from {pdf_url}: {e}")
        return None


def extract_key_sections(full_text: str) -> Dict[str, str]:
    sections = {"introduction": "", "methodology": "", "results": "", "conclusion": ""}
    text_lower = full_text.lower()

    intro_markers = ["introduction", "1. introduction", "1 introduction"]
    method_markers = ["method", "methodology", "approach", "2. method", "3. method"]
    results_markers = ["result", "experiment", "evaluation", "4. result"]
    conclusion_markers = ["conclusion", "discussion", "summary", "6. conclusion"]

    def find_section(markers, next_markers=None):
        for marker in markers:
            idx = text_lower.find(marker)
            if idx != -1:
                end_idx = len(full_text)
                if next_markers:
                    for nm in next_markers:
                        nm_idx = text_lower.find(nm, idx + len(marker))
                        if nm_idx != -1 and nm_idx < end_idx:
                            end_idx = nm_idx
                section_text = full_text[idx:min(idx + 2500, end_idx)]
                return section_text[:2000]
        return ""

    sections["introduction"] = find_section(intro_markers, method_markers)
    sections["methodology"] = find_section(method_markers, results_markers)
    sections["results"] = find_section(results_markers, conclusion_markers)
    sections["conclusion"] = find_section(conclusion_markers)
    return sections


def _build_paper_content(paper: dict) -> str:
    if paper.get("full_text"):
        sections = extract_key_sections(paper["full_text"])
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


def _pick_random_model() -> Dict[str, str]:
    return random.choice(TOURNAMENT_MODELS)


async def compare_papers(paper1: dict, paper2: dict, prompt_config: dict = None) -> Dict:
    if prompt_config is None:
        prompt_config = DEFAULT_EVALUATION_PROMPT

    model_info = _pick_random_model()
    provider = model_info["provider"]
    model = model_info["model"]

    system_msg = prompt_config["system_prompt"]
    user_template = prompt_config["user_prompt"]

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
