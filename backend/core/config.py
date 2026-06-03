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

# Default settings
DEFAULT_SETTINGS = {
    "key": "global",
    "admin_password": os.environ["ADMIN_PASSWORD"],
    "active_categories": list(CATEGORIES.keys()),
    "fetch_interval_hours": 6,
    "fetch_delay_minutes": 8,
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
    "max_initial_backlog": 200,
}
