# First-Pass Code Review: PaperSumo (Kurate.org)

**Reviewer**: Claude Code (Automated)
**Date**: 2026-04-01
**Scope**: Full codebase first-pass to identify focus areas for deeper second-pass review

**Project**: AI-powered scientific paper ranking platform using LLM pairwise comparisons with TrueSkill-style ratings. FastAPI backend + React 19 frontend + MongoDB, deployed on Emergent Agent platform.

---

## 1. SECURITY (High Priority for Deep Dive)

### 1a. Default Admin Password Hardcoded
- `backend/core/config.py:128` -- `ADMIN_PASSWORD` defaults to `"papersumo2025"` if env var is unset
- `backend/core/auth.py:44-48` -- Legacy path still accepts raw password as admin token (not just session tokens), meaning anyone who knows the default password can authenticate as admin
- **Risk**: If the env var is ever unset in a deployment, the app is wide open

### 1b. MongoDB Regex Injection via User Input
- `backend/routers/leaderboard.py:792-793` -- User-supplied `search` query param is passed directly into `$regex` without escaping special regex characters
- `backend/routers/claims.py:213` -- Same pattern with `arxiv_id`
- `backend/routers/admin.py:2130` -- Same with `label` parameter
- **Risk**: ReDoS (Regular Expression Denial of Service) or unexpected query behavior. A crafted input like `.*.*.*.*.*.*.*` could cause catastrophic backtracking in MongoDB's regex engine.

### 1c. CORS Wildcard with Credentials
- `backend/server.py:146-153` -- If `CORS_ORIGINS="*"`, all origins are allowed with `allow_credentials=True`, which is a dangerous combination (allows credential theft from any domain)
- Default value is properly scoped to `kurate.org` domains, but the wildcard fallback path exists

### 1d. XSS via `dangerouslySetInnerHTML`
- `frontend/src/pages/PaperPage.jsx:85,159,164,179` -- Renders markdown-style bold + LaTeX via innerHTML. Content comes from LLM-generated summaries stored in DB.
- `frontend/src/pages/ICLRDeepDiveSection.jsx:345` -- Same pattern
- `frontend/src/pages/DeeperDiveSection.jsx:540` -- Same pattern
- **Risk**: Stored XSS if an LLM response contains `<script>` tags or event handlers. The regex-based markdown conversion (`**text**` to `<strong>`) does not sanitize HTML. No DOMPurify or similar library is used.

### 1e. Session Tokens in localStorage
- `frontend/src/contexts/AuthContext.jsx:12-56` -- Session tokens stored in `localStorage`, which is accessible to any JavaScript on the page
- Combined with the XSS vectors above, this means a successful XSS attack could steal session tokens
- The backend *also* sets httpOnly cookies (`routers/auth.py:90-98`), creating a dual-auth mechanism with different security properties

### 1f. Rate Limiter Weaknesses
- `backend/server.py:37-122` -- Rate limits are per-process in-memory (reset on restart, not shared across workers)
- Admin endpoints are entirely exempt from rate limiting (line 103)
- `X-Forwarded-For` header can be spoofed to bypass per-IP limits
- `_rate_buckets` dict grows unbounded until > 5000 entries, with only best-effort cleanup

### 1g. Admin Token in sessionStorage (Frontend)
- `frontend/src/pages/AdminLoginPage.jsx:29` -- Admin token stored in `sessionStorage`
- Duplicated `getAdminHeaders()` function in 6+ admin component files reads from sessionStorage
- No token expiration or rotation on the frontend side

---

## 2. ARCHITECTURE (Medium-High Priority)

### 2a. Monolithic Router Files
The largest backend files mix routing, business logic, and data access:
| File | Lines | Concern |
|------|-------|---------|
| `routers/validation.py` | 4,956 | Validation tournament logic |
| `routers/validation_experiments.py` | 3,412 | Experiment management |
| `routers/leaderboard.py` | 3,078 | Leaderboard queries + ranking |
| `routers/human_ai_benchmark.py` | 2,919 | Benchmark comparisons |
| `routers/admin.py` | 2,790 | Admin CRUD + category management |
| `services/scheduler.py` | 1,518 | Background task orchestration |

These files are difficult to test, review, and maintain. Business logic should be separated from HTTP routing.

### 2b. Global Mutable State Everywhere
In-memory caches and state scattered across modules with no centralized management:
- `server.py`: `_rate_buckets`
- `admin.py`: `_admin_cache`, `_fetch_tasks`
- `validation.py`: `_tournament_states`, `_tournament_tasks`, `_datasets_cache`
- `leaderboard.py`: `_cache`
- `core/auth.py`: `_settings_cache`
- `scheduler.py`: `_category_status`, `_summary_gen_progress`, `_processing_locks`
- `validation_utils.py`: `consistency_cache`, `cycle_all_cache`, `convergence_all_cache`, `_result_cache`

Each module implements its own TTL/eviction logic. All state is process-local, which would break with multi-worker deployment.

### 2c. Tight Coupling Between Routers
- `admin.py` imports `routers.leaderboard._cache` to access internal cache state directly
- `server.py` imports from `routers.congrats` for OAuth flow construction
- `core/auth.py` imports from `routers.admin._is_valid_session` (circular dependency)
- `validation.py` imports heavily from `validation_utils.py` with complex interdependencies

### 2d. No Centralized API Client (Frontend)
- 62+ files make raw `axios` calls with `process.env.REACT_APP_BACKEND_URL` concatenated inline
- No request/response interceptors, no retry logic, inconsistent error handling
- Some errors silently caught (`.catch(() => {})`), others show toast notifications
- Auth headers managed differently across components

