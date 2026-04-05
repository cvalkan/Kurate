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
ANALYSIS_FILE = PRECOMPUTED_DIR / "analysis_results.json"

EXPERIMENT_REGISTRY = [
    "consistency",
    "cycle-all",
    "summarizer-ab",
    "extended-thinking",
    "multi-aspect",
    "judge-comparison",
    "assessor-evaluator",
    "model-correlation",
    "institution-bias",
    "institution-bias-samepair",
    "single-item-scoring",
    "human-ai-benchmark-comp",
    "human-ai-benchmark-stan",
    "unified-benchmark-comp",
    "unified-benchmark-stan",
    "ai-ranking-quality-comp",
    "human-ai-benchmark-unfiltered-comp",
    "human-ai-benchmark-fixed-comp",
    "ai-ranking-quality-unfiltered-comp",
    "ai-ranking-gap-analysis-comp",
]


def _get_cache_and_fn(name):
    """Lazily resolve cache dict and compute function for an experiment."""
    from routers.validation_utils import (
        consistency_cache, cycle_all_cache, sumab_results_cache,
        ae_cache, extended_thinking_cache, multi_aspect_cache,
    )
    from routers.validation_experiments import _judge_comparison_cache, _model_correlation_cache, _INST_BIAS_CACHE, _INST_BIAS_SAMEPAIR_CACHE, _SINGLE_ITEM_CACHE

    mapping = {
        "consistency": (consistency_cache, "routers.validation", "_compute_consistency_analysis"),
        "cycle-all": (cycle_all_cache, "routers.validation", "_compute_cycle_analysis_all"),
        "summarizer-ab": (sumab_results_cache, "routers.validation_experiments", "_compute_summarizer_ab_results"),
        "extended-thinking": (extended_thinking_cache, "routers.validation_experiments", "_compute_extended_thinking_results"),
        "multi-aspect": (multi_aspect_cache, "routers.validation_experiments", "_compute_multi_aspect_results"),
        "judge-comparison": (_judge_comparison_cache, "routers.validation_experiments", "_compute_judge_comparison"),
        "assessor-evaluator": (ae_cache, "routers.validation_experiments", "_compute_assessor_evaluator"),
        "model-correlation": (_model_correlation_cache, "routers.validation_experiments", "_compute_model_correlation_analysis"),
        "institution-bias": (_INST_BIAS_CACHE, "routers.validation_experiments", "_compute_institution_bias"),
        "institution-bias-samepair": (_INST_BIAS_SAMEPAIR_CACHE, "routers.validation_experiments", "_compute_institution_bias_samepair"),
        "single-item-scoring": (_SINGLE_ITEM_CACHE, "routers.validation_experiments", "_compute_single_item_results"),
    }

    # Handle benchmark endpoints separately (they use different cache structures)
    if name == "human-ai-benchmark-comp":
        from routers.human_ai_benchmark import _benchmark_cache, _compute_benchmark
        return _benchmark_cache.setdefault("comp", {}), lambda: _compute_benchmark("comp")
    if name == "human-ai-benchmark-stan":
        from routers.human_ai_benchmark import _benchmark_cache
        from routers.standalone_benchmark import compute_standalone_benchmark
        return _benchmark_cache.setdefault("stan", {}), lambda: compute_standalone_benchmark(ai_source="pairwise")
    if name == "unified-benchmark-comp":
        from routers.unified_benchmark import _unified_cache, _compute_unified_benchmark
        return _unified_cache.setdefault("comp", {}), lambda: _compute_unified_benchmark("comp")
    if name == "unified-benchmark-stan":
        from routers.unified_benchmark import _unified_cache, _compute_unified_benchmark
        return _unified_cache.setdefault("stan", {}), lambda: _compute_unified_benchmark("stan")
    if name == "ai-ranking-quality-comp":
        from routers.human_ai_benchmark import _ranking_quality_cache, _compute_ranking_quality
        return _ranking_quality_cache.setdefault("comp", {}), lambda: _compute_ranking_quality("comp")
    if name == "human-ai-benchmark-unfiltered-comp":
        from routers.human_ai_benchmark import _benchmark_unfiltered_cache, _compute_benchmark
        return _benchmark_unfiltered_cache.setdefault("comp", {}), lambda: _compute_benchmark("comp", include_within_tier=True)
    if name == "human-ai-benchmark-fixed-comp":
        from routers.human_ai_benchmark import _benchmark_fixed_cache, _compute_benchmark
        return _benchmark_fixed_cache.setdefault("comp", {}), lambda: _compute_benchmark(
            "comp", include_within_tier=True, min_expert_prefs=1,
            rankable_tiers_only=True, exclude_datasets={"peerread_acl_2017"})
    if name == "ai-ranking-quality-unfiltered-comp":
        from routers.human_ai_benchmark import _ranking_quality_unfiltered_cache, _compute_ranking_quality
        return _ranking_quality_unfiltered_cache.setdefault("comp", {}), lambda: _compute_ranking_quality("comp", include_within_tier=True)
    if name == "ai-ranking-gap-analysis-comp":
        from routers.human_ai_benchmark import _gap_analysis_cache, _compute_gap_analysis
        return _gap_analysis_cache.setdefault("comp", {}), lambda: _compute_gap_analysis("comp")
    cache, module_path, fn_name = mapping[name]
    import importlib
    mod = importlib.import_module(module_path)
    fn = getattr(mod, fn_name)
    return cache, fn


