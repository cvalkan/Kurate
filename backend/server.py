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

class Tournament(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str
    category_name: str
    num_papers: int
    parallel_agents: int
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
    category: str
    num_papers: int = 10
    parallel_agents: int = 3

class CompareRequest(BaseModel):
    paper1: Dict[str, Any]
    paper2: Dict[str, Any]

# Store active tournaments for SSE
active_tournaments: Dict[str, Dict[str, Any]] = {}

# Helper Functions
async def fetch_arxiv_papers(category: str, max_results: int = 10) -> List[Paper]:
    """Fetch papers from arXiv API"""
    base_url = "http://export.arxiv.org/api/query"
    query = f"cat:{category}"
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(base_url, params=params, timeout=30.0)
        response.raise_for_status()
        
    # Parse XML response
    root = ET.fromstring(response.text)
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

async def compare_papers_llm(paper1: Dict, paper2: Dict) -> Dict:
    """Use LLM to compare two papers for scientific impact"""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"compare-{uuid.uuid4()}",
        system_message="""You are a scientific paper evaluator. Your task is to compare two papers and determine which has higher potential scientific impact.

Consider the following factors:
1. Novelty and innovation of the approach
2. Potential real-world applications
3. Methodological rigor (based on abstract)
4. Breadth of impact across fields
5. Timeliness and relevance

You MUST respond with valid JSON only, no other text. Format:
{"winner": "paper1" or "paper2", "reasoning": "Brief explanation (max 100 words)"}"""
    ).with_model("openai", "gpt-5.2")
    
    prompt = f"""Compare these two papers for scientific impact:

**Paper 1: {paper1['title']}**
Abstract: {paper1['abstract'][:800]}

**Paper 2: {paper2['title']}**
Abstract: {paper2['abstract'][:800]}

Which paper has higher estimated scientific impact? Respond with JSON only."""
    
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
        
        # Update status
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {"status": "running", "current_log": "Starting tournament..."}}
        )
        
        papers = tournament_doc['papers']
        matches = tournament_doc['matches']
        parallel_agents = tournament_doc.get('parallel_agents', 3)
        
        # Create paper lookup
        paper_lookup = {p['id']: p for p in papers}
        
        # Process matches in batches
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
                tasks.append(compare_papers_llm(p1, p2))
            
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
            log_msg = f"Completed {completed}/{total} comparisons..."
            
            # Update matches in DB
            await db.tournaments.update_one(
                {"id": tournament_id},
                {"$set": {
                    "matches": matches,
                    "progress": progress,
                    "current_log": log_msg
                }}
            )
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)
        
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
        
        # Update final state
        await db.tournaments.update_one(
            {"id": tournament_id},
            {"$set": {
                "status": "completed",
                "matches": matches,
                "rankings": rankings,
                "scores": {k: round(v, 4) for k, v in scores.items()},
                "progress": 100,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "current_log": "Tournament completed!"
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

@api_router.post("/tournaments", response_model=Dict)
async def create_tournament(config: TournamentCreate, background_tasks: BackgroundTasks):
    """Create a new tournament"""
    if config.category not in ARXIV_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    # Fetch papers
    try:
        papers = await fetch_arxiv_papers(config.category, config.num_papers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch papers: {e}")
    
    if len(papers) < 2:
        raise HTTPException(status_code=400, detail="Not enough papers found for tournament")
    
    # Generate matches
    paper_dicts = [p.model_dump() for p in papers]
    matches = generate_round_robin_matches(paper_dicts)
    match_dicts = [m.model_dump() for m in matches]
    
    # Create tournament
    tournament = Tournament(
        category=config.category,
        category_name=ARXIV_CATEGORIES[config.category],
        num_papers=len(papers),
        parallel_agents=config.parallel_agents,
        papers=paper_dicts,
        matches=match_dicts,
        total_matches=len(matches)
    )
    
    # Save to DB
    doc = tournament.model_dump()
    await db.tournaments.insert_one(doc)
    
    return {"tournament": {"id": tournament.id, "status": tournament.status, "total_matches": len(matches), "num_papers": len(papers)}}

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
    """List all tournaments"""
    tournaments = await db.tournaments.find(
        {},
        {"_id": 0, "id": 1, "category": 1, "category_name": 1, "status": 1, 
         "num_papers": 1, "total_matches": 1, "progress": 1, "created_at": 1, "completed_at": 1}
    ).sort("created_at", -1).to_list(limit)
    return {"tournaments": tournaments}

@api_router.get("/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str):
    """Get tournament details"""
    tournament = await db.tournaments.find_one({"id": tournament_id}, {"_id": 0})
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
