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


async def compare_papers(paper1: dict, paper2: dict, prompt_config: dict = None, abstract_only: bool = False) -> Dict:
    if prompt_config is None:
        prompt_config = DEFAULT_EVALUATION_PROMPT

    model_info = _pick_random_model()
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
    model_info = _pick_random_model()
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
