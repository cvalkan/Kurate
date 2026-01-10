# PaperSumo - ArXiv Paper Tournament Platform

## Original Problem Statement
Build a website/platform that fetches the latest scientific papers from arxiv (sorted by different topic) and then runs a pairwise tournament on them to output a ranked list (e.g. based on Bradley-Terry scores) of scientific impact.

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
- `/api/papers/search` - Search papers by keywords, author, category, date (returns citation counts)
- `/api/tournaments` - CRUD for tournaments
- `/api/tournaments/{id}/start` - Start tournament processing
- `/api/tournaments/{id}/results` - Get tournament results with confidence intervals
- `/api/tournaments/{id}/matches` - Get detailed match logs (paginated)

### Frontend (React + Shadcn/UI)
- **Home Page**: Category selection, tournament configuration
- **Search Page**: Advanced paper search with citations, UCB configuration with Top-K and confidence level
- **Tournament Page**: Real-time progress, paper list with citations, match logs with reasoning
- **Results Page**: Top 3 podium with confidence bands and citations, complete rankings
- **History Page**: Past tournaments (title shows search keywords)

### Key Technologies
- ArXiv API for paper fetching
- Semantic Scholar API for citation counts
- GPT 5.2 for pairwise comparison
- Bradley-Terry algorithm for scoring
- UCB (Upper Confidence Bound) algorithm for efficient ranking
- Wilson Score Intervals for confidence bands
- MongoDB for persistence

## What's Been Implemented

**January 10, 2026 - Keywords as Title, Citation Counts, Confidence Estimates ✅ NEW**
- **Keywords as Tournament Title**: Search keywords now display as the tournament title instead of "Custom Selection"
  - History page shows "blockchain prediction markets" instead of "Custom Selection (Search: ...)"
  - Results page shows clean title without redundant search info
- **Citation Counts** (Semantic Scholar integration):
  - Search results show citation counts (amber badge: "55 citations")
  - Tournament page paper list shows citation badges
  - Results page rankings show citation counts next to authors
  - Top 3 podium shows citations
- **Confidence Level Affects Estimates**:
  - Formula: multiplier = 1 + (confidence_level - 0.80) * 3
  - 80% confidence = 1.0x estimated comparisons
  - 95% confidence = 1.45x estimated comparisons  
  - 99% confidence = 1.57x estimated comparisons
  - UI dynamically updates estimates when confidence slider changes

**January 10, 2026 - Target Top-K and Confidence Bands ✅**
- Target Top-K mode for efficient ranking
- Wilson Score confidence intervals for rankings

**January 10, 2026 - UCB Bandit Feature ✅**
- UCB Smart Ranking toggle (77% comparison savings)
- Expandable UCB Parameters section

**January 10, 2026 - Earlier Features ✅**
- Complete MVP with all core features
- Deep Analysis mode (full PDF reading)
- Advanced paper search (keywords, author, category, date)
- Performance optimizations (MongoDB indexing, lazy loading)
- Auto-resume interrupted tournaments

## Prioritized Backlog

### P0 (Critical) - All Completed ✅
- [x] ArXiv paper fetching
- [x] Tournament creation and execution
- [x] LLM comparison engine
- [x] Results display with confidence bands
- [x] UCB ranking mode
- [x] Target Top-K mode
- [x] Citation counts
- [x] Keywords as title

### P1 (High Priority)
- [ ] Date-based filtering in search (user requested)
- [ ] Export results to CSV/PDF
- [ ] Share tournament results via link

### P2 (Medium Priority)
- [ ] Pause button for long-running tournaments
- [ ] Paper abstract preview modal on hover

### P3 (Low Priority)
- [ ] User accounts for personalized history
- [ ] Save search queries as presets
- [ ] Highlight matched search phrase in results

## Technical Notes

### Citation Counts (Semantic Scholar)
- Batch API: `POST /graph/v1/paper/batch` with arXiv IDs
- Returns citationCount for papers in their database
- Some papers may return null (not indexed)
- Rate limited - fetches up to 100 papers per request

### Confidence Level Formula
Higher confidence requires more comparisons:
- multiplier = 1 + (confidence_level - 0.80) * 3
- Applied to base UCB estimate: n × log(n) × 3 × multiplier

## Next Action Items
1. Implement date-based filtering in search
2. Add pause button for tournaments
3. Add export functionality (CSV/JSON)
