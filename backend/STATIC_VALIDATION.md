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

## Endpoints covered by this rule
- `/api/validation/pairwise-results`
- `/api/validation/convergence-all`
- `/api/validation/irt-results`
- `/api/validation/agreement-analysis`
- `/api/validation/dual-dimension-results`
- `/api/validation/multimodel-results`
- `/api/validation/cycle-analysis`
- `/api/validation/cross-mode-agreement`
- `/api/validation/consistency-analysis`
- `/api/validation/cycle-analysis-all`
- `/api/validation/summarizer-ab/results`
- `/api/validation/judge-comparison/results`
- `/api/validation/single-item-scoring/results`
- `/api/validation/human-ai-benchmark`
- `/api/validation/unified-benchmark`
- `/api/validation/extended-thinking/results`
- `/api/validation/multi-aspect/results`
- `/api/validation/model-correlation-analysis/results`
- `/api/validation/institution-bias/results`
- `/api/validation/institution-bias-samepair/results`
- `/api/validation/assessor-evaluator/results`

## DO NOT revert this without explicit approval.
