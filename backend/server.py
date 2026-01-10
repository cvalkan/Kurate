from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
import httpx
import asyncio
import json
import math
import xml.etree.ElementTree as ET
from emergentintegrations.llm.chat import LlmChat, UserMessage
from PyPDF2 import PdfReader
import io
import tempfile

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# LLM API Key
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ArXiv Categories
ARXIV_CATEGORIES = {
    "cs.AI": "Artificial Intelligence",
    "cs.CL": "Computation and Language",
    "cs.CV": "Computer Vision",
    "cs.LG": "Machine Learning",
    "cs.NE": "Neural and Evolutionary Computing",
    "cs.RO": "Robotics",
    "cs.SE": "Software Engineering",
    "cs.CR": "Cryptography and Security",
    "cs.DB": "Databases",
    "cs.DC": "Distributed Computing",
    "stat.ML": "Machine Learning (Statistics)",
    "physics.gen-ph": "General Physics",
    "physics.comp-ph": "Computational Physics",
    "math.NA": "Numerical Analysis",
    "math.OC": "Optimization and Control",
    "q-bio.NC": "Neurons and Cognition",
    "q-bio.GN": "Genomics",
    "econ.EM": "Econometrics",
    "astro-ph": "Astrophysics",
    "cond-mat": "Condensed Matter",
    "hep-th": "High Energy Physics - Theory",
    "quant-ph": "Quantum Physics"
}

