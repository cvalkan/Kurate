# PaperSumo - Product Requirements Document

## Overview
PaperSumo is a web platform for ranking academic papers using pairwise comparison models.

## Implemented Features

### Validation Page (`/validation`) — Ranking Correlation
- 3 datasets: ICLR LLMs (ρ=0.65), ICLR Protein (ρ=0.60), PeerRead ACL (ρ=0.41)
- Multi-model analysis (GPT-5.2, Claude Opus, Gemini 3 Pro)
- Sidebar navigation, per-dataset tabs

### Pairwise Expert Comparison (`/pairwise`) — NEW
- Unbiased head-to-head: 1 pair per reviewer, no ties
- Fetches from Qeios via Crossref API + Qeios page scraping
- Full body text extraction, categorized by domain
- AI runs exact same pairs as human reviewers
- Results: agreement by domain, by model, by score gap, full text vs abstract
- Current: 50 pairs, 52% overall agreement. Social Sciences 81%, Physical Sciences 21%

### Key Endpoints
- `POST /api/pairwise/fetch-pairs` — fetch N reviewer pairs from Qeios
- `POST /api/pairwise/run-tournament` — run AI on pending pairs
- `POST /api/pairwise/stop-tournament` — stop running tournament
- `GET /api/pairwise/status` — pair counts, domains, progress
- `GET /api/pairwise/results` — agreement by domain/model/gap

## Backlog
- Fetch more pairwise pairs (100-200) for statistical power
- Add more data sources (F1000, Crossref/Copernicus) to pairwise system
- HTTP security headers for production
- Update production seed data
