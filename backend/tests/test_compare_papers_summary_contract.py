"""Regression test: compare_papers must use the summary field the caller provides.

Context: llm.py previously had a fallback chain reading
    ai_impact_summary_thinking → ai_impact_summary_opus46 → ai_impact_summary
which silently overrode what the caller passed in `ai_impact_summary`. That chain
was migration scar tissue and is now removed. This test pins the contract so it
cannot be reintroduced.
"""
import re
from pathlib import Path


LLM_FILE = Path(__file__).resolve().parent.parent / "services" / "llm.py"


def _extract_branch(text: str, branch_key: str) -> str:
    """Extract an `elif content_mode == "<branch_key>":` block up to the next `elif`/`else`."""
    pattern = rf'elif content_mode == "{branch_key}":(.*?)(?=\n    (?:elif content_mode|else:))'
    m = re.search(pattern, text, re.DOTALL)
    assert m, f"Branch {branch_key!r} not found in llm.py"
    return m.group(1)


def test_abstract_plus_summary_has_no_legacy_key_fallbacks():
    src = LLM_FILE.read_text()
    branch = _extract_branch(src, "abstract_plus_summary")
    assert "ai_impact_summary_thinking" not in branch, (
        "abstract_plus_summary branch must not read ai_impact_summary_thinking — "
        "caller (e.g. scheduler) is responsible for injecting the correct summary "
        "into ai_impact_summary."
    )
    assert "ai_impact_summary_opus46" not in branch, (
        "abstract_plus_summary branch must not read ai_impact_summary_opus46 — "
        "this field was migration-era residue and no longer exists on paper docs."
    )
    # It should still read the one canonical field.
    assert "paper1.get('ai_impact_summary'" in branch
    assert "paper2.get('ai_impact_summary'" in branch


def test_unknown_mode_fallback_has_no_legacy_key_fallbacks():
    src = LLM_FILE.read_text()
    # The else branch lives just before `prompt = user_template.format(`.
    m = re.search(r'else:\s*\n\s*# Unknown mode.*?(?=\n    prompt = user_template\.format)',
                  src, re.DOTALL)
    assert m, "Unknown-mode else branch not found"
    branch = m.group()
    assert "ai_impact_summary_thinking" not in branch
    assert "paper1.get('ai_impact_summary'" in branch