# Pydantic Models
class Paper(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str
    categories: List[str]
    published: str
    link: str
    pdf_link: Optional[str] = None
    full_text: Optional[str] = None  # For deep analysis
    citation_count: Optional[int] = None  # From Semantic Scholar

class Match(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    paper1_id: str
    paper2_id: str
    winner_id: Optional[str] = None
    reasoning: Optional[str] = None
    completed: bool = False
    round_num: int = 0

class TournamentConfig(BaseModel):
    category: str
    num_papers: int = 10
    parallel_agents: int = 3
    deep_analysis: bool = False

class SearchQuery(BaseModel):
    keywords: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    max_results: int = 20

class UCBConfig(BaseModel):
    enabled: bool = False
    exploration_constant: float = 1.414  # sqrt(2) is standard
    min_comparisons_per_paper: int = 3  # Minimum comparisons before stopping
    max_total_comparisons: Optional[int] = None  # None = auto-calculate
    convergence_threshold: float = 0.05  # Stop if top rankings stable
    target_top_k: Optional[int] = None  # Focus on finding accurate top-k (None = rank all)
    confidence_level: float = 0.95  # Confidence level for intervals (0.95 = 95%)

class Tournament(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str
    category_name: str
    num_papers: int
    parallel_agents: int
    deep_analysis: bool = False
    search_query: Optional[str] = None
    ranking_mode: str = "round_robin"  # "round_robin" or "ucb"
    ucb_config: Optional[Dict[str, Any]] = None
    status: str = "pending"
    papers: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    rankings: List[Dict[str, Any]] = []
    scores: Dict[str, float] = {}
    paper_stats: Dict[str, Dict[str, Any]] = {}  # UCB stats per paper
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    progress: int = 0
    total_matches: int = 0
    current_log: str = ""

class TournamentCreate(BaseModel):
    category: Optional[str] = None
    num_papers: int = 10
    parallel_agents: int = 3
    deep_analysis: bool = False
    paper_ids: Optional[List[str]] = None
    papers: Optional[List[Dict[str, Any]]] = None
    search_query: Optional[str] = None
    ranking_mode: str = "round_robin"  # "round_robin" or "ucb"
    ucb_config: Optional[UCBConfig] = None

class CompareRequest(BaseModel):
    paper1: Dict[str, Any]
    paper2: Dict[str, Any]

# Store active tournaments for SSE
active_tournaments: Dict[str, Dict[str, Any]] = {}

# Helper Functions
async def download_and_extract_pdf(pdf_url: str) -> Optional[str]:
    """Download PDF and extract text content"""
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(pdf_url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
            
        # Read PDF content
        pdf_bytes = io.BytesIO(response.content)
        reader = PdfReader(pdf_bytes)
        
        # Extract text from all pages
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        
        full_text = "\n".join(text_parts)
        
        # Clean up the text
        full_text = " ".join(full_text.split())  # Normalize whitespace
        
        return full_text
    except Exception as e:
        logger.error(f"Failed to download/extract PDF from {pdf_url}: {e}")
        return None

def extract_key_sections(full_text: str) -> Dict[str, str]:
    """Extract key sections from paper text"""
    sections = {
        "introduction": "",
        "methodology": "",
        "results": "",
        "conclusion": ""
    }
    
    text_lower = full_text.lower()
    
    # Common section markers
    intro_markers = ["introduction", "1. introduction", "1 introduction", "i. introduction"]
    method_markers = ["method", "methodology", "approach", "2. method", "3. method", "ii. method"]
    results_markers = ["result", "experiment", "evaluation", "4. result", "5. result"]
    conclusion_markers = ["conclusion", "discussion", "summary", "6. conclusion", "7. conclusion"]
    
    def find_section(markers, next_markers=None):
        for marker in markers:
            idx = text_lower.find(marker)
            if idx != -1:
                # Find end of section (next section or end of text)
                end_idx = len(full_text)
                if next_markers:
                    for nm in next_markers:
                        nm_idx = text_lower.find(nm, idx + len(marker))
                        if nm_idx != -1 and nm_idx < end_idx:
                            end_idx = nm_idx
                
                # Extract section (limit to ~2000 chars)
                section_text = full_text[idx:min(idx + 2500, end_idx)]
                return section_text[:2000]
        return ""
    
    sections["introduction"] = find_section(intro_markers, method_markers)
    sections["methodology"] = find_section(method_markers, results_markers)
    sections["results"] = find_section(results_markers, conclusion_markers)
    sections["conclusion"] = find_section(conclusion_markers)
    
    return sections

async def fetch_arxiv_papers(category: str, max_results: int = 10) -> List[Paper]:
    """Fetch papers from arXiv API by category"""
    base_url = "https://export.arxiv.org/api/query"
    query = f"cat:{category}"
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }
    
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(base_url, params=params, timeout=30.0)
        response.raise_for_status()
    
    return parse_arxiv_response(response.text)

async def search_arxiv_papers(
    keywords: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_results: int = 20
) -> List[Paper]:
    """Search papers from arXiv API with multiple filters - uses parallel fetching for speed"""
    import time
    start_time = time.time()
    
    base_url = "http://export.arxiv.org/api/query"  # HTTP is faster than HTTPS for arXiv
    
    # Build query parts
    query_parts = []
    exact_phrase = None  # Track if user wants exact phrase matching
    
    if keywords:
        keywords_clean = keywords.strip()
        # Check if user wants exact phrase (wrapped in quotes)
        if keywords_clean.startswith('"') and keywords_clean.endswith('"'):
            # Exact phrase search
            exact_phrase = keywords_clean[1:-1].lower()  # Store for local filtering
            words = exact_phrase.split()
            if len(words) > 1:
                # Multi-word phrase: use all: field with AND, fetch more for filtering
                word_queries = [f'all:{word}' for word in words]
                query_parts.append(f'({" AND ".join(word_queries)})')
            else:
                query_parts.append(f'all:{exact_phrase}')
        else:
            # Regular search - search in title and abstract with AND between words
            words = keywords_clean.split()
            if len(words) > 1:
                word_queries = []
                for word in words:
                    word_queries.append(f'(ti:{word} OR abs:{word})')
                query_parts.append(f'({" AND ".join(word_queries)})')
            else:
                query_parts.append(f'(ti:{keywords_clean} OR abs:{keywords_clean})')
    
    if author:
        author_clean = author.strip()
        query_parts.append(f'au:{author_clean}')
    
    if category:
        query_parts.append(f'cat:{category}')
    
    # Combine query parts with AND
    if query_parts:
        query = " AND ".join(query_parts)
    else:
        query = "all:*"
    
    logger.info(f"ArXiv search query: {query}")
    
    # Fetch more results if exact phrase filtering needed
    fetch_count = max_results * 5 if exact_phrase else max_results
    fetch_count = min(fetch_count, 200)  # Hard cap
    
    # Single request to arXiv - parallel batching doesn't help due to rate limiting
    params = {
        "search_query": query,
        "start": 0,
        "max_results": fetch_count,
        "sortBy": "relevance",
        "sortOrder": "descending"
    }
    
    logger.info(f"ArXiv API call starting... (time so far: {time.time() - start_time:.2f}s)")
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as http_client:
        response = await http_client.get(base_url, params=params)
        response.raise_for_status()
    logger.info(f"ArXiv API response received (time so far: {time.time() - start_time:.2f}s)")
    
    papers = parse_arxiv_response(response.text)
    logger.info(f"Parsed {len(papers)} papers (time so far: {time.time() - start_time:.2f}s)")
    
    # Filter for exact phrase if specified
    if exact_phrase:
        filtered_papers = []
        for paper in papers:
            title_lower = paper.title.lower()
            abstract_lower = paper.abstract.lower()
            # Check if exact phrase appears in title or abstract
            if exact_phrase in title_lower or exact_phrase in abstract_lower:
                filtered_papers.append(paper)
            if len(filtered_papers) >= max_results:
                break
        papers = filtered_papers
        logger.info(f"Exact phrase filter: {len(papers)} papers contain '{exact_phrase}'")
    
    # Filter by date if specified
    if date_from or date_to:
        filtered_papers = []
        for paper in papers:
            pub_date = paper.published[:10]
            if date_from and pub_date < date_from:
                continue
            if date_to and pub_date > date_to:
                continue
            filtered_papers.append(paper)
        papers = filtered_papers
    
    # Return papers immediately - citations fetched separately for speed
    return papers

async def fetch_citation_counts(papers: List[Paper]) -> List[Paper]:
    """Fetch citation counts from Semantic Scholar for a list of papers"""
    if not papers:
        return papers
    
    # Semantic Scholar API - batch lookup by arXiv IDs
    arxiv_ids = [f"ARXIV:{p.arxiv_id.split('v')[0]}" for p in papers]  # Remove version number
    
    try:
        async with httpx.AsyncClient() as client:
            # Semantic Scholar batch endpoint (up to 500 papers)
            response = await client.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                params={"fields": "citationCount"},
                json={"ids": arxiv_ids[:100]},  # Limit to 100 for performance
                timeout=15.0
            )
            
            if response.status_code == 200:
                results = response.json()
                # Map results back to papers
                for i, paper in enumerate(papers[:100]):
                    if i < len(results) and results[i]:
                        paper.citation_count = results[i].get('citationCount', 0)
                    else:
                        paper.citation_count = None
            else:
                logger.warning(f"Semantic Scholar API returned {response.status_code}")
                
    except Exception as e:
        logger.warning(f"Failed to fetch citation counts: {e}")
        # Continue without citation counts
    
    return papers

def parse_arxiv_response(xml_text: str) -> List[Paper]:
    """Parse arXiv API XML response into Paper objects"""
    root = ET.fromstring(xml_text)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    
    papers = []
    for entry in root.findall('atom:entry', ns):
        arxiv_id = entry.find('atom:id', ns).text.split('/abs/')[-1]
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        abstract = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
        published = entry.find('atom:published', ns).text
        
        authors = []
        for author in entry.findall('atom:author', ns):
            name = author.find('atom:name', ns).text
            authors.append(name)
        
        categories = []
        for cat in entry.findall('atom:category', ns):
            categories.append(cat.get('term'))
        
        link = entry.find('atom:id', ns).text
        pdf_link = None
        for l in entry.findall('atom:link', ns):
            if l.get('title') == 'pdf':
                pdf_link = l.get('href')
        
        paper = Paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors[:5],  # Limit authors
            abstract=abstract[:1500],  # Limit abstract length
            categories=categories,
            published=published,
            link=link,
            pdf_link=pdf_link
        )
        papers.append(paper)
    
    return papers

async def compare_papers_llm(paper1: Dict, paper2: Dict, deep_analysis: bool = False) -> Dict:
    """Use LLM to compare two papers for scientific impact"""
    
    if deep_analysis:
        # Deep analysis mode - use full paper content
        system_msg = """You are an expert scientific paper evaluator conducting a DEEP ANALYSIS. 
You have access to key sections from both papers (introduction, methodology, results, conclusion).

Evaluate based on:
1. Novelty and innovation of the approach
2. Methodological rigor and experimental design
3. Quality and significance of results
4. Potential real-world impact and applications
5. Clarity of contribution and reproducibility
6. Breadth of impact across the field

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Detailed explanation (max 200 words)"}"""
        
        # Build detailed content for each paper
        p1_content = f"**Title:** {paper1['title']}\n\n"
        p2_content = f"**Title:** {paper2['title']}\n\n"
        
        if paper1.get('full_text'):
            sections1 = extract_key_sections(paper1['full_text'])
            p1_content += f"**Abstract:** {paper1['abstract'][:500]}\n\n"
            if sections1['introduction']:
                p1_content += f"**Introduction:** {sections1['introduction'][:1000]}\n\n"
            if sections1['methodology']:
                p1_content += f"**Methodology:** {sections1['methodology'][:1000]}\n\n"
            if sections1['results']:
                p1_content += f"**Results:** {sections1['results'][:800]}\n\n"
            if sections1['conclusion']:
                p1_content += f"**Conclusion:** {sections1['conclusion'][:500]}\n"
        else:
            p1_content += f"**Abstract:** {paper1['abstract'][:1200]}\n"
        
        if paper2.get('full_text'):
            sections2 = extract_key_sections(paper2['full_text'])
            p2_content += f"**Abstract:** {paper2['abstract'][:500]}\n\n"
            if sections2['introduction']:
                p2_content += f"**Introduction:** {sections2['introduction'][:1000]}\n\n"
            if sections2['methodology']:
                p2_content += f"**Methodology:** {sections2['methodology'][:1000]}\n\n"
            if sections2['results']:
                p2_content += f"**Results:** {sections2['results'][:800]}\n\n"
            if sections2['conclusion']:
                p2_content += f"**Conclusion:** {sections2['conclusion'][:500]}\n"
        else:
            p2_content += f"**Abstract:** {paper2['abstract'][:1200]}\n"
        
        prompt = f"""Perform a DEEP ANALYSIS comparison of these two scientific papers:

=== PAPER 1 ===
{p1_content}

=== PAPER 2 ===
{p2_content}

Based on your thorough analysis of both papers' content, methodology, and findings, which paper has higher scientific impact? Respond with JSON only."""
        
    else:
        # Standard mode - abstract only
        system_msg = """You are a scientific paper evaluator. Your task is to compare two papers and determine which has higher potential scientific impact.

Consider the following factors:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor (based on abstract)
4. Breadth of impact across fields
5. Timeliness and relevance

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation (max 100 words)"}"""
        
        prompt = f"""Compare these two papers for scientific impact:

**Paper 1: {paper1['title']}**
Abstract: {paper1['abstract'][:800]}

**Paper 2: {paper2['title']}**
Abstract: {paper2['abstract'][:800]}

Which paper has higher estimated scientific impact? Respond with JSON only."""
    
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"compare-{uuid.uuid4()}",
        system_message=system_msg
    ).with_model("openai", "gpt-5.2")
    
    try:
        response = await chat.send_message(UserMessage(text=prompt))
        # Parse JSON response
        response_text = response.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        result = json.loads(response_text)
        return result
    except Exception as e:
        logger.error(f"LLM comparison error: {e}")
        # Fallback: random selection
        import random
        return {
            "winner": random.choice(["paper1", "paper2"]),
            "reasoning": "Comparison failed, random selection applied."
        }

