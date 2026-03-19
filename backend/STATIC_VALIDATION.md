# STATIC VALIDATION ENDPOINTS — DO NOT MAKE DYNAMIC

## Rule
ALL validation endpoints (`/api/validation/*`) MUST serve data from precomputed caches ONLY.
They MUST NEVER compute results on-demand from the database during a user request.

## Why
On-demand computation of validation metrics takes 10-60 seconds per dataset, blocks the
asyncio event loop, and causes the entire production site to become unresponsive.

## How it works
1. **Precomputed JSON files** (`data/precomputed/experiment_results.json`, `validation_results.json`)
   are loaded at startup BEFORE the server accepts connections.
2. **MongoDB persistent cache** (`computation_cache` collection) stores results that survive restarts.
3. **Background prewarm tasks** compute any missing data after startup (never on the request path).
4. If data is not cached, endpoints return `{"status": "no_data"}` — never compute.

## To update validation data
- Run experiments on the **preview** environment
- Use the admin `precompute-experiments` endpoint to regenerate the JSON files
- Deploy — the new JSON files will be loaded at startup

## Endpoints covered by this rule (CACHE-ONLY, never compute on-demand)
- `/api/validation/convergence-all` (10-60s per dataset — the main offender)
- `/api/validation/consistency-analysis` (52s cold)
- `/api/validation/cycle-analysis-all` (9s cold)
- `/api/validation/summarizer-ab/results` (36s cold)
- `/api/validation/judge-comparison/results` (10s cold)
- `/api/validation/single-item-scoring/results`
- `/api/validation/human-ai-benchmark`
- `/api/validation/unified-benchmark`
- `/api/validation/extended-thinking/results`
- `/api/validation/multi-aspect/results`
- `/api/validation/model-correlation-analysis/results`
- `/api/validation/institution-bias/results`
- `/api/validation/institution-bias-samepair/results`
- `/api/validation/assessor-evaluator/results`

## Endpoints that MAY compute on-demand (lightweight, per-dataset)
These are fast enough (<2s) to compute on first request, then cached:
- `/api/validation/pairwise-results` (per dataset + content_mode)
- `/api/validation/irt-results` (per dataset + content_mode)
- `/api/validation/agreement-analysis` (per dataset + content_mode)
- `/api/validation/dual-dimension-results` (per dataset + content_mode)
- `/api/validation/multimodel-results` (per dataset)
- `/api/validation/cycle-analysis` (per dataset)
- `/api/validation/cross-mode-agreement` (per dataset)

## DO NOT revert this without explicit approval.
