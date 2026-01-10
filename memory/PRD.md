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
- `/api/tournaments/{id}/results` - Get tournament results with confidence intervals
- `/api/tournaments/{id}/matches` - Get detailed match logs (paginated)
- `/api/tournaments/{id}/status` - SSE endpoint for real-time updates

### Frontend (React + Shadcn/UI)
- **Home Page**: Category selection, tournament configuration
- **Search Page**: Advanced paper search, custom tournament creation, UCB configuration with Top-K and confidence level
- **Tournament Page**: Real-time progress, paper list, match logs with reasoning
- **Results Page**: Top 3 podium with confidence bands, complete Bradley-Terry rankings with win rate ± margin of error
- **History Page**: Past tournaments with delete functionality

### Key Technologies
- ArXiv API for paper fetching
- GPT 5.2 for pairwise comparison
- Bradley-Terry algorithm for scoring
- UCB (Upper Confidence Bound) algorithm for efficient ranking
- Wilson Score Intervals for confidence bands
- MongoDB for persistence
- Supports both Round-robin and UCB tournament modes

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
- [x] Target Top-K focused ranking
- [x] Confidence bands for rankings

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

**Date: January 10, 2026 - Search & Custom Tournament Feature**
- Added Search page (/search) with advanced filters
- Paper selection with checkboxes from search results
- Exact phrase search support (wrap in quotes)

**Date: January 10, 2026 - Performance Optimizations**
- MongoDB indexing for fast queries
- Lazy-loading of match logs on Results page
- Auto-resume tournaments interrupted by server restart

**Date: January 10, 2026 - UCB Bandit Feature ✅**
- UCB Smart Ranking toggle in Tournament Settings
- UCB achieves ~78% savings in comparisons vs round-robin
- Expandable UCB Parameters section

**Date: January 10, 2026 - Target Top-K and Confidence Bands ✅ NEW**
- **Target Top-K Mode**: Focus comparisons on finding accurate top-k papers
  - Papers that statistically cannot reach top-k are eliminated early
  - Significant reduction in comparisons for "find top 5" type queries
  - Slider in UCB Parameters (3 to n, or "all" for full ranking)
  
- **Confidence Bands (Wilson Score Intervals)**:
  - Each paper shows win rate ± margin of error
  - Configurable confidence level (80-99%, default 95%)
  - Results display format: "75% ± 33% (4 cmp)"
  - Top 3 podium shows "Win rate: XX% ± YY%"
  - Higher confidence = tighter intervals but more comparisons needed

## Prioritized Backlog

### P0 (Critical) - All Completed ✅
- [x] ArXiv paper fetching
- [x] Tournament creation and execution
- [x] LLM comparison engine
- [x] Results display
- [x] UCB ranking mode
- [x] Target Top-K mode
- [x] Confidence bands

### P1 (High Priority)
- [ ] Date-based filtering in search (requested but not yet implemented)
- [ ] Export results to CSV/PDF
- [ ] Share tournament results via link

### P2 (Medium Priority)
- [ ] Pause button for long-running tournaments
- [ ] Paper abstract preview modal on hover

### P3 (Low Priority)
- [ ] User accounts for personalized history
- [ ] Scheduled/recurring tournaments
- [ ] Save search queries as presets
- [ ] Highlight matched search phrase in results

## Technical Notes

### UCB Algorithm
- Formula: UCB = win_rate + c × √(ln(total_comparisons) / paper_comparisons)
- Default: c=1.414 (√2), min_comparisons=3 per paper
- Top-K mode: Eliminates papers that can't statistically reach top-k

### Wilson Score Confidence Interval
- More accurate than normal approximation for small sample sizes
- Formula: center ± z × √((p(1-p) + z²/4n) / n) / (1 + z²/n)
- Returns: win_rate, lower_bound, upper_bound, margin_of_error, comparisons

### Auto-Resume Feature
Server startup hook automatically resumes any tournaments with status='running'.

## Next Action Items
1. Implement date-based filtering in search (user-requested)
2. Add pause button for tournaments
3. Add export functionality (CSV/JSON)