def calculate_bradley_terry(matches: List[Dict], paper_ids: List[str]) -> Dict[str, float]:
    """Calculate Bradley-Terry scores from pairwise comparisons"""
    n = len(paper_ids)
    if n == 0:
        return {}
    
    # Initialize scores
    scores = {pid: 1.0 for pid in paper_ids}
    
    # Count wins for each paper
    wins = {pid: 0 for pid in paper_ids}
    comparisons = {pid: 0 for pid in paper_ids}
    
    for match in matches:
        if match.get('completed') and match.get('winner_id'):
            p1, p2 = match['paper1_id'], match['paper2_id']
            winner = match['winner_id']
            wins[winner] = wins.get(winner, 0) + 1
            comparisons[p1] = comparisons.get(p1, 0) + 1
            comparisons[p2] = comparisons.get(p2, 0) + 1
    
    # Iterative Bradley-Terry estimation
    for _ in range(50):  # 50 iterations
        new_scores = {}
        for pid in paper_ids:
            if comparisons[pid] > 0:
                denominator = 0
                for match in matches:
                    if match.get('completed') and match.get('winner_id'):
                        p1, p2 = match['paper1_id'], match['paper2_id']
                        if pid == p1:
                            denominator += 1.0 / (scores[p1] + scores[p2])
                        elif pid == p2:
                            denominator += 1.0 / (scores[p1] + scores[p2])
                
                if denominator > 0:
                    new_scores[pid] = wins[pid] / denominator
                else:
                    new_scores[pid] = scores[pid]
            else:
                new_scores[pid] = scores[pid]
        
        # Normalize
        total = sum(new_scores.values())
        if total > 0:
            scores = {k: v / total * n for k, v in new_scores.items()}
        else:
            scores = new_scores
    
    return scores

def generate_round_robin_matches(papers: List[Dict]) -> List[Match]:
    """Generate all pairwise matches for round-robin tournament"""
    matches = []
    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            match = Match(
                paper1_id=papers[i]['id'],
                paper2_id=papers[j]['id'],
                round_num=1
            )
            matches.append(match)
    return matches

# UCB Algorithm Implementation
def calculate_wilson_confidence_interval(wins: int, comparisons: int, confidence_level: float = 0.95) -> Dict:
    """
    Calculate Wilson score confidence interval for win rate.
    More accurate than normal approximation for small sample sizes.
    Returns: {win_rate, lower_bound, upper_bound, margin_of_error, confidence_level}
    """
    import math
    from scipy import stats as scipy_stats
    
    if comparisons == 0:
        return {
            'win_rate': 0.5,
            'lower_bound': 0.0,
            'upper_bound': 1.0,
            'margin_of_error': 0.5,
            'confidence_level': confidence_level,
            'comparisons': 0
        }
    
    p = wins / comparisons
    n = comparisons
    
    # Z-score for confidence level (e.g., 1.96 for 95%)
    z = scipy_stats.norm.ppf(1 - (1 - confidence_level) / 2)
    
    # Wilson score interval formula
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator
    
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    
    return {
        'win_rate': round(p, 4),
        'lower_bound': round(lower, 4),
        'upper_bound': round(upper, 4),
        'margin_of_error': round((upper - lower) / 2, 4),
        'confidence_level': confidence_level,
        'comparisons': comparisons
    }

