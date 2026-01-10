# PaperSumo - Product Requirements Document

## Original Problem Statement
Build a website/platform that fetches the latest scientific papers from arXiv (sorted by different topics) and runs a pairwise tournament on them to output a ranked list (based on Bradley-Terry scores) of scientific impact. Uses an LLM to determine which of two selected papers has higher estimated scientific impact or value. Can run multiple agents in parallel to speed up the process.

## Core Requirements
- Use GPT 5.2 with Emergent LLM Key
- Fetch papers from all arXiv categories
- Tournament settings configurable
- Results of tournaments preserved
- "Deep Analysis" mode that reads full papers (not just abstracts)
- Search for papers by keywords, authors, etc. for custom tournament sets
- Show LLM reasoning for each comparison in tournament logs
- UCB (Upper Confidence Bound) bandit mechanism for ranking efficiency
- Top-K focused ranking and confidence intervals
- Paper citation counts
- No 20-paper limit on tournaments
- Exact phrase searches work correctly

## Tech Stack
- **Frontend:** React, React Router, Axios, Tailwind CSS, Shadcn UI
- **Backend:** FastAPI, Pydantic, Motor, asyncio, PyPDF2, ThreadPoolExecutor
- **Database:** MongoDB
- **APIs:** ArXiv API, Semantic Scholar API, OpenAI GPT-5.2 (via Emergent LLM Key)
- **Algorithms:** Bradley-Terry, Upper Confidence Bound (UCB)

## Key Features Implemented

### ✅ Complete
1. **Paper Fetching** - From arXiv by category or advanced search
2. **Asynchronous Search** - Results display instantly, citations load in background
3. **Multiple Ranking Modes:**
   - Round Robin (standard all-pairs)
   - UCB Smart Ranking (bandit-based)
4. **Advanced UCB Configuration:**
   - Target Top-K focusing
   - Confidence Bands with intervals
5. **Deep Analysis Mode** - Downloads and analyzes full PDFs
6. **Live Tournament Tracking** - Real-time progress display
7. **Performance Optimizations:**
   - ThreadPoolExecutor for LLM calls (non-blocking)
   - In-memory cache for progress tracking
8. **Auto-resume** - Restarts interrupted tournaments
9. **Citation Counts** - From Semantic Scholar API

### 🟡 Upcoming (P1-P2)
1. ~~**Date-based filtering for search** (P1)~~ ✅ DONE (Jan 2026)
2. **Pause button for tournaments** (P2)
3. **Paper abstract preview on hover** (P2)

### 🔵 Future/Backlog
- Save search queries as presets
- Export results to CSV/PDF
- Share tournament results via public link
- Pagination for large match logs
- Highlight matched search phrases

## Database Schema

### tournaments collection
- `id`, `name`, `status`, `papers`, `matches`, `rankings`
- `deep_analysis`, `ranking_mode`, `ucb_config`

### In-Memory Cache
- `TOURNAMENT_PROGRESS_CACHE` - Tracks live progress without DB writes

## Key API Endpoints
- `POST /api/search/papers` - Search papers (non-blocking)
- `POST /api/papers/citations` - Fetch citation counts async
- `POST /api/tournaments` - Create tournament
- `GET /api/tournaments` - List all tournaments
- `GET /api/tournaments/{id}/status` - SSE for live progress
- `GET /api/tournaments/{id}/status-light` - Lightweight polling

## Architecture Notes
- `backend/server.py` is monolithic (1500+ lines) - needs refactoring
- Progress tracked in-memory to eliminate DB contention
- LLM calls run in ThreadPoolExecutor to prevent event loop blocking

## Deployment Status
- **Status:** READY
- **.gitignore fixed:** Removed env file exclusions
- All services operational

---
*Last Updated: January 2026*

## Changelog
- **Jan 10, 2026:** Fixed date filtering - now uses arXiv `submittedDate` query parameter
- **Jan 10, 2026:** Fixed progress bar reset issue - added in-memory cache merge and protected progress updates
