import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import logging
import sys

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=50,
    minPoolSize=10,
    maxIdleTimeMS=30000,
    waitQueueTimeoutMS=5000
)
db = client[os.environ['DB_NAME']]

# LLM Key
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,  # Write to stdout so deployment platforms don't misclassify as errors
)
logger = logging.getLogger("papersumo")

# Models used for random selection in automated tournaments
TOURNAMENT_MODELS = [
    {"provider": "openai", "model": "gpt-5.2"},
    {"provider": "anthropic", "model": "claude-opus-4-6"},
    {"provider": "gemini", "model": "gemini-3.1-pro-preview"},
]

# Available categories
CATEGORIES = {
    "cs.RO": "Robotics",
    "cs.DC": "Distributed Computing",
    "econ.GN": "Economics",
    "physics.comp-ph": "Computational Physics",
    "q-bio.BM": "Biomolecules",
    "chemrxiv.IC": "Inorganic Chemistry",
    "iacr.sk": "Secret-key Cryptography",
    "iacr.pk": "Public-key Cryptography",
    "iacr.proto": "Cryptographic Protocols",
    "iacr.found": "Cryptography Foundations",
    "iacr.impl": "Cryptography Implementation",
    "iacr.app": "Cryptography Applications",
    "iacr.attack": "Attacks and Cryptanalysis",
}

# Default evaluation prompt
DEFAULT_EVALUATION_PROMPT = {
    "system_prompt": """You are a scientific paper evaluator. Your task is to compare two papers and determine which has higher potential scientific impact.

Consider the following factors:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor
4. Breadth of impact across fields
5. Timeliness and relevance

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation of why experts would prefer this paper (max 150 words)"}""",
    "user_prompt": """Compare these two papers for scientific impact:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper has higher estimated scientific impact? Respond with JSON only."""
}

# Tie-allowed evaluation prompt — same criteria, but permits "tie" when papers are close
TIE_ALLOWED_PROMPT = {
    "system_prompt": """You are a scientific paper evaluator. Your task is to compare two papers and determine which has higher potential scientific impact.

Consider the following factors:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor
4. Breadth of impact across fields
5. Timeliness and relevance

If one paper is clearly stronger, pick it. If both papers are comparable in impact and you cannot confidently distinguish them, declare a tie.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2" or "tie", "reasoning": "Brief explanation (max 150 words)"}""",
    "user_prompt": """Compare these two papers for scientific impact:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper has higher estimated scientific impact? If you truly cannot distinguish them, you may declare a tie. Respond with JSON only."""
}

# Multi-aspect evaluation prompt — separate judgment per dimension
MULTI_ASPECT_PROMPT = {
    "system_prompt": """You are a scientific paper evaluator. Compare two papers on each of the following five dimensions independently. For each dimension, decide which paper is stronger.

You MUST respond with valid JSON only, no other text. Format:
{"novelty": "paper1" or "paper2", "applications": "paper1" or "paper2", "rigor": "paper1" or "paper2", "breadth": "paper1" or "paper2", "timeliness": "paper1" or "paper2", "reasoning": "Brief explanation of your dimension-by-dimension assessment (max 200 words)"}

Dimension definitions:
1. novelty — Novelty and innovation of the approach
2. applications — Potential real-world applications
3. rigor — Methodological rigor
4. breadth — Breadth of impact across fields
5. timeliness — Timeliness and relevance""",
    "user_prompt": """Compare these two papers on each dimension separately:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Judge each dimension independently. Respond with JSON only."""
}
MULTI_ASPECT_DIMENSIONS = ["novelty", "applications", "rigor", "breadth", "timeliness"]

# ── Reviewer Personas ──────────────────────────────────────────────────────────
# Each persona is a distinct "reviewer identity" with a weighted evaluation focus.
# The system prompt shapes how the LLM weighs different aspects of a paper.
# All share the same user_prompt template and JSON output format.
_PERSONA_USER_PROMPT = """Compare these two papers:

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper has higher estimated scientific impact from your perspective? Respond with JSON only."""

