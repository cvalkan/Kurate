import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import logging

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("papersumo")

# Models used for random selection in automated tournaments
TOURNAMENT_MODELS = [
    {"provider": "openai", "model": "gpt-5.2"},
    {"provider": "anthropic", "model": "claude-opus-4-5-20251101"},
    {"provider": "gemini", "model": "gemini-3-pro-preview"},
]

# Available categories
CATEGORIES = {
    "cs.RO": "Robotics",
    "cs.DC": "Distributed Computing",
    "q-fin.EC": "Economics",
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

# Default settings
DEFAULT_SETTINGS = {
    "key": "global",
    "admin_password": "papersumo2025",
    "active_categories": list(CATEGORIES.keys()),
    "fetch_interval_hours": 24,
    "max_papers_per_fetch": 50,
    "parallel_agents": 5,
    "top_k_focus": 10,
    "exploration_constant": 1.414,
    "anchor_comparisons": 4,
    "min_matches_per_paper": 3,
    "max_matches_per_paper": 150,
    "ci_target": 12,
    "paused": False,
}
