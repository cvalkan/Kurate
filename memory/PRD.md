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
- `/api/papers/search` - Search papers by keywords, author, category, date
- `/api/tournaments` - CRUD for tournaments
- `/api/tournaments/{id}/start` - Start tournament processing
- `/api/tournaments/{id}/results` - Get tournament results
- `/api/tournaments/{id}/matches` - Get detailed match logs (paginated)
- `/api/tournaments/{id}/status` - SSE endpoint for real-time updates

### Frontend (React + Shadcn/UI)
- **Home Page**: Category selection, tournament configuration
- **Search Page**: Advanced paper search, custom tournament creation, UCB configuration
- **Tournament Page**: Real-time progress, paper list, match logs with reasoning
- **Results Page**: Top 3 podium, complete Bradley-Terry rankings, comparison logs
- **History Page**: Past tournaments with delete functionality

### Key Technologies
- ArXiv API for paper fetching
- GPT 5.2 for pairwise comparison
- Bradley-Terry algorithm for scoring
- UCB (Upper Confidence Bound) algorithm for efficient ranking
- MongoDB for persistence
- Supports both Round-robin and UCB tournament modes

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
- [x] Deep Analysis mode (full PDF reading)
- [x] Advanced paper search (keywords, author, category, date)
- [x] UCB ranking mode for efficient comparisons

## What's Been Implemented

**Date: January 10, 2026 - Initial MVP**
- Complete MVP with all core features
- 22 arXiv categories supported
- GPT 5.2 integration via Emergent LLM key
- Round-robin tournament with parallel LLM calls
- Bradley-Terry score calculation
- Clean "Swiss Lab" themed UI
- Full CRUD for tournaments
- Real-time progress polling

**Date: January 10, 2026 - Deep Analysis Feature**
- Added "Deep Analysis" toggle mode
- Downloads full PDFs from arXiv and extracts text
- Extracts key sections: Introduction, Methodology, Results, Conclusion
- LLM receives full paper context instead of just abstracts
- More thorough comparison but slower (~10s per comparison vs ~3s)
- Limited to 10 papers max in deep mode
- UI shows estimated time, warnings, and mode badges

**Date: January 10, 2026 - Search & Custom Tournament Feature**
- Added Search page (/search) with advanced filters:
  - Keywords search (title & abstract)
  - Author search
  - Category filter (optional)
  - Date range filter (from/to)
  - Max results slider
- Paper selection with checkboxes from search results
- Tournament settings panel appears after selecting 2+ papers
- Custom tournaments track search query used
- History page shows search description for custom tournaments
- Exact phrase search support (wrap in quotes)

**Date: January 10, 2026 - Performance Optimizations**
- MongoDB indexing for fast queries
- Lazy-loading of match logs on Results page
- Lightweight API responses for lists (exclude heavy fields)
- Auto-resume tournaments interrupted by server restart

**Date: January 10, 2026 - UCB Bandit Feature ✅ COMPLETED**
- Added UCB (Upper Confidence Bound) as alternative ranking mode
- UCB Smart Ranking toggle in Tournament Settings
- Expandable UCB Parameters section with:
  - Exploration constant (c) - controls exploration vs exploitation
  - Min comparisons per paper
  - Max total comparisons (auto-calculated by default)
- UCB mode badges displayed on:
  - History page (purple "UCB" badge)
  - Tournament progress page (purple "UCB Mode" badge)
  - Results page (purple "UCB Mode" badge)
- **Efficiency**: UCB achieved 77.9% savings in comparisons (96 vs 435 for 30 papers)
- Backend supports both Round Robin and UCB tournament execution
- UCB convergence detection for early stopping

## Prioritized Backlog

### P0 (Critical) - All Completed ✅
- [x] ArXiv paper fetching
- [x] Tournament creation and execution
- [x] LLM comparison engine
- [x] Results display
- [x] UCB ranking mode

### P1 (High Priority)
- [ ] Date-based filtering in search (requested but not yet implemented)
- [ ] Export results to CSV/PDF
- [ ] Share tournament results via link

### P2 (Medium Priority)
- [ ] Pause button for long-running tournaments
- [ ] Paper abstract preview modal on hover
- [ ] Custom comparison criteria
- [ ] Multiple LLM provider support (user-selected)
- [ ] Tournament templates/presets

### P3 (Low Priority)
- [ ] User accounts for personalized history
- [ ] Scheduled/recurring tournaments
- [ ] Integration with reference managers
- [ ] Citation network visualization
- [ ] Save search queries as presets
- [ ] Pagination for very large match logs
- [ ] Highlight matched search phrase in results

## Next Action Items
1. Implement date-based filtering in search (user-requested)
2. Add pause button for tournaments
3. Add export functionality (CSV/JSON)
4. Implement share link for results

## Technical Notes

### UCB Algorithm Implementation
The UCB (Upper Confidence Bound) algorithm selects paper pairs intelligently:
- Papers with fewer comparisons have higher UCB scores (exploration)
- Papers with higher win rates also have higher UCB scores (exploitation)
- Formula: UCB = win_rate + c × √(ln(total_comparisons) / paper_comparisons)
- Convergence: Stops when top rankings stabilize and min comparisons reached
- Default config: c=1.414 (√2), min_comparisons=3 per paper

### Auto-Resume Feature
Server startup hook automatically resumes any tournaments with status='running'.
This prevents tournaments from getting stuck if the server restarts mid-execution.