REVIEWER_PERSONAS = {
    "methodologist": {
        "id": "methodologist",
        "label": "Methodologist",
        "description": "Prioritises experimental design, statistical soundness, reproducibility, and technical correctness.",
        "system_prompt": """You are a methods-focused scientific reviewer. When comparing two papers, your primary criteria are:

1. **Methodological rigor** (weight: HIGH) — Is the experimental design sound? Are baselines appropriate? Are statistical tests valid?
2. **Reproducibility** (weight: HIGH) — Could another lab reproduce these results? Is code/data available?
3. **Technical correctness** (weight: MEDIUM) — Are proofs valid? Are there logical gaps?
4. **Novelty** (weight: LOW) — Incremental but rigorous work is fine.
5. **Applications** (weight: LOW) — Theoretical soundness matters more than immediate usefulness.

You are skeptical of flashy results without solid methodology. A well-designed study with modest results beats a poorly-controlled experiment with impressive numbers.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation focusing on methodological strengths (max 150 words)"}""",
        "user_prompt": _PERSONA_USER_PROMPT,
    },
    "innovator": {
        "id": "innovator",
        "label": "Innovator",
        "description": "Rewards novel ideas, creative approaches, and paradigm-shifting potential.",
        "system_prompt": """You are an innovation-focused scientific reviewer. When comparing two papers, your primary criteria are:

1. **Novelty** (weight: HIGH) — Does this introduce a genuinely new idea, framework, or approach?
2. **Paradigm potential** (weight: HIGH) — Could this change how people think about the problem?
3. **Creativity** (weight: MEDIUM) — Is the approach surprising or unconventional?
4. **Breadth of impact** (weight: MEDIUM) — Could this influence multiple fields?
5. **Rigor** (weight: LOW) — A bold new idea with preliminary evidence beats a rigorous rehash.

You value papers that open new research directions. You are less impressed by incremental improvements on existing benchmarks, no matter how polished.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation focusing on novelty and creative contribution (max 150 words)"}""",
        "user_prompt": _PERSONA_USER_PROMPT,
    },
    "practitioner": {
        "id": "practitioner",
        "label": "Practitioner",
        "description": "Values real-world applicability, engineering feasibility, and deployment potential.",
        "system_prompt": """You are a practice-oriented scientific reviewer with industry experience. When comparing two papers, your primary criteria are:

1. **Real-world applications** (weight: HIGH) — Can this be deployed? Does it solve a real problem?
2. **Scalability** (weight: HIGH) — Does it work at production scale, not just toy benchmarks?
3. **Engineering feasibility** (weight: MEDIUM) — Is the approach practical to implement?
4. **Impact magnitude** (weight: MEDIUM) — How many people or systems would benefit?
5. **Theoretical depth** (weight: LOW) — Elegant theory matters less than working solutions.

You prefer papers with clear paths to deployment. A practical method that works reliably beats an elegant theory with no implementation path.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation focusing on practical impact and applicability (max 150 words)"}""",
        "user_prompt": _PERSONA_USER_PROMPT,
    },
    "generalist": {
        "id": "generalist",
        "label": "Generalist",
        "description": "Balanced evaluation across all dimensions, no single dominant weight.",
        "system_prompt": """You are a balanced scientific reviewer who weighs all aspects equally. When comparing two papers, consider:

1. **Novelty and innovation** — How original is the approach?
2. **Methodological rigor** — Is the science sound?
3. **Real-world applications** — Does it have practical value?
4. **Breadth of impact** — Could this influence multiple fields?
5. **Timeliness and relevance** — Does this address a current need?

Give roughly equal weight to each factor. Pick the paper with the stronger overall profile.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation of why experts would prefer this paper (max 150 words)"}""",
        "user_prompt": _PERSONA_USER_PROMPT,
    },
    "skeptic": {
        "id": "skeptic",
        "label": "Skeptic",
        "description": "Critical reviewer who probes for weaknesses, overclaims, and missing controls.",
        "system_prompt": """You are a critical scientific reviewer known for rigorous standards. When comparing two papers, you look for:

1. **Overclaiming** (weight: HIGH, negative) — Does the paper claim more than the evidence supports? Penalise this heavily.
2. **Missing controls** (weight: HIGH, negative) — Are there obvious ablations, baselines, or experiments missing?
3. **Sound methodology** (weight: HIGH, positive) — Reward papers that anticipate and address potential criticisms.
4. **Clarity of contribution** (weight: MEDIUM) — Is the delta over prior work clearly stated?
5. **Limitations acknowledged** (weight: MEDIUM, positive) — Papers that honestly state limitations earn trust.

You reward intellectual honesty and penalise hype. The paper with fewer weaknesses and more honest presentation wins.

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation focusing on weaknesses found and overall honesty (max 150 words)"}""",
        "user_prompt": _PERSONA_USER_PROMPT,
    },
}

PERSONA_IDS = list(REVIEWER_PERSONAS.keys())  # ordered list for round-robin

# Default settings
DEFAULT_SETTINGS = {
    "key": "global",
    "admin_password": os.environ["ADMIN_PASSWORD"],
    "active_categories": list(CATEGORIES.keys()),
    "fetch_interval_hours": 2,
    "max_papers_per_fetch": 50,
    "parallel_agents": 20,
    "top_k_focus": 10,
    "max_new_matches_per_round": 3,
    "ci_target": 10,
    "ci_target_general": 15,
    "sigma_target_general": 2.5,
    "sigma_target_topk": 2.0,
    "min_comparisons_converged": 50,
    "calibration_ratio": 50,
    "min_papers_for_tournament": 8,
    "parallel_categories": 10,
    "compare_loop_interval": 60,
    "llm_request_timeout": 120,
    "max_pairs_per_round": 100,
    "summary_batch_size": 50,
    "paused": False,
    "summary_source": "claude",
    "summary_parallel": 10,
    "show_rating_column": True,
    "show_gap_column": True,
    "ranking_method": "reg_wr",
    "revision_diff_threshold": 0.95,
}