def calculate_ucb_scores(paper_stats: Dict[str, Dict], total_comparisons: int, exploration_constant: float = 1.414) -> Dict[str, float]:
    """Calculate UCB scores for all papers"""
    import math
    ucb_scores = {}
    
    for paper_id, stats in paper_stats.items():
        wins = stats.get('wins', 0)
        comparisons = stats.get('comparisons', 0)
        
        if comparisons == 0:
            # Papers with no comparisons get infinite UCB (must be explored)
            ucb_scores[paper_id] = float('inf')
        else:
            win_rate = wins / comparisons
            # UCB1 formula: win_rate + c * sqrt(ln(total) / comparisons)
            exploration_bonus = exploration_constant * math.sqrt(math.log(total_comparisons + 1) / comparisons)
            ucb_scores[paper_id] = win_rate + exploration_bonus
    
    return ucb_scores

def select_ucb_pair(paper_ids: List[str], paper_stats: Dict[str, Dict], compared_pairs: set, 
                    total_comparisons: int, exploration_constant: float,
                    target_top_k: Optional[int] = None, eliminated_papers: Optional[set] = None) -> Optional[tuple]:
    """
    Select the best pair to compare using UCB.
    If target_top_k is set, prioritizes comparisons near the top-k boundary.
    """
    import math
    
    # Filter out eliminated papers
    active_papers = [p for p in paper_ids if not eliminated_papers or p not in eliminated_papers]
    
    if len(active_papers) < 2:
        return None
    
    ucb_scores = calculate_ucb_scores(paper_stats, total_comparisons, exploration_constant)
    
    # Sort papers by current win rate (for top-k boundary detection)
    sorted_by_winrate = sorted(
        active_papers,
        key=lambda x: paper_stats[x].get('wins', 0) / max(paper_stats[x].get('comparisons', 1), 1),
        reverse=True
    )
    
    # If targeting top-k, prioritize papers near the boundary
    if target_top_k and target_top_k < len(active_papers):
        # Focus zone: papers ranked k-2 to k+2 (around the boundary)
        boundary_start = max(0, target_top_k - 2)
        boundary_end = min(len(sorted_by_winrate), target_top_k + 3)
        boundary_papers = set(sorted_by_winrate[boundary_start:boundary_end])
        
        # Also include top-k papers that need more comparisons
        top_k_papers = set(sorted_by_winrate[:target_top_k])
        
        # Priority papers: those in boundary zone or top-k with low comparisons
        priority_papers = boundary_papers | {
            p for p in top_k_papers 
            if paper_stats[p].get('comparisons', 0) < 5
        }
    else:
        priority_papers = set(active_papers)
    
    # Find best pair
    best_pair = None
    best_score = -1
    
    # First, try to find pairs involving priority papers
    for p1 in priority_papers:
        for p2 in active_papers:
            if p1 == p2:
                continue
            pair_key = tuple(sorted([p1, p2]))
            if pair_key not in compared_pairs:
                # Score: sum of UCB scores, with bonus for priority papers
                pair_score = ucb_scores.get(p1, 0) + ucb_scores.get(p2, 0)
                if p2 in priority_papers:
                    pair_score *= 1.5  # Bonus for comparing two priority papers
                if pair_score > best_score:
                    best_score = pair_score
                    best_pair = (p1, p2)
    
    # Fallback to any pair if no priority pairs available
    if not best_pair:
        for i, p1 in enumerate(active_papers):
            for p2 in active_papers[i+1:]:
                pair_key = tuple(sorted([p1, p2]))
                if pair_key not in compared_pairs:
                    pair_score = ucb_scores.get(p1, 0) + ucb_scores.get(p2, 0)
                    if pair_score > best_score:
                        best_score = pair_score
                        best_pair = (p1, p2)
    
    return best_pair

def can_reach_top_k(paper_id: str, paper_stats: Dict[str, Dict], paper_ids: List[str], 
                    target_k: int, confidence_level: float = 0.95) -> bool:
    """
    Check if a paper can statistically still reach top-k position.
    Uses confidence intervals to determine if elimination is justified.
    """
    stats = paper_stats.get(paper_id, {})
    wins = stats.get('wins', 0)
    comparisons = stats.get('comparisons', 0)
    
    if comparisons < 3:
        return True  # Not enough data to eliminate
    
    # Calculate confidence interval for this paper
    ci = calculate_wilson_confidence_interval(wins, comparisons, confidence_level)
    paper_upper = ci['upper_bound']
    
    # Get win rates of papers currently in top-k
    sorted_papers = sorted(
        paper_ids,
        key=lambda x: paper_stats[x].get('wins', 0) / max(paper_stats[x].get('comparisons', 1), 1),
        reverse=True
    )
    
    if len(sorted_papers) <= target_k:
        return True
    
    # Get the k-th paper's lower confidence bound
    kth_paper = sorted_papers[target_k - 1]
    kth_stats = paper_stats.get(kth_paper, {})
    kth_ci = calculate_wilson_confidence_interval(
        kth_stats.get('wins', 0), 
        kth_stats.get('comparisons', 0), 
        confidence_level
    )
    kth_lower = kth_ci['lower_bound']
    
    # Paper can reach top-k if its upper bound exceeds k-th paper's lower bound
    return paper_upper >= kth_lower

