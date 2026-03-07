"""
Precomputed experiment + validation results — export from preview, serve on production.

Export: POST /api/admin/precompute-experiments (runs all computations, saves to JSON files)
Load:  On startup, if JSON files exist, populate all caches — zero computation.

Two files:
  - experiment_results.json: global experiment caches (8 experiments)
  - validation_results.json: per-dataset caches (status, pairwise, convergence, etc.)
"""
import json
import asyncio
import os
import time
from pathlib import Path
from core.config import db, logger

PRECOMPUTED_DIR = Path(__file__).parent.parent / "data" / "precomputed"
EXPERIMENT_FILE = PRECOMPUTED_DIR / "experiment_results.json"
VALIDATION_FILE = PRECOMPUTED_DIR / "validation_results.json"

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
    """Compute all experiment + validation results and save to JSON files."""
    exp_results = await _compute_experiments()
    val_results = await _compute_validation_datasets()

    PRECOMPUTED_DIR.mkdir(parents=True, exist_ok=True)

    with open(EXPERIMENT_FILE, "w") as f:
        json.dump(exp_results, f)
    exp_size = EXPERIMENT_FILE.stat().st_size / (1024 * 1024)

    with open(VALIDATION_FILE, "w") as f:
        json.dump(val_results, f)
    val_size = VALIDATION_FILE.stat().st_size / (1024 * 1024)

    logger.info(f"Precomputed {len(exp_results)} experiments ({exp_size:.1f} MB) + {len(val_results)} dataset caches ({val_size:.1f} MB)")
    return {
        "experiments": list(exp_results.keys()),
        "datasets": list(val_results.keys()),
        "experiment_file_mb": round(exp_size, 1),
        "validation_file_mb": round(val_size, 1),
    }


async def _compute_experiments():
    """Compute all global experiment caches."""
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
    return results


async def _compute_validation_datasets():
    """Compute per-dataset results (status, pairwise, irt, agreement, convergence, etc.)."""
    from routers.validation import (
        _compute_status, _compute_pairwise_results, _compute_convergence,
        _compute_irt_results, _compute_agreement,
        _compute_cross_mode_agreement, _compute_dual_dimension_results,
    )

    datasets = await db.validation_datasets.find({}, {"_id": 0}).to_list(100)
    dataset_ids = [d["dataset_id"] for d in datasets]

    results = {}
    for ds_id in dataset_ids:
        ds_cache = {}

        # Use a list of (name, fn) — define with default args to capture ds_id correctly
        def make_endpoints(did):
            return [
                ("status", lambda: _compute_status(did)),
                ("pairwise", lambda: _compute_pairwise_results(did, None, None)),
                ("irt", lambda: _compute_irt_results(did, None, None)),
                ("agreement", lambda: _compute_agreement(did, None, None)),
                ("cross-mode", lambda: _compute_cross_mode_agreement(did)),
                ("convergence", lambda: _compute_convergence(did, None, 20)),
                ("dual-dim", lambda: _compute_dual_dimension_results(did, None)),
            ]

        for ep_name, fn in make_endpoints(ds_id):
            try:
                result = await asyncio.wait_for(fn(), timeout=60)
                ds_cache[ep_name] = result
            except asyncio.TimeoutError:
                logger.warning(f"  precompute {ds_id}/{ep_name}: timed out")
            except Exception as e:
                logger.warning(f"  precompute {ds_id}/{ep_name}: failed — {e}")

        if ds_cache:
            results[ds_id] = ds_cache
            logger.info(f"  precompute {ds_id}: {len(ds_cache)} endpoints")

    return results


def load_precomputed():
    """Load precomputed results from JSON files into caches. Returns count loaded."""
    loaded = 0
    loaded += _load_experiments()
    loaded += _load_validation()
    return loaded


def _load_experiments():
    """Load experiment caches from file."""
    if not EXPERIMENT_FILE.exists():
        return 0
    try:
        with open(EXPERIMENT_FILE) as f:
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
            except Exception:
                pass
    if loaded:
        logger.info(f"Loaded {loaded}/{len(EXPERIMENT_REGISTRY)} precomputed experiment caches")
    return loaded


def _load_validation():
    """Load per-dataset validation caches from file."""
    if not VALIDATION_FILE.exists():
        return 0
    try:
        with open(VALIDATION_FILE) as f:
            results = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load precomputed validation: {e}")
        return 0

    from routers.validation_utils import _result_cache
    loaded = 0
    for ds_id, endpoints in results.items():
        for ep_name, data in endpoints.items():
            _result_cache[(ep_name, ds_id, "")] = {"data": data, "ts": time.time()}
            loaded += 1

    if loaded:
        logger.info(f"Loaded {loaded} precomputed validation dataset caches ({len(results)} datasets)")
    return loaded
