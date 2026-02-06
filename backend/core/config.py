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

# Default evaluation prompt for robotics papers
DEFAULT_EVALUATION_PROMPT = {
    "system_prompt": """You are simulating the collective judgment of a diverse crowd of expert robotics researchers. Your task is to PREDICT which paper a group of 100 expert robotics professors, reviewers, and industry researchers would consider more impactful.

Think about:
1. What would senior robotics professors and principal investigators value?
2. What would top robotics conference (ICRA, IROS, RSS, CoRL) reviewers look for?
3. What would industry robotics leaders (Boston Dynamics, Tesla Bot, Google DeepMind) find compelling?
4. Which paper would receive more citations in the next 3 years?
5. Which represents a more significant contribution to the field?

Experts typically value:
- Novel manipulation, locomotion, or perception approaches
- Real-world robot experiments (not just simulation)
- Practical deployability and robustness
- Clear advancement over prior work
- Potential to open new research directions

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation of why experts would prefer this paper (max 150 words)"}""",
    "user_prompt": """You are predicting which paper a crowd of 100 robotics domain experts would vote as more impactful.

**Paper 1: {paper1_title}**
{paper1_content}

**Paper 2: {paper2_title}**
{paper2_content}

Which paper would the majority of robotics experts consider more scientifically impactful? Predict the crowd's preference. Respond with JSON only."""
}

# Default settings
DEFAULT_SETTINGS = {
    "key": "global",
    "admin_password": "papersumo2025",
    "fetch_interval_hours": 24,
    "max_papers_per_fetch": 50,
    "comparisons_per_round": 50,
    "parallel_agents": 5,
    "top_k_focus": 10,
    "exploration_constant": 1.414,
    "anchor_comparisons": 4,
    "min_matches_per_paper": 3,
    "ci_target": 200,
    "paused": False,
}
