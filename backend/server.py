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
    deep_analysis: bool = False  # New field for deep analysis mode

class SearchQuery(BaseModel):
    keywords: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    date_from: Optional[str] = None  # YYYY-MM-DD format
    date_to: Optional[str] = None    # YYYY-MM-DD format
    max_results: int = 20

class Tournament(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str
    category_name: str
    num_papers: int
    parallel_agents: int
    deep_analysis: bool = False  # Track if deep analysis is enabled
    search_query: Optional[str] = None  # Store the search query used
    status: str = "pending"  # pending, running, completed, failed
    papers: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    rankings: List[Dict[str, Any]] = []
    scores: Dict[str, float] = {}
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
    paper_ids: Optional[List[str]] = None  # Selected paper IDs from search
    papers: Optional[List[Dict[str, Any]]] = None  # Full paper objects from search
    search_query: Optional[str] = None  # Description of search used

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
    """Search papers from arXiv API with multiple filters"""
    base_url = "https://export.arxiv.org/api/query"
    
    # Build query parts
    query_parts = []
    
    if keywords:
        keywords_clean = keywords.strip()
        # Check if user wants exact phrase (wrapped in quotes)
        if keywords_clean.startswith('"') and keywords_clean.endswith('"'):
            # Exact phrase search - remove outer quotes, arXiv uses quotes internally
            phrase = keywords_clean[1:-1]
            # For exact phrase, search with AND between words
            words = phrase.split()
            if len(words) > 1:
                # Multi-word phrase: use all: field with AND
                word_queries = [f'all:{word}' for word in words]
                query_parts.append(f'({" AND ".join(word_queries)})')
            else:
                query_parts.append(f'all:{phrase}')
        else:
            # Regular search - search in title and abstract with OR between words
            words = keywords_clean.split()
            if len(words) > 1:
                # Multiple words: OR them together for broader results
                word_queries = []
                for word in words:
                    word_queries.append(f'(ti:{word} OR abs:{word})')
                query_parts.append(f'({" AND ".join(word_queries)})')
            else:
                query_parts.append(f'(ti:{keywords_clean} OR abs:{keywords_clean})')
    
    if author:
        author_clean = author.strip()
        # Handle author names - arXiv uses lastname_firstname format
        query_parts.append(f'au:{author_clean}')
    
    if category:
        query_parts.append(f'cat:{category}')
    
    # Combine query parts with AND
    if query_parts:
        query = " AND ".join(query_parts)
    else:
        query = "all:*"  # Default: fetch recent papers
    
    logger.info(f"ArXiv search query: {query}")
    
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",  # Use relevance for keyword searches
        "sortOrder": "descending"
    }
    
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(base_url, params=params, timeout=30.0)
        response.raise_for_status()
    
    papers = parse_arxiv_response(response.text)
    
    # Filter by date if specified (arXiv API doesn't support date filtering directly)
    if date_from or date_to:
        filtered_papers = []
        for paper in papers:
            pub_date = paper.published[:10]  # Get YYYY-MM-DD
            if date_from and pub_date < date_from:
                continue
            if date_to and pub_date > date_to:
                continue
            filtered_papers.append(paper)
        papers = filtered_papers
    
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

