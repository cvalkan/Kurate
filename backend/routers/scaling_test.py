"""
Synthetic paper generator for list-view scaling tests.

Produces N papers with the same shape as the real prompt-stability endpoint so
the frontend list view can be stress-tested against 10k / 50k / 100k records.
Deterministic on (n, seed) pair so tests are reproducible.
"""
from fastapi import APIRouter, Query, Response
from datetime import datetime, timedelta, timezone
import random
import json
import time

router = APIRouter(prefix="/api/scaling-test", tags=["scaling_test"])

# --- vocabulary ---------------------------------------------------------------

_TITLE_WORDS = [
    "Learning", "Neural", "Graph", "Transformer", "Diffusion", "Optimal", "Adaptive",
    "Sparse", "Robust", "Differentiable", "Causal", "Generative", "Bayesian", "Stochastic",
    "Recurrent", "Convolutional", "Attention", "Reinforcement", "Self-Supervised",
    "Quantum", "Symbolic", "Hierarchical", "Multimodal", "Federated", "Equivariant",
    "Manifold", "Latent", "Spectral", "Topological", "Variational", "Adversarial",
    "Contrastive", "Embedding", "Retrieval", "Distillation", "Calibration", "Alignment",
    "Reasoning", "Forecasting", "Estimation", "Inference", "Synthesis", "Compression",
    "Regularization", "Pruning", "Quantization", "Augmentation", "Sampling", "Decoder",
    "Encoder", "Pretraining", "Fine-tuning", "In-Context", "Prompting", "Tokenization",
    "Sequence", "Trajectory", "Policy", "Reward", "Value", "Exploration", "Planning",
    "Control", "Simulation", "Dynamics", "Optimization", "Convergence", "Stability",
    "Foundation", "Modeling", "Scaling", "Emergent", "Compositional", "Modular",
    "Discrete", "Continuous", "Differential", "Algebraic", "Geometric", "Probabilistic",
    "Information-Theoretic", "Game-Theoretic", "Mechanistic", "Interpretable",
]

_CONNECTORS = ["for", "via", "with", "through", "under", "from", "to", "in", "on"]

_DOMAINS = [
    "Image Recognition", "Language Modeling", "Robotic Manipulation", "Protein Folding",
    "Drug Discovery", "Climate Forecasting", "High-Energy Physics", "Computational Biology",
    "Recommendation Systems", "Speech Synthesis", "Computer Vision", "Natural Language",
    "Multi-Agent Systems", "Autonomous Driving", "Materials Science", "Genomics",
    "Quantum Chemistry", "Astrophysics", "Cryptography", "Theorem Proving",
    "Code Generation", "Search Engines", "Time Series", "Tabular Data", "Audio Generation",
    "Video Understanding", "Healthcare Imaging", "Financial Modeling", "Industrial Control",
]

_FIRST = [
    "Wei", "Akira", "Carlos", "Maria", "Yuki", "Aditi", "Hassan", "Liang", "Sven", "Ines",
    "Naoko", "Andrei", "Priya", "Tomas", "Anya", "Lukas", "Sofia", "Eduardo", "Mei",
    "Rajesh", "Hana", "Ahmed", "Iris", "Boris", "Camille", "Pavel", "Sara", "Diego",
    "Yusuf", "Olga", "Daichi", "Nadia", "Jiwoo", "Mateo", "Lucia", "Felix", "Zara",
]
_LAST = [
    "Smith", "Tanaka", "Kumar", "Schneider", "Rossi", "Petrov", "Sato", "Garcia", "Wang",
    "Li", "Park", "Chen", "Mueller", "Dubois", "Andersen", "Suzuki", "Ivanov", "Patel",
    "Nakamura", "Khan", "Rodriguez", "Yamamoto", "Hoffman", "Kowalski", "Silva",
    "Cohen", "Novak", "Olsen", "Martinez", "Ng", "Kim", "Yoon", "Choi", "Costa",
]