def check_ucb_convergence(paper_stats: Dict[str, Dict], min_comparisons: int, 
                          convergence_threshold: float, previous_rankings: List[str],
                          target_top_k: Optional[int] = None) -> tuple:
    """
    Check if UCB rankings have converged.
    If target_top_k is set, only checks convergence of top-k papers.
    """
    # Check if all papers have minimum comparisons
    for stats in paper_stats.values():
        if stats.get('comparisons', 0) < min_comparisons:
            return False, []
    
    # Calculate current rankings by win rate
    current_rankings = sorted(
        paper_stats.keys(),
        key=lambda x: paper_stats[x].get('wins', 0) / max(paper_stats[x].get('comparisons', 1), 1),
        reverse=True
    )
    
    if not previous_rankings:
        return False, current_rankings
    
    # Check stability of top papers
    if target_top_k:
        # For top-k mode, only check if top-k is stable
        check_n = target_top_k
    else:
        # Default: check top 5 or all if fewer
        check_n = min(5, len(current_rankings))
    
    if current_rankings[:check_n] == previous_rankings[:check_n]:
        return True, current_rankings
    
    return False, current_rankings

def create_rankings(scores: Dict[str, float], paper_lookup: Dict, 
                    paper_stats: Optional[Dict] = None, confidence_level: float = 0.95) -> List[Dict]:
    """Create rankings list from scores with optional confidence intervals"""
    rankings = []
    for pid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        paper = paper_lookup[pid]
        ranking_entry = {
            "rank": len(rankings) + 1,
            "paper_id": pid,
            "title": paper['title'],
            "authors": paper.get('authors', []),
            "arxiv_id": paper.get('arxiv_id', ''),
            "link": paper.get('link', ''),
            "score": round(score, 4)
        }
        
        # Add confidence interval if paper_stats available
        if paper_stats and pid in paper_stats:
            stats = paper_stats[pid]
            wins = stats.get('wins', 0)
            comparisons = stats.get('comparisons', 0)
            ci = calculate_wilson_confidence_interval(wins, comparisons, confidence_level)
            ranking_entry['confidence'] = ci
        
        rankings.append(ranking_entry)
    return rankings

async def run_tournament(tournament_id: str):
    """Run the tournament with parallel LLM comparisons - supports Round Robin and UCB modes"""
    try:
        tournament_doc = await db.tournaments.find_one({"id": tournament_id}, {"_id": 0})
        if not tournament_doc:
            logger.error(f"Tournament {tournament_id} not found")
            return
        
        deep_analysis = tournament_doc.get('deep_analysis', False)
        ranking_mode = tournament_doc.get('ranking_mode', 'round_robin')
        ucb_config = tournament_doc.get('ucb_config', {})
        
        # Update status
        mode_label = "UCB" if ranking_mode == "ucb" else "Round Robin"
        if deep_analysis:
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"status": "running", "current_log": f"Deep Analysis + {mode_label}: Downloading papers..."}}
            )
        else:
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"status": "running", "current_log": f"{mode_label} Mode: Starting tournament..."}}
            )
        
        papers = tournament_doc['papers']
        parallel_agents = tournament_doc.get('parallel_agents', 3)
        
        # Download PDFs for deep analysis
        if deep_analysis:
            logger.info(f"Deep analysis mode: downloading {len(papers)} PDFs")
            for i, paper in enumerate(papers):
                if paper.get('pdf_link'):
                    await db.tournaments.update_one(
                        {"id": tournament_id},
                        {"$set": {"current_log": f"Downloading paper {i+1}/{len(papers)}: {paper['title'][:50]}..."}}
                    )
                    full_text = await download_and_extract_pdf(paper['pdf_link'])
                    if full_text:
                        paper['full_text'] = full_text
                    await asyncio.sleep(0.5)
            
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"papers": papers, "current_log": "PDFs downloaded. Starting comparisons..."}}
            )
        
        paper_lookup = {p['id']: p for p in papers}
        paper_ids = [p['id'] for p in papers]
        effective_parallel = min(parallel_agents, 2) if deep_analysis else parallel_agents
        
        if ranking_mode == "ucb":
            # UCB Mode - intelligent pair selection
            await run_ucb_tournament(tournament_id, papers, paper_lookup, paper_ids, 
                                     ucb_config, deep_analysis, effective_parallel)
        else:
            # Round Robin Mode - all pairs
            matches = tournament_doc['matches']
            await run_round_robin_tournament(tournament_id, papers, paper_lookup, paper_ids,
                                            matches, deep_analysis, effective_parallel)
        
    except Exception as e:
        logger.error(f"Tournament {tournament_id} failed: {e}")
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {"status": "failed", "current_log": f"Error: {str(e)}"}}
        )