async def compute_and_export_all():
    """Compute all experiment + validation + analysis results and save to JSON files."""
    exp_results = await _compute_experiments()
    val_results = await _compute_validation_datasets()
    analysis_results = await _compute_analysis_caches()

    PRECOMPUTED_DIR.mkdir(parents=True, exist_ok=True)

    with open(EXPERIMENT_FILE, "w") as f:
        json.dump(exp_results, f)
    exp_size = EXPERIMENT_FILE.stat().st_size / (1024 * 1024)

    with open(VALIDATION_FILE, "w") as f:
        json.dump(val_results, f)
    val_size = VALIDATION_FILE.stat().st_size / (1024 * 1024)

    with open(ANALYSIS_FILE, "w") as f:
        json.dump(analysis_results, f)
    analysis_size = ANALYSIS_FILE.stat().st_size / (1024 * 1024)

    logger.info(f"Precomputed {len(exp_results)} experiments ({exp_size:.1f} MB) + {len(val_results)} dataset caches ({val_size:.1f} MB) + {len(analysis_results)} analysis caches ({analysis_size:.1f} MB)")
    return {
        "experiments": list(exp_results.keys()),
        "datasets": list(val_results.keys()),
        "analysis_endpoints": len(analysis_results),
        "experiment_file_mb": round(exp_size, 1),
        "validation_file_mb": round(val_size, 1),
        "analysis_file_mb": round(analysis_size, 1),
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
    """Compute per-dataset results for ALL content modes (status, pairwise, irt, agreement, convergence, convergence-all, etc.)."""
    from routers.validation import (
        _compute_status, _compute_pairwise_results, _compute_convergence,
        _compute_irt_results, _compute_agreement,
        _compute_cross_mode_agreement, _compute_dual_dimension_results,
        get_convergence_all,
    )

    datasets = await db.validation_datasets.find({}, {"_id": 0}).to_list(1000)
    dataset_ids = [d["dataset_id"] for d in datasets]

    results = {}
    for ds_id in dataset_ids:
        ds_cache = {}

        # Discover ALL available content modes for this dataset
        mode_pipeline = [
            {"$match": {"dataset_id": ds_id, "completed": True, "failed": {"$ne": True}}},
            {"$group": {"_id": {"$ifNull": ["$content_mode", "none"]}, "count": {"$sum": 1}}},
        ]
        modes_with_data = []
        async for doc in db.validation_matches.aggregate(mode_pipeline):
            cm = doc["_id"]
            if cm in ("none", None, ""):
                cm = "extract"
            if doc["count"] >= 10:
                modes_with_data.append(cm)
        if not modes_with_data:
            modes_with_data = ["abstract"]

        # Mode-independent endpoints
        for ep_name, fn in [
            ("status", lambda: _compute_status(ds_id)),
            ("cross-mode", lambda: _compute_cross_mode_agreement(ds_id)),
            ("convergence-all", lambda: get_convergence_all(dataset_id=ds_id, steps=20)),
        ]:
            try:
                result = await asyncio.wait_for(fn(), timeout=120)
                ds_cache[ep_name] = result
            except asyncio.TimeoutError:
                logger.warning(f"  precompute {ds_id}/{ep_name}: timed out")
            except Exception as e:
                logger.warning(f"  precompute {ds_id}/{ep_name}: failed — {e}")

        # Per-mode endpoints: compute for EVERY content mode
        for mode in modes_with_data:
            mode_suffix = f":{mode}" if mode != "abstract" else ""
            for ep_base, fn_factory in [
                ("pairwise", lambda m=mode: _compute_pairwise_results(ds_id, None, m)),
                ("irt", lambda m=mode: _compute_irt_results(ds_id, None, m)),
                ("agreement", lambda m=mode: _compute_agreement(ds_id, None, m)),
                ("convergence", lambda m=mode: _compute_convergence(ds_id, m, 20)),
                ("dual-dim", lambda m=mode: _compute_dual_dimension_results(ds_id, m)),
            ]:
                cache_key = f"{ep_base}{mode_suffix}"
                try:
                    result = await asyncio.wait_for(fn_factory(), timeout=60)
                    ds_cache[cache_key] = result
                except asyncio.TimeoutError:
                    logger.warning(f"  precompute {ds_id}/{cache_key}: timed out")
                except Exception as e:
                    logger.warning(f"  precompute {ds_id}/{cache_key}: failed — {e}")

            await asyncio.sleep(0)  # Yield between modes

        if ds_cache:
            results[ds_id] = ds_cache
            logger.info(f"  precompute {ds_id}: {len(ds_cache)} endpoints ({len(modes_with_data)} modes)")

    return results


async def _compute_analysis_caches():
    """Compute Model Analysis page data per category using unified compute_model_analysis."""
    from services.model_analysis import compute_model_analysis
    from core.config import CATEGORIES

    results = {}
    categories = [None]  # None = all categories
    for cat_info in CATEGORIES:
        cat_id = cat_info["id"] if isinstance(cat_info, dict) else cat_info
        categories.append(cat_id)

    for cat in categories:
        cat_key = cat or "__all__"
        try:
            result = await asyncio.wait_for(compute_model_analysis(cat), timeout=120)
            if result.get("status") == "ok":
                results[f"model-analysis:{cat_key}"] = result
        except Exception as e:
            logger.warning(f"  precompute model-analysis/{cat_key}: {e}")
        await asyncio.sleep(0)

    logger.info(f"  precompute analysis: {len(results)} endpoints across {len(categories)} categories")
    return results


def load_precomputed():
    """Load precomputed results from JSON files into caches. Returns count loaded."""
    loaded = 0
    loaded += _load_experiments()
    loaded += _load_validation()
    loaded += _load_analysis()
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

    from routers.validation_utils import _result_cache, convergence_all_cache
    # Base endpoint names (without mode suffix)
    _MODE_ENDPOINTS = {"pairwise", "irt", "agreement", "convergence", "dual-dim"}
    loaded = 0
    for ds_id, endpoints in results.items():
        for ep_name, data in endpoints.items():
            # convergence-all goes into its own dedicated cache (multi-mode format)
            if ep_name == "convergence-all":
                if data and data.get("status") == "ok" and data.get("modes"):
                    convergence_all_cache[ds_id] = {"data": data, "ts": time.time()}
                    loaded += 1
                continue

            # Parse "pairwise:abstract_plus_summary:thinking" → base="pairwise", mode="abstract_plus_summary:thinking"
            # Or "pairwise" → base="pairwise", mode=""
            # Or "status" → base="status", mode=""
            parts = ep_name.split(":", 1)
            base = parts[0]
            mode = parts[1] if len(parts) > 1 else ""

            if base in _MODE_ENDPOINTS and mode:
                # Per-mode entry: store with the exact content_mode
                _result_cache[(base, ds_id, mode)] = {"data": data, "ts": time.time()}
                loaded += 1
            elif base in _MODE_ENDPOINTS:
                # Default mode entry: store with "" and "abstract"
                _result_cache[(base, ds_id, "")] = {"data": data, "ts": time.time()}
                loaded += 1
                _result_cache[(base, ds_id, "abstract")] = {"data": data, "ts": time.time()}
                loaded += 1
            else:
                # Non-mode endpoints (status, cross-mode)
                _result_cache[(base, ds_id, "")] = {"data": data, "ts": time.time()}
                loaded += 1

    if loaded:
        logger.info(f"Loaded {loaded} precomputed validation dataset caches ({len(results)} datasets)")
    return loaded


def _load_analysis():
    """Load precomputed analysis caches.
    
    Analysis endpoints now read from MongoDB analysis_store (not in-memory cache).
    This function is a no-op but kept for backward compatibility with load_precomputed().
    """
    return 0