_CATEGORIES = [
    # ML / CS
    "cs.LG", "cs.AI", "cs.CV", "cs.CL", "cs.NE", "cs.RO", "cs.MA", "cs.IR", "cs.DC",
    "cs.GT", "cs.IT", "cs.LO", "cs.PL", "cs.SE", "cs.CR", "cs.DS", "cs.SY",
    # Stats / Math
    "stat.ML", "stat.ME", "stat.TH", "math.OC", "math.ST", "math.PR", "math.NA",
    # Physics
    "quant-ph", "cond-mat.mtrl-sci", "cond-mat.stat-mech", "cond-mat.str-el",
    "hep-th", "hep-ph", "astro-ph.GA", "astro-ph.CO", "physics.comp-ph",
    # Biology
    "q-bio.BM", "q-bio.NC", "q-bio.QM",
    # Other
    "econ.EM", "eess.SP", "eess.IV", "eess.AS",
]

_REASON_TEMPLATES = {
    "difficulty": [
        "Requires graduate-level expertise in {domain} and familiarity with advanced {topic}.",
        "Accessible to anyone with undergraduate background in {domain}; no specialist tooling needed.",
        "Deep specialist territory — relies on niche techniques in {topic}.",
    ],
    "surprisingness": [
        "Findings strongly conflict with the prevailing view that {topic} required {alt}.",
        "Confirms what most practitioners already assumed about {topic}; few unexpected wins.",
        "Mildly surprising: a known technique applied to {domain} with stronger gains than expected.",
    ],
    "reproducibility": [
        "Authors release code, weights, and clear hyperparameter tables — re-running should be straightforward.",
        "Reproducing the headline result would require access to a closed-source dataset and significant compute.",
        "Partial reproducibility: methodology is clear but training data is not fully described.",
    ],
    "translational_potential": [
        "Direct path to industrial deployment in {domain}; patentable improvement over current systems.",
        "Primarily theoretical contribution; applied follow-ups are conceivable but distant.",
        "Strong commercial relevance for {domain} pipelines, with clear economic upside if it generalises.",
    ],
    "evidence_strength": [
        "Comprehensive ablations across {n} benchmarks plus a theoretical bound supporting the main claim.",
        "Single benchmark, modest improvement, no ablations — claims rest on a narrow base.",
        "Strong empirical evidence on standard benchmarks but limited variance reporting.",
    ],
    "generalisability": [
        "Tested across {n} domains and the method appears largely architecture-agnostic.",
        "Findings tied closely to the specific {domain} setting; generalisation unclear.",
        "Plausibly generalises to adjacent settings; authors hint at broader applicability.",
    ],
}

_METRIC_KEYS_CORE = ["score", "significance", "rigor", "novelty", "clarity"]
_METRIC_KEYS_EXT  = ["difficulty", "surprisingness", "reproducibility", "translational_potential", "evidence_strength", "generalisability"]


def _gen_title(rng: random.Random) -> str:
    head = rng.choice(_TITLE_WORDS)
    mid = rng.choice(_TITLE_WORDS)
    connector = rng.choice(_CONNECTORS)
    domain = rng.choice(_DOMAINS)
    # 20% chance of a colon-prefixed working title (more variety)
    if rng.random() < 0.2:
        codename = rng.choice([
            "Atlas", "Pulse", "Spectra", "Loom", "Helix", "Quanta", "Mosaic",
            "Cascade", "Prism", "Echo", "Drift", "Aether", "Forge", "Lattice",
        ])
        return f"{codename}: {head} {mid} {connector} {domain}"
    return f"{head} {mid} {connector} {domain}"


def _gen_authors(rng: random.Random) -> list:
    n = rng.choices([1, 2, 3, 4, 5, 6, 7, 8, 10], weights=[3, 6, 10, 12, 10, 8, 6, 5, 3])[0]
    return [f"{rng.choice(_FIRST)} {rng.choice(_LAST)}" for _ in range(n)]