async def run_ucb_tournament(tournament_id: str, papers: List[Dict], paper_lookup: Dict,
                             paper_ids: List[str], ucb_config: Dict, deep_analysis: bool,
                             parallel_agents: int):
    """Run tournament using UCB algorithm for efficient pair selection with top-k focus"""
    
    exploration_constant = ucb_config.get('exploration_constant', 1.414)
    min_comparisons = ucb_config.get('min_comparisons_per_paper', 3)
    convergence_threshold = ucb_config.get('convergence_threshold', 0.05)
    target_top_k = ucb_config.get('target_top_k')  # None means rank all
    confidence_level = ucb_config.get('confidence_level', 0.95)
    
    n = len(paper_ids)
    
    # Calculate max comparisons based on mode
    if target_top_k:
        # Top-k mode: need fewer comparisons, roughly k * log(n) * 4
        default_max = int(target_top_k * math.log(n) * 4 + n * 2)
    else:
        # Full ranking mode: n * log(n) * 3
        default_max = int(n * math.log(n) * 3)
    
    max_total = ucb_config.get('max_total_comparisons') or default_max
    
    # Initialize paper stats
    paper_stats = {pid: {'wins': 0, 'comparisons': 0, 'ucb_score': float('inf'), 'eliminated': False} for pid in paper_ids}
    compared_pairs = set()
    eliminated_papers = set()
    matches = []
    total_comparisons = 0
    previous_rankings = []
    
    mode_desc = f"Top-{target_top_k}" if target_top_k else "Full Ranking"
    logger.info(f"UCB Tournament ({mode_desc}): {n} papers, max {max_total} comparisons, c={exploration_constant}")
    
    while total_comparisons < max_total:
        # Check for papers that can be eliminated (only in top-k mode)
        if target_top_k and total_comparisons > n * 2:
            for pid in paper_ids:
                if pid not in eliminated_papers:
                    if not can_reach_top_k(pid, paper_stats, paper_ids, target_top_k, confidence_level):
                        eliminated_papers.add(pid)
                        paper_stats[pid]['eliminated'] = True
                        logger.info(f"UCB: Eliminated paper {pid[:8]}... (cannot reach top-{target_top_k})")
        
        # Select next pair(s) to compare
        batch_pairs = []
        for _ in range(parallel_agents):
            pair = select_ucb_pair(paper_ids, paper_stats, compared_pairs, total_comparisons, 
                                   exploration_constant, target_top_k, eliminated_papers)
            if pair:
                batch_pairs.append(pair)
                compared_pairs.add(tuple(sorted(pair)))
            else:
                break  # No more pairs to compare
        
        if not batch_pairs:
            logger.info("UCB: All relevant pairs compared or no valid pairs found")
            break
        
        # Run comparisons in parallel
        tasks = []
        for p1_id, p2_id in batch_pairs:
            p1 = paper_lookup[p1_id]
            p2 = paper_lookup[p2_id]
            tasks.append(compare_papers_llm(p1, p2, deep_analysis))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for (p1_id, p2_id), result in zip(batch_pairs, results):
            match = {
                'id': str(uuid.uuid4()),
                'paper1_id': p1_id,
                'paper2_id': p2_id,
                'completed': True,
                'round_num': total_comparisons // parallel_agents + 1
            }
            
            if isinstance(result, Exception):
                logger.error(f"UCB comparison failed: {result}")
                match['winner_id'] = p1_id
                match['reasoning'] = "Comparison failed"
            else:
                winner_key = result.get('winner', 'paper1')
                match['winner_id'] = p1_id if winner_key == 'paper1' else p2_id
                match['reasoning'] = result.get('reasoning', '')
            
            matches.append(match)
            
            # Update stats
            winner_id = match['winner_id']
            paper_stats[winner_id]['wins'] += 1
            paper_stats[p1_id]['comparisons'] += 1
            paper_stats[p2_id]['comparisons'] += 1
            total_comparisons += 1
        
        # Update UCB scores and confidence intervals
        for pid in paper_ids:
            stats = paper_stats[pid]
            ucb_score = calculate_ucb_scores(paper_stats, total_comparisons, exploration_constant).get(pid, 0)
            # Replace inf with large number for JSON serialization
            stats['ucb_score'] = 999999.0 if ucb_score == float('inf') else ucb_score
            # Update confidence interval
            ci = calculate_wilson_confidence_interval(stats['wins'], stats['comparisons'], confidence_level)
            stats['confidence'] = ci
        
        # Check convergence
        converged, previous_rankings = check_ucb_convergence(
            paper_stats, min_comparisons, convergence_threshold, previous_rankings, target_top_k
        )
        
        # Update progress
        progress = min(int((total_comparisons / max_total) * 100), 99)
        
        # Build status message
        if target_top_k:
            active_count = n - len(eliminated_papers)
            status_msg = f"UCB Top-{target_top_k}: {total_comparisons} comparisons, {active_count} active papers"
        else:
            status_msg = f"UCB: {total_comparisons} comparisons (exploring {'high uncertainty' if total_comparisons < n*2 else 'refinement'})"
        
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {
                "matches": matches,
                "paper_stats": paper_stats,
                "progress": progress,
                "current_log": status_msg
            }}
        )
        
        if converged and total_comparisons >= n * min_comparisons:
            logger.info(f"UCB: Converged after {total_comparisons} comparisons")
            break
        
        await asyncio.sleep(0.5 if deep_analysis else 0.3)
    
    # Calculate final rankings with confidence intervals
    scores = calculate_bradley_terry(matches, paper_ids)
    rankings = create_rankings(scores, paper_lookup, paper_stats, confidence_level)
    
    # Build completion message
    saved = (n*(n-1)//2) - len(matches)
    if target_top_k:
        completion_msg = f"UCB Top-{target_top_k} completed! {len(matches)} comparisons (saved {saved} vs round-robin)"
    else:
        completion_msg = f"UCB completed! {len(matches)} comparisons (saved {saved} vs round-robin)"
    
    await db.tournaments.update_one(
        {"id": tournament_id},
        {"$set": {
            "status": "completed",
            "matches": matches,
            "rankings": rankings,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "paper_stats": paper_stats,
            "progress": 100,
            "total_matches": len(matches),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "current_log": completion_msg
        }}
    )

async def run_round_robin_tournament(tournament_id: str, papers: List[Dict], paper_lookup: Dict,
                                     paper_ids: List[str], matches: List[Dict], deep_analysis: bool,
                                     parallel_agents: int):
    """Run traditional round-robin tournament"""
    pending_matches = [m for m in matches if not m.get('completed')]
    total = len(pending_matches)
    completed = 0
    
    for i in range(0, len(pending_matches), parallel_agents):
        batch = pending_matches[i:i + parallel_agents]
        
        # Run comparisons in parallel
        tasks = []
        for match in batch:
            p1 = paper_lookup[match['paper1_id']]
            p2 = paper_lookup[match['paper2_id']]
            tasks.append(compare_papers_llm(p1, p2, deep_analysis))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update matches with results
        for match, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error(f"Match comparison failed: {result}")
                match['completed'] = True
                match['winner_id'] = match['paper1_id']
                match['reasoning'] = "Comparison failed"
            else:
                winner_key = result.get('winner', 'paper1')
                match['winner_id'] = match['paper1_id'] if winner_key == 'paper1' else match['paper2_id']
                match['reasoning'] = result.get('reasoning', '')
                match['completed'] = True
            
            completed += 1
        
        # Update progress
        progress = int((completed / total) * 100) if total > 0 else 100
        mode_label = "Deep Analysis: " if deep_analysis else ""
        
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {
                "matches": matches,
                "progress": progress,
                "current_log": f"{mode_label}Completed {completed}/{total} comparisons..."
            }}
        )
        
        await asyncio.sleep(1.0 if deep_analysis else 0.5)
    
    # Calculate final rankings
    scores = calculate_bradley_terry(matches, paper_ids)
    rankings = create_rankings(scores, paper_lookup)
    
    # Clean papers (remove full_text)
    papers_clean = [{k: v for k, v in p.items() if k != 'full_text'} for p in papers]
    
    await db.tournaments.update_one(
        {"id": tournament_id},
        {"$set": {
            "status": "completed",
            "papers": papers_clean,
            "matches": matches,
            "rankings": rankings,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "progress": 100,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "current_log": f"Round Robin completed! {len(matches)} comparisons"
        }}
    )
    logger.info(f"Tournament {tournament_id} completed successfully")