async def run_tournament(tournament_id: str):
    """Run the tournament with parallel LLM comparisons"""
    try:
        # Get tournament from DB
        tournament_doc = await db.tournaments.find_one({"id": tournament_id}, {"_id": 0})
        if not tournament_doc:
            logger.error(f"Tournament {tournament_id} not found")
            return
        
        deep_analysis = tournament_doc.get('deep_analysis', False)
        
        # Update status
        if deep_analysis:
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"status": "running", "current_log": "Deep Analysis Mode: Downloading papers..."}}
            )
        else:
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"status": "running", "current_log": "Starting tournament..."}}
            )
        
        papers = tournament_doc['papers']
        matches = tournament_doc['matches']
        parallel_agents = tournament_doc.get('parallel_agents', 3)
        
        # If deep analysis, download PDFs first
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
                        logger.info(f"Downloaded PDF for {paper['arxiv_id']}: {len(full_text)} chars")
                    else:
                        logger.warning(f"Failed to download PDF for {paper['arxiv_id']}")
                    
                    # Small delay between downloads
                    await asyncio.sleep(0.5)
            
            # Update papers with full text in DB
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {"papers": papers, "current_log": "PDFs downloaded. Starting comparisons..."}}
            )
        
        # Create paper lookup
        paper_lookup = {p['id']: p for p in papers}
        
        # Process matches in batches
        pending_matches = [m for m in matches if not m.get('completed')]
        total = len(pending_matches)
        completed = 0
        
        # Use fewer parallel agents for deep analysis (more tokens per request)
        effective_parallel = min(parallel_agents, 2) if deep_analysis else parallel_agents
        
        for i in range(0, len(pending_matches), effective_parallel):
            batch = pending_matches[i:i + effective_parallel]
            
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
                    match['winner_id'] = match['paper1_id']  # Default
                    match['reasoning'] = "Comparison failed"
                else:
                    winner_key = result.get('winner', 'paper1')
                    match['winner_id'] = match['paper1_id'] if winner_key == 'paper1' else match['paper2_id']
                    match['reasoning'] = result.get('reasoning', '')
                    match['completed'] = True
                
                completed += 1
            
            # Update progress in DB
            progress = int((completed / total) * 100) if total > 0 else 100
            mode_label = "Deep Analysis: " if deep_analysis else ""
            log_msg = f"{mode_label}Completed {completed}/{total} comparisons..."
            
            # Update matches in DB
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {
                    "matches": matches,
                    "progress": progress,
                    "current_log": log_msg
                }}
            )
            
            # Delay between batches (longer for deep analysis to avoid rate limits)
            await asyncio.sleep(1.0 if deep_analysis else 0.5)
        
        # Calculate final rankings using Bradley-Terry
        paper_ids = [p['id'] for p in papers]
        scores = calculate_bradley_terry(matches, paper_ids)
        
        # Create rankings
        rankings = []
        for pid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            paper = paper_lookup[pid]
            rankings.append({
                "rank": len(rankings) + 1,
                "paper_id": pid,
                "title": paper['title'],
                "authors": paper['authors'],
                "arxiv_id": paper['arxiv_id'],
                "link": paper['link'],
                "score": round(score, 4)
            })
        
        # Update final state (remove full_text from papers to save space)
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
                "current_log": f"Tournament completed! {'(Deep Analysis)' if deep_analysis else ''}"
            }}
        )
        
        logger.info(f"Tournament {tournament_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Tournament {tournament_id} failed: {e}")
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {
                "status": "failed",
                "current_log": f"Error: {str(e)}"
            }}
        )

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

@api_router.post("/tournaments", response_model=Dict)
async def create_tournament(config: TournamentCreate, background_tasks: BackgroundTasks):
    """Create a new tournament - either from category or custom paper selection"""
    
    # If papers are provided directly (from search selection)
    if config.papers and len(config.papers) >= 2:
        paper_dicts = config.papers
        category = config.category or "custom"
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
    
    # Generate matches
    matches = generate_round_robin_matches(paper_dicts)
    match_dicts = [m.model_dump() for m in matches]
    
    # Create tournament
    tournament = Tournament(
        category=category,
        category_name=category_name,
        num_papers=len(paper_dicts),
        parallel_agents=config.parallel_agents,
        deep_analysis=config.deep_analysis,
        search_query=config.search_query,
        papers=paper_dicts,
        matches=match_dicts,
        total_matches=len(matches)
    )
    
    # Save to DB
    doc = tournament.model_dump()
    await db.tournaments.insert_one(doc)
    
    return {
        "tournament": {
            "id": tournament.id, 
            "status": tournament.status, 
            "total_matches": len(matches), 
            "num_papers": len(paper_dicts),
            "deep_analysis": config.deep_analysis
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
         "completed_at": 1, "deep_analysis": 1, "search_query": 1}
    ).sort("created_at", -1).to_list(limit)
    return {"tournaments": tournaments}

@api_router.get("/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str, full: bool = False):
    """Get tournament details - lightweight by default, full with ?full=true"""
    if full:
        # Full data including all papers and matches
        tournament = await db.tournaments.find_one({"id": tournament_id}, {"_id": 0})
    else:
        # Lightweight - exclude heavy fields but keep reasoning for display
        tournament = await db.tournaments.find_one(
            {"id": tournament_id}, 
            {
                "_id": 0,
                "papers.abstract": 0,
                "papers.full_text": 0
            }
        )
    
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
            "matches": 1,
            "papers.id": 1,
            "papers.title": 1,
            "papers.arxiv_id": 1,
            "papers.link": 1
        }
    )
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.get('status') != 'completed':
        raise HTTPException(status_code=400, detail="Tournament not completed yet")
    return {"tournament": tournament}

@api_router.get("/tournaments/{tournament_id}/status")
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