### 2e. Large Frontend Components
Several page components are excessively large:
- `ValidationPage.jsx` -- ~57KB
- `HumanAIBenchmarkSection.jsx` -- ~49KB
- `AdminPage.jsx` -- ~41KB
- `SummaryBiasSection.jsx` -- ~37KB

These should be decomposed into focused sub-components.

---

## 3. RELIABILITY & ERROR HANDLING (Medium Priority)

### 3a. Broad Exception Swallowing
- Multiple `except Exception as e: logger.warning(...)` patterns that silently continue execution
- `server.py:232,242,255,265` -- Startup failures logged as warnings but execution continues, potentially running in a degraded state without alerting

### 3b. Blocking Operations in Async Event Loop
- `services/llm.py:46` -- PDF parsing runs in the default thread pool executor (not the dedicated `_llm_executor`), which can starve other async tasks
- `server.py:226` -- `subprocess.run()` with `timeout=5` blocks the event loop during startup

### 3c. No Database Transaction Safety
- MongoDB operations across collections (e.g., creating a match + updating paper stats) are not atomic
- Server crash mid-operation could leave inconsistent state
- No use of MongoDB transactions despite using replica sets (Motor supports them)

### 3d. No React Error Boundaries (Frontend)
- No Error Boundary components found anywhere in the frontend
- A crash in any component takes down the entire page with no recovery

### 3e. Polling Without Backoff
- Frontend components poll backend endpoints (e.g., prewarm-status, tournament progress) using `setInterval`
- No exponential backoff on failure, no coordination between multiple polling components

---

## 4. CODE QUALITY (Medium Priority)

### 4a. Duplicated .gitignore Entries
- `.gitignore` (247 lines) has heavily duplicated env file patterns (lines 84-246), suggesting repeated manual edits without cleanup

### 4b. Dead/Unused Code
- The project has its own `tools/dead_code_audit.py` -- worth running to see findings
- 52 shadcn/ui component files in `frontend/src/components/ui/` -- many likely unused (auto-generated by shadcn init)
- Should audit which UI components are actually imported

### 4c. Test Infrastructure Gaps
- Tests are integration/API tests using `requests` against a running server, not unit tests
- No mocking of external services (LLM API calls, arXiv API, email service, etc.)
- Test files split between project root (`backend_test.py`, `regression_test.py`) and `backend/tests/` (39 files, 10K+ lines)
- No CI/CD pipeline detected -- unclear if tests run automatically
- Zero frontend tests -- no `.test.jsx` or `.spec.js` files found

### 4d. Import Anti-patterns
- Imports inside function bodies: `validation.py:67` (`import time as _t`), `server.py:219` (`import subprocess`), `server.py:269` (`from core.memlog import`)
- Circular import workarounds (e.g., `core/auth.py` importing from `routers/admin.py`)

### 4e. Duplicated Utility Functions (Frontend)
- `getAdminHeaders()` reimplemented identically in 6+ admin component files
- API URL construction duplicated in every component that makes API calls

### 4f. Console Logging in Production
- 49+ `console.log/error/warn` calls scattered throughout frontend code
- No production log filtering or external error tracking (Sentry, etc.)

---

## 5. PERFORMANCE (Lower Priority)

### 5a. Precomputation Architecture
- Heavy reliance on precomputed JSON caches loaded at startup (`backend/STATIC_VALIDATION.md` documents this)
- Validation endpoints are cache-only and return stale/empty data if caches aren't warmed
- Deliberate design choice but creates deployment complexity and cold-start delays

### 5b. Unbounded In-Memory Growth
- `_rate_buckets` only cleaned when size > 5000 entries (best-effort)
- Various cache dicts have max-entry limits but not max-memory limits
- No monitoring of memory consumption by caches

### 5c. Frontend Re-render Optimization
- Out of 572 React hooks, only 68 are performance optimizations (`useMemo`/`useCallback`)
- Large data arrays potentially re-created on every render in validation/benchmark pages

---

## Recommended Focus Areas for Second-Pass Deep Dive

| Priority | Area | Key Files | Rationale |
|----------|------|-----------|-----------|
| **P0** | Regex injection / ReDoS | `leaderboard.py:790+`, `claims.py:210+`, `admin.py:2130` | User input flows directly into MongoDB `$regex` |
| **P0** | XSS via innerHTML | `PaperPage.jsx:81-85`, `DeeperDiveSection.jsx:540`, `ICLRDeepDiveSection.jsx:345` | LLM output rendered as raw HTML without sanitization |
| **P0** | Admin auth hardening | `core/auth.py:37-49`, `core/config.py:128`, `admin.py:108-115` | Default password + legacy raw-password auth path |
| **P1** | CORS configuration | `server.py:146-156` | Wildcard + credentials combination |
| **P1** | Auth flow completeness | `routers/auth.py` full file | Session management, token expiry, ORCID/Google OAuth flows |
| **P1** | LLM service reliability | `services/llm.py` full file (1,007 lines) | Error handling, token limits, retry logic, PDF parsing |
| **P1** | Token storage security | `AuthContext.jsx`, `AdminLoginPage.jsx` | localStorage/sessionStorage vs httpOnly cookies |
| **P2** | Scheduler reliability | `services/scheduler.py` (1,518 lines) | Background task lifecycle, failure recovery, lock management |
| **P2** | State management audit | All `_cache` / `_state` globals across routers | Process-local state, cache invalidation correctness |
| **P2** | Frontend API layer | All component files making `axios` calls | Centralize error handling, auth headers, retries |
| **P3** | Dead code removal | Run `tools/dead_code_audit.py`, audit shadcn components | Reduce maintenance surface |
| **P3** | Test coverage gaps | `backend/tests/`, root test files | Missing unit tests, no frontend tests, no CI |