# API Routes
@api_router.get("/")
async def root():
    return {"message": "ArXiv Paper Tournament API"}

@api_router.get("/categories")
async def get_categories():
    """Get all available arXiv categories"""
    return {"categories": [{"id": k, "name": v} for k, v in ARXIV_CATEGORIES.items()]}

@api_router.post("/papers/fetch")
async def fetch_papers(config: TournamentConfig):
    """Fetch papers from arXiv for a specific category"""
    if config.category not in ARXIV_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    try:
        papers = await fetch_arxiv_papers(config.category, config.num_papers)
        return {"papers": [p.model_dump() for p in papers]}
    except Exception as e:
        logger.error(f"Error fetching papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/papers/search")
async def search_papers(query: SearchQuery):
    """Search papers from arXiv with keywords, author, category, and date filters"""
    try:
        papers = await search_arxiv_papers(
            keywords=query.keywords,
            author=query.author,
            category=query.category,
            date_from=query.date_from,
            date_to=query.date_to,
            max_results=query.max_results
        )
        
        # Build search description
        search_parts = []
        if query.keywords:
            search_parts.append(f'keywords: "{query.keywords}"')
        if query.author:
            search_parts.append(f'author: "{query.author}"')
        if query.category:
            search_parts.append(f'category: {query.category}')
        if query.date_from:
            search_parts.append(f'from: {query.date_from}')
        if query.date_to:
            search_parts.append(f'to: {query.date_to}')
        search_description = ", ".join(search_parts) if search_parts else "all recent papers"
        
        return {
            "papers": [p.model_dump() for p in papers],
            "count": len(papers),
            "search_description": search_description
        }
    except Exception as e:
        logger.error(f"Error searching papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CitationRequest(BaseModel):
    arxiv_ids: List[str]

@api_router.post("/papers/citations")
async def get_citations(request: CitationRequest):
    """Fetch citation counts from Semantic Scholar for a list of arXiv IDs"""
    if not request.arxiv_ids:
        return {"citations": {}}
    
    # Semantic Scholar API - batch lookup by arXiv IDs
    arxiv_ids = [f"ARXIV:{aid.split('v')[0]}" for aid in request.arxiv_ids[:100]]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                params={"fields": "citationCount"},
                json={"ids": arxiv_ids},
                timeout=10.0
            )
            
            if response.status_code == 200:
                results = response.json()
                citations = {}
                for i, aid in enumerate(request.arxiv_ids[:100]):
                    if i < len(results) and results[i]:
                        citations[aid] = results[i].get('citationCount', 0)
                    else:
                        citations[aid] = None
                return {"citations": citations}
            else:
                logger.warning(f"Semantic Scholar API returned {response.status_code}")
                return {"citations": {}}
                
    except Exception as e:
        logger.warning(f"Failed to fetch citation counts: {e}")
        return {"citations": {}}

@api_router.post("/tournaments", response_model=Dict)
async def create_tournament(config: TournamentCreate, background_tasks: BackgroundTasks):
    """Create a new tournament - either from category or custom paper selection"""
    
    # If papers are provided directly (from search selection)
    if config.papers and len(config.papers) >= 2:
        paper_dicts = config.papers
        category = config.category or "custom"
        # Use search query as title if available, otherwise "Custom Selection"
        if config.search_query:
            category_name = config.search_query
        else:
            category_name = ARXIV_CATEGORIES.get(category, "Custom Selection")
    elif config.category:
        # Fetch papers from category
        if config.category not in ARXIV_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        
        try:
            papers = await fetch_arxiv_papers(config.category, config.num_papers)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch papers: {e}")
        
        if len(papers) < 2:
            raise HTTPException(status_code=400, detail="Not enough papers found for tournament")
        
        paper_dicts = [p.model_dump() for p in papers]
        category = config.category
        category_name = ARXIV_CATEGORIES[config.category]
    else:
        raise HTTPException(status_code=400, detail="Either category or papers must be provided")
    
    # Generate matches (only for round_robin, UCB generates dynamically)
    ranking_mode = config.ranking_mode or "round_robin"
    ucb_config_dict = None
    
    if ranking_mode == "ucb":
        matches = []  # UCB generates matches dynamically
        ucb_config_dict = config.ucb_config.model_dump() if config.ucb_config else {
            "exploration_constant": 1.414,
            "min_comparisons_per_paper": 3,
            "max_total_comparisons": None,
            "convergence_threshold": 0.05,
            "target_top_k": None,
            "confidence_level": 0.95
        }
        # Calculate estimated matches for UCB based on mode and confidence
        n = len(paper_dicts)
        target_k = ucb_config_dict.get('target_top_k')
        confidence_level = ucb_config_dict.get('confidence_level', 0.95)
        
        # Higher confidence requires more comparisons (scale factor)
        # 0.80 -> 1.0x, 0.95 -> 1.3x, 0.99 -> 1.6x
        confidence_multiplier = 1 + (confidence_level - 0.80) * 3
        
        if target_k:
            # Top-k mode: fewer comparisons needed
            base_estimate = target_k * math.log(n) * 4 + n * 2
        else:
            # Full ranking mode
            base_estimate = n * math.log(n) * 3
        
        estimated_matches = ucb_config_dict.get('max_total_comparisons') or int(base_estimate * confidence_multiplier)
    else:
        matches = generate_round_robin_matches(paper_dicts)
        estimated_matches = len(matches)
    
    match_dicts = [m.model_dump() for m in matches]
    
    # Create tournament
    tournament = Tournament(
        category=category,
        category_name=category_name,
        num_papers=len(paper_dicts),
        parallel_agents=config.parallel_agents,
        deep_analysis=config.deep_analysis,
        search_query=config.search_query,
        ranking_mode=ranking_mode,
        ucb_config=ucb_config_dict,
        papers=paper_dicts,
        matches=match_dicts,
        total_matches=estimated_matches
    )
    
    # Save to DB
    doc = tournament.model_dump()
    await db.tournaments.insert_one(doc)
    
    return {
        "tournament": {
            "id": tournament.id, 
            "status": tournament.status, 
            "total_matches": estimated_matches, 
            "num_papers": len(paper_dicts),
            "deep_analysis": config.deep_analysis,
            "ranking_mode": ranking_mode,
            "ucb_config": ucb_config_dict
        }
    }