def _gen_categories(rng: random.Random) -> list:
    primary = rng.choice(_CATEGORIES)
    extras_n = rng.choices([0, 1, 2, 3, 4, 5], weights=[40, 25, 15, 10, 6, 4])[0]
    extras = []
    for _ in range(extras_n):
        c = rng.choice(_CATEGORIES)
        if c != primary and c not in extras:
            extras.append(c)
    return [primary] + extras


def _gen_published(rng: random.Random) -> str:
    days_ago = rng.choices(
        [0, 1, 3, 7, 14, 30, 60, 90, 180, 365, 730],
        weights=[2, 3, 5, 8, 10, 14, 14, 12, 12, 12, 8],
    )[0]
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=rng.randint(0, 86400))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_score(rng: random.Random, base: float, jitter: float = 0.9) -> float:
    v = rng.gauss(base, jitter)
    v = max(1.0, min(10.0, v))
    return round(v * 2) / 2.0  # 0.5 increments to match real ratings


def _gen_reason(rng: random.Random, metric: str) -> str:
    template = rng.choice(_REASON_TEMPLATES[metric])
    return template.format(
        domain=rng.choice(_DOMAINS),
        topic=rng.choice(_DOMAINS),
        alt=rng.choice(_DOMAINS),
        n=rng.randint(3, 12),
    )


def _gen_paper(rng: random.Random, include_reasoning: bool = True) -> dict:
    # Each paper has a per-paper "talent" base that correlates all its scores
    base = rng.uniform(3.5, 8.5)
    cats = _gen_categories(rng)
    ratings = {}
    for k in _METRIC_KEYS_CORE:
        ratings[k] = _gen_score(rng, base, 0.9)
    for k in _METRIC_KEYS_EXT:
        # 15% chance of N/A for extended dims (matches the real "theoretical/position paper" pattern)
        if rng.random() < 0.15:
            ratings[k] = None
            ratings[f"{k}_reason"] = None if include_reasoning else None
        else:
            ratings[k] = _gen_score(rng, base, 1.1)
            ratings[f"{k}_reason"] = _gen_reason(rng, k) if include_reasoning else None
    # Pseudo-uuid: cheaper than uuid4()
    pid_hi = rng.getrandbits(64)
    pid_lo = rng.getrandbits(64)
    paper_id = f"{pid_hi:016x}-{pid_lo:016x}"
    arxiv_id = f"2{rng.randint(1,12):02d}.{rng.randint(10000, 99999)}v{rng.randint(1, 3)}"
    return {
        "paper_id": paper_id,
        "title": _gen_title(rng),
        "category": cats[0],
        "categories": cats,
        "authors": _gen_authors(rng),
        "published": _gen_published(rng),
        "arxiv_id": arxiv_id,
        "ratings": ratings,
    }


@router.get("/papers")
async def scaling_test_papers(
    n: int = Query(1000, ge=1, le=200_000),
    seed: int = Query(42),
    reasoning: bool = Query(True, description="Include _reason strings (set False to test smaller payload)"),
):
    """Generate N synthetic papers in the same schema as /api/prompt-stability-results.exp3.

    Deterministic on (n, seed). Frontend mirrors the schema so the heatmap can render
    these directly without any other backend changes.
    """
    t0 = time.time()
    rng = random.Random(seed)
    papers = [_gen_paper(rng, include_reasoning=reasoning) for _ in range(n)]
    gen_ms = int((time.time() - t0) * 1000)
    payload = {
        "n": n,
        "seed": seed,
        "reasoning": reasoning,
        "gen_ms": gen_ms,
        "exp3": {"n": n, "papers": papers},
    }
    # Use ORJSON-style fast path via json.dumps; FastAPI's default is already fast enough for this.
    body = json.dumps(payload, separators=(",", ":"))
    return Response(content=body, media_type="application/json")
