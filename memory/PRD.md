# PaperSumo - ArXiv Paper Tournament Platform

## Original Problem Statement
Build a website/platform that fetches the latest scientific papers from arxiv (sorted by different topic) and then runs a pairwise tournament on them to output a ranked list (e.g. based on Bradley-Terry scores) of scientific impact. Uses an LLM (selected by the user) to determine which of the two selected papers has the higher estimated scientific impact or value. It can run multiple agents in parallel to speed up the process.

## User Choices
- **LLM**: GPT 5.2 with Emergent LLM key
- **Categories**: All arXiv categories (22 categories)
- **Configuration**: Configurable number of papers and parallel agents
- **Authentication**: None required
- **Data Persistence**: Results preserved in MongoDB

## Architecture

### Backend (FastAPI)
- `/api/categories` - List all arXiv categories
- `/api/papers/fetch` - Fetch papers from arXiv API
- `/api/tournaments` - CRUD for tournaments
- `/api/tournaments/{id}/start` - Start tournament processing
- `/api/tournaments/{id}/status` - SSE endpoint for real-time updates

### Frontend (React + Shadcn/UI)
- **Home Page**: Category selection, tournament configuration
- **Tournament Page**: Real-time progress, paper list, match logs
- **Results Page**: Top 3 podium, complete Bradley-Terry rankings
- **History Page**: Past tournaments with delete functionality

### Key Technologies
- ArXiv API for paper fetching
- GPT 5.2 for pairwise comparison
- Bradley-Terry algorithm for scoring
- MongoDB for persistence
- Round-robin tournament structure

## User Personas
1. **Researchers**: Want to quickly identify high-impact papers in their field
2. **Academics**: Looking for literature review assistance
3. **Students**: Discovering influential papers for study

## Core Requirements (Static)
- [x] Fetch papers from arXiv by category
- [x] LLM-based pairwise comparison
- [x] Bradley-Terry scoring algorithm
- [x] Parallel processing support
- [x] Configurable tournament settings
- [x] Results persistence
- [x] Real-time progress updates

## What's Been Implemented
**Date: January 10, 2026**
- Complete MVP with all core features
- 22 arXiv categories supported
- GPT 5.2 integration via Emergent LLM key
- Round-robin tournament with parallel LLM calls
- Bradley-Terry score calculation
- Clean "Swiss Lab" themed UI
- Full CRUD for tournaments
- Real-time progress polling

## Prioritized Backlog

### P0 (Critical) - Completed
- [x] ArXiv paper fetching
- [x] Tournament creation and execution
- [x] LLM comparison engine
- [x] Results display

### P1 (High Priority)
- [ ] Export results to CSV/PDF
- [ ] Share tournament results via link
- [ ] Advanced filtering (date range, keyword search)

### P2 (Medium Priority)
- [ ] Custom comparison criteria
- [ ] Multiple LLM provider support (user-selected)
- [ ] Tournament templates/presets
- [ ] Paper abstract preview modal

### P3 (Low Priority)
- [ ] User accounts for personalized history
- [ ] Scheduled/recurring tournaments
- [ ] Integration with reference managers
- [ ] Citation network visualization

## Next Action Items
1. Add export functionality (CSV/JSON)
2. Implement share link for results
3. Add date range filter for papers
4. Consider adding paper abstract tooltips