@api_router.post("/tournaments/{tournament_id}/start")
async def start_tournament(tournament_id: str, background_tasks: BackgroundTasks):
    """Start a tournament"""
    tournament = await db.tournaments.find_one({"id": tournament_id}, {"_id": 0})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if tournament['status'] not in ['pending', 'failed']:
        raise HTTPException(status_code=400, detail=f"Tournament already {tournament['status']}")
    
    # Start tournament in background
    background_tasks.add_task(run_tournament, tournament_id)
    
    return {"message": "Tournament started", "tournament_id": tournament_id}

@api_router.get("/tournaments")
async def list_tournaments(limit: int = 20):
    """List all tournaments - lightweight"""
    tournaments = await db.tournaments.find(
        {},
        {"_id": 0, "id": 1, "category": 1, "category_name": 1, "status": 1, 
         "num_papers": 1, "total_matches": 1, "progress": 1, "created_at": 1, 
         "completed_at": 1, "deep_analysis": 1, "search_query": 1, "ranking_mode": 1}
    ).sort("created_at", -1).to_list(limit)
    return {"tournaments": tournaments}

@api_router.get("/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str, include_matches: bool = False):
    """Get tournament details - excludes matches by default for performance"""
    projection = {
        "_id": 0,
        "papers.abstract": 0,
        "papers.full_text": 0
    }
    
    if not include_matches:
        # Exclude matches for faster loading - use /matches endpoint for match details
        projection["matches"] = 0
    
    tournament = await db.tournaments.find_one({"id": tournament_id}, projection)
    
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"tournament": tournament}

@api_router.get("/tournaments/{tournament_id}/results")
async def get_tournament_results(tournament_id: str):
    """Get tournament results only - optimized for results page"""
    tournament = await db.tournaments.find_one(
        {"id": tournament_id}, 
        {
            "_id": 0,
            "id": 1,
            "category": 1,
            "category_name": 1,
            "status": 1,
            "num_papers": 1,
            "total_matches": 1,
            "deep_analysis": 1,
            "search_query": 1,
            "completed_at": 1,
            "rankings": 1,
            "scores": 1,
            "ranking_mode": 1,
            "ucb_config": 1,
            "paper_stats": 1,
            "papers.id": 1,
            "papers.title": 1,
            "papers.arxiv_id": 1,
            "papers.link": 1,
            "papers.citation_count": 1
            # Note: matches excluded for performance, fetched separately if needed
        }
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.get('status') != 'completed':
        raise HTTPException(status_code=400, detail="Tournament not completed yet")
    return {"tournament": tournament}

@api_router.get("/tournaments/{tournament_id}/matches")
async def get_tournament_matches(tournament_id: str, limit: int = 50, offset: int = 0):
    """Get tournament matches with pagination - for logs view"""
    tournament = await db.tournaments.find_one(
        {"id": tournament_id}, 
        {
            "_id": 0,
            "matches": 1,
            "papers.id": 1,
            "papers.title": 1,
            "papers.link": 1
        }
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    matches = tournament.get('matches', [])
    completed_matches = [m for m in matches if m.get('completed')]
    total = len(completed_matches)
    
    # Paginate
    paginated = completed_matches[offset:offset + limit]
    
    return {
        "matches": paginated,
        "papers": tournament.get('papers', []),
        "total": total,
        "offset": offset,
        "limit": limit
    }

@api_router.get("/tournaments/{tournament_id}/status")
async def get_tournament_status_simple(tournament_id: str):
    """Get lightweight tournament status for polling (no matches data)"""
    tournament = await db.tournaments.find_one(
        {"id": tournament_id},
        {
            "_id": 0,
            "id": 1,
            "status": 1,
            "progress": 1,
            "current_log": 1,
            "total_matches": 1,
            "ranking_mode": 1
        }
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Get match count without fetching all match data
    match_count = await db.tournaments.aggregate([
        {"$match": {"id": tournament_id}},
        {"$project": {"matchCount": {"$size": {"$ifNull": ["$matches", []]}}}}
    ]).to_list(1)
    tournament["completed_matches"] = match_count[0]["matchCount"] if match_count else 0
    
    return tournament

@api_router.get("/tournaments/{tournament_id}/status/stream")
async def tournament_status_sse(tournament_id: str):
    """Get tournament status as SSE stream"""
    async def event_generator():
        while True:
            tournament = await db.tournaments.find_one(
                {"id": tournament_id},
                {"_id": 0, "status": 1, "progress": 1, "current_log": 1, "rankings": 1}
            )
            if not tournament:
                yield f"data: {json.dumps({'error': 'Tournament not found'})}\n\n"
                break
            
            yield f"data: {json.dumps(tournament)}\n\n"
            
            if tournament['status'] in ['completed', 'failed']:
                break
            
            await asyncio.sleep(2)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@api_router.delete("/tournaments/{tournament_id}")
async def delete_tournament(tournament_id: str):
    """Delete a tournament"""
    result = await db.tournaments.delete_one({"id": tournament_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"message": "Tournament deleted"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_client():
    """Create indexes and resume stuck tournaments on startup"""
    try:
        # Create indexes
        await db.tournaments.create_index("id", unique=True)
        await db.tournaments.create_index("status")
        await db.tournaments.create_index("created_at")
        logger.info("MongoDB indexes created successfully")
        
        # Resume any stuck tournaments (status = "running" but no active task)
        stuck_tournaments = await db.tournaments.find(
            {"status": "running"},
            {"_id": 0, "id": 1, "category_name": 1, "progress": 1}
        ).to_list(100)
        
        if stuck_tournaments:
            logger.info(f"Found {len(stuck_tournaments)} stuck tournament(s), resuming...")
            for t in stuck_tournaments:
                logger.info(f"Resuming tournament {t['id'][:8]}... ({t['category_name']}) at {t.get('progress', 0)}%")
                # Import BackgroundTasks equivalent for startup
                asyncio.create_task(run_tournament(t['id']))
            logger.info("All stuck tournaments resumed")
    except Exception as e:
        logger.warning(f"Startup warning: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
