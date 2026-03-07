"""
Precomputed experiment results — export from preview, serve on production.

Export: POST /api/admin/precompute-experiments (runs all computations, saves to JSON file)
Load:  On startup, if the JSON file exists, populate all caches from it — zero computation.
"""
import json
import os
import time
from pathlib import Path
from core.config import logger

PRECOMPUTED_FILE = Path(__file__).parent.parent / "data" / "precomputed" / "experiment_results.json"

# Registry: maps cache name → (cache_dict, compute_fn_import_path)
# Populated at import time with the cache dicts; compute fns resolved lazily
EXPERIMENT_REGISTRY = [
    "consistency",
    "cycle-all",
    "summarizer-ab",
    "extended-thinking",
    "multi-aspect",
    "judge-comparison",
    "assessor-evaluator",
    "model-correlation",
]


def _get_cache_and_fn(name):
    """Lazily resolve cache dict and compute function for an experiment."""
    from routers.validation_utils import (
        consistency_cache, cycle_all_cache, sumab_results_cache,
        ae_cache, extended_thinking_cache, multi_aspect_cache,
    )
    from routers.validation_experiments import _judge_comparison_cache, _model_correlation_cache

    mapping = {
        "consistency": (consistency_cache, "routers.validation", "_compute_consistency_analysis"),
        "cycle-all": (cycle_all_cache, "routers.validation", "_compute_cycle_analysis_all"),
        "summarizer-ab": (sumab_results_cache, "routers.validation_experiments", "_compute_summarizer_ab_results"),
        "extended-thinking": (extended_thinking_cache, "routers.validation_experiments", "_compute_extended_thinking_results"),
        "multi-aspect": (multi_aspect_cache, "routers.validation_experiments", "_compute_multi_aspect_results"),
        "judge-comparison": (_judge_comparison_cache, "routers.validation_experiments", "_compute_judge_comparison"),
        "assessor-evaluator": (ae_cache, "routers.validation_experiments", "_compute_assessor_evaluator"),
        "model-correlation": (_model_correlation_cache, "routers.validation_experiments", "_compute_model_correlation_analysis"),
    }
    cache, module_path, fn_name = mapping[name]
    import importlib
    mod = importlib.import_module(module_path)
    fn = getattr(mod, fn_name)
    return cache, fn


async def compute_and_export_all():
    """Compute all experiment results and save to JSON file. Run in preview only."""
    import asyncio
    results = {}
    for name in EXPERIMENT_REGISTRY:
        try:
            cache, fn = _get_cache_and_fn(name)
            result = await asyncio.wait_for(fn(), timeout=120)
            if result.get("status") == "ok":
                results[name] = result
                cache["data"] = result
                cache["ts"] = time.time()
                logger.info(f"  precompute {name}: ok")
            else:
                logger.info(f"  precompute {name}: status={result.get('status')}")
        except Exception as e:
            logger.warning(f"  precompute {name}: failed — {e}")

    # Save to file
    PRECOMPUTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRECOMPUTED_FILE, "w") as f:
        json.dump(results, f)
    size_mb = PRECOMPUTED_FILE.stat().st_size / (1024 * 1024)
    logger.info(f"Precomputed {len(results)}/{len(EXPERIMENT_REGISTRY)} experiments → {PRECOMPUTED_FILE} ({size_mb:.1f} MB)")
    return {"exported": list(results.keys()), "file": str(PRECOMPUTED_FILE), "size_mb": round(size_mb, 1)}


def load_precomputed():
    """Load precomputed results from JSON file into caches. Returns count loaded."""
    if not PRECOMPUTED_FILE.exists():
        return 0

    try:
        with open(PRECOMPUTED_FILE) as f:
            results = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load precomputed experiments: {e}")
        return 0

    loaded = 0
    for name in EXPERIMENT_REGISTRY:
        if name in results:
            try:
                cache, _ = _get_cache_and_fn(name)
                cache["data"] = results[name]
                cache["ts"] = time.time()
                loaded += 1
            except Exception as e:
                logger.warning(f"  precomputed {name}: load failed — {e}")

    if loaded:
        logger.info(f"Loaded {loaded}/{len(EXPERIMENT_REGISTRY)} precomputed experiment caches from file")
    return loaded
