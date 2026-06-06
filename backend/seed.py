"""Seed data for Kurate paper rankings platform.

Generates a realistic, deterministic dataset of scientific preprints
across multiple research categories. Data refreshes timestamps on every
import so the platform always feels live.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any


CATEGORIES: list[dict[str, Any]] = [
    {"code": "cs.AI", "name": "Artificial Intelligence", "field": "ai", "broad": "Computer Science",
     "description": "Reasoning, planning, knowledge representation, and learning systems."},
    {"code": "cs.LG", "name": "Machine Learning", "field": "ai", "broad": "Computer Science",
     "description": "Statistical learning theory, optimisation, and neural architectures."},
    {"code": "cs.CL", "name": "Computation & Language", "field": "cs", "broad": "Computer Science",
     "description": "Natural language processing, language models, and linguistic structure."},
    {"code": "cs.CV", "name": "Computer Vision", "field": "cs", "broad": "Computer Science",
     "description": "Visual recognition, representation learning, and image understanding."},
    {"code": "cs.RO", "name": "Robotics", "field": "robotics", "broad": "Engineering",
     "description": "Manipulation, control, perception, and embodied learning."},
    {"code": "quant-ph", "name": "Quantum Physics", "field": "quantum", "broad": "Physics",
     "description": "Quantum information, error correction, and condensed-matter quantum effects."},
    {"code": "math.ST", "name": "Statistics Theory", "field": "math", "broad": "Mathematics",
     "description": "Inference, estimation theory, and probabilistic foundations."},
    {"code": "q-bio.NC", "name": "Quantitative Biology", "field": "biology", "broad": "Life Sciences",
     "description": "Neuroscience, systems biology, and biological modelling."},
    {"code": "econ.GN", "name": "General Economics", "field": "econ", "broad": "Social Sciences",
     "description": "Markets, welfare, and applied econometrics."},
    {"code": "cs.CR", "name": "Cryptography & Security", "field": "security", "broad": "Computer Science",
     "description": "Cryptographic protocols, hardware security, and adversarial systems."},
    {"code": "physics.flu", "name": "Fluid Dynamics", "field": "quantum", "broad": "Physics",
     "description": "Turbulence, compressible flow, and computational fluid dynamics."},
    {"code": "math.NT", "name": "Number Theory", "field": "math", "broad": "Mathematics",
     "description": "Arithmetic geometry, L-functions, and analytic number theory."},
]


TITLE_TEMPLATES: dict[str, list[str]] = {
    "cs.AI": [
        "Emergent Reasoning in Compositional Transformer Architectures",
        "Self-Refined Chain-of-Thought via Verifier-Guided Decoding",
        "Counterfactual Planning with Learned World Models",
        "On the Sample Complexity of In-Context Inductive Reasoning",
        "Latent Search Trees for Programmatic Problem Solving",
        "Inverse Constitutional Learning for Aligned Autonomy",
        "Tractable Abductive Inference in Foundation Models",
        "Symbolic Distillation of Neural Policy Heads",
        "Hierarchical Goal Discovery without Human Demonstrations",
        "Calibrated Uncertainty for High-Stakes AI Decisions",
    ],
    "cs.LG": [
        "Scaling Laws for Conditional Diffusion under Sparse Supervision",
        "Sharpness-Aware Generalisation in Heterogeneous Federated Settings",
        "Implicit Bias of SGD on Two-Layer ReLU Networks Revisited",
        "Continual Pretraining via Replay-Free Loss Re-Weighting",
        "Convergence of Mirror Descent for Non-Convex Minimax Problems",
        "Linear Mode Connectivity Across Fine-Tuned Checkpoints",
        "Data Attribution at Pretraining Scale via Influence Sketches",
        "Adaptive Curriculum Learning with Bandit Feedback",
        "Provable Robustness via Smoothed Spectral Regularisation",
        "Out-of-Distribution Detection through Energy Recalibration",
    ],
    "cs.CL": [
        "Long-Context Retrieval with Hierarchical Position Encodings",
        "Faithful Summarisation under Conflicting Source Evidence",
        "Token-Level Provenance for Open-Ended Generation",
        "Crosslingual Transfer in Low-Resource Morphological Tagging",
        "Instruction-Tuned Models as Implicit Knowledge Editors",
        "Compositional Generalisation in Semantic Parsing Benchmarks",
        "Speculative Decoding with Speculative Verification",
        "Probing Lexical Ambiguity in Multilingual Encoders",
        "Dialogue State Tracking under Distributional Drift",
        "Sparse Retrieval over Document-Level Knowledge Graphs",
    ],
    "cs.CV": [
        "Equivariant Representation Learning for 3D Scene Reasoning",
        "Self-Supervised Video Pretraining via Temporal Order Inversion",
        "Token Pruning for Efficient Dense Prediction Transformers",
        "Open-Vocabulary Segmentation through Region-Concept Alignment",
        "Diffusion-Based Image Restoration under Heavy-Tail Noise",
        "Implicit Neural Representations for Multi-View Reconstruction",
        "Camera-Pose Conditioned Generative Priors for Novel Views",
        "Robust Few-Shot Classification via Geometric Calibration",
        "Cross-Domain Object Detection without Source Annotations",
        "Latent Editing of Concept Activations in Vision Backbones",
    ],
    "cs.RO": [
        "Whole-Body Loco-Manipulation through Contact-Implicit Optimisation",
        "Dexterous Cloth Folding via Tactile-Vision Fusion Policies",
        "Sample-Efficient Sim-to-Real with Adaptive Domain Mixing",
        "Geometric Imitation Learning for Articulated Tool Use",
        "Visuomotor Foundation Models for Mobile Manipulation",
        "Risk-Aware Motion Planning under Perception Uncertainty",
        "Learning Compliant Contact from Demonstration Sparsity",
        "Reactive Bimanual Coordination with Predictive Safety Filters",
        "Tactile-Driven Object Identification in Cluttered Bins",
        "Long-Horizon Skill Discovery via Differentiable Simulation",
    ],
    "quant-ph": [
        "Fault-Tolerant Magic State Distillation Below Threshold",
        "Variational Quantum Eigensolvers for Strongly Correlated Lattices",
        "Quantum Advantage in Sampling Sparse Boson Networks",
        "Logical Qubit Lifetimes under Coherent Noise Bias",
        "Tensor-Network Decoders for Topological Codes",
        "Entanglement Distillation at Finite Repeater Bandwidth",
        "Measurement-Induced Phase Transitions in Open Systems",
        "Quantum Error Mitigation via Probabilistic Twirling",
        "Scalable Calibration of Superconducting Qubit Arrays",
        "Floquet Engineering of Topological Edge Modes",
    ],
    "math.ST": [
        "Optimal Adaptive Confidence Bands for Nonparametric Regression",
        "Minimax Estimation under Differential Privacy Constraints",
        "High-Dimensional CLT via Stein-Type Couplings",
        "Posterior Contraction Rates for Deep Gaussian Processes",
        "Empirical Bayes Selection with Side Information",
        "Asymptotic Normality of Random Forest Quantile Estimators",
        "Sequential Testing for Detecting Distribution Shift",
        "Causal Effect Identification under Selection Bias",
        "Robust Estimation in Heavy-Tailed Linear Models",
        "Statistical Guarantees for Score-Based Diffusion Inference",
    ],
    "q-bio.NC": [
        "Cortical Representations of Belief under Naturalistic Stimuli",
        "Predictive Coding in Recurrent Spiking Networks",
        "Mesoscale Connectomics of the Mouse Visual Hierarchy",
        "Neural Geometry of Working Memory in Prefrontal Cortex",
        "Cross-Species Alignment of Single-Cell Transcriptomes",
        "Dopaminergic Modulation of Reward-Prediction Errors",
        "Energy Constraints on Synaptic Plasticity Rules",
        "Topographic Maps Emerge from Sparse Coding Objectives",
        "Brain-Wide Decoding of Decision Variables in Mice",
        "Population Dynamics of Place Cells Across Environments",
    ],
    "econ.GN": [
        "General Equilibrium Effects of Place-Based Subsidies",
        "Identifying Demand Elasticities from High-Frequency Pricing",
        "Information Frictions in Global Supply Networks",
        "Bargaining Power and Wage Posting in Concentrated Labour Markets",
        "Climate Risk Premia in Sovereign Debt Spreads",
        "Behavioural Foundations of Forward Guidance",
        "Optimal Taxation under Imperfect Capital Mobility",
        "Algorithmic Pricing and Tacit Collusion in Online Markets",
        "Heterogeneous Agent Models with Endogenous Networks",
        "Welfare Costs of Disclosure under Strategic Misreporting",
    ],
    "cs.CR": [
        "Side-Channel Resilient Lattice-Based Key Encapsulation",
        "Composable Security of Hybrid Post-Quantum Handshakes",
        "Provable Defences Against Prompt Injection in Tool-Using Agents",
        "Differential Privacy Accountants for Streaming Releases",
        "Practical Zero-Knowledge Proofs over Custom Circuits",
        "Adversarial Robustness via Certified Smoothing at Scale",
        "Memory-Safe Cryptographic Primitives in Hardware Enclaves",
        "Threshold ECDSA with Asynchronous Verifiable Broadcast",
        "Auditable Federated Learning under Malicious Aggregators",
        "Watermarking Generative Outputs with Statistical Soundness",
    ],
    "physics.flu": [
        "Reduced-Order Models of Turbulent Channel Flow via Operator Learning",
        "Non-Local Closures for Stratified Boundary Layers",
        "Anomalous Dissipation in Forced Compressible Turbulence",
        "Lagrangian Coherent Structures in Oceanic Mesoscale Eddies",
        "Hydrodynamic Instabilities in Soft Active Matter",
        "Spectral Methods for High-Reynolds Jet Simulations",
        "Data-Driven Sub-Grid Closures with Physical Constraints",
        "Transition to Turbulence in Curved Pipe Flow",
        "Acoustic-Vortex Interactions in Compressible Mixing Layers",
        "Energy Cascades in Rotating Stratified Turbulence",
    ],
    "math.NT": [
        "Effective Bounds on Class Numbers via Subconvexity",
        "Equidistribution of Heegner Points on Modular Curves",
        "p-Adic L-Functions for Hilbert Modular Forms",
        "Galois Representations Attached to Siegel Eigenforms",
        "Sieve Methods for Almost-Primes in Arithmetic Progressions",
        "Mod-p Cohomology of Arithmetic Locally Symmetric Spaces",
        "Heights and Equidistribution in Diophantine Geometry",
        "Iwasawa Theory of Elliptic Curves at Non-Ordinary Primes",
        "Bounds on Exceptional Zeros of Dirichlet L-Functions",
        "Beyond-Endoscopy and the Arthur-Selberg Trace Formula",
    ],
}


AUTHOR_POOL = [
    "Lin, Y.", "Chen, M.", "Patel, R.", "Rossi, G.", "Nakamura, S.", "Okafor, A.",
    "Garcia, L.", "Schmidt, K.", "Ivanova, N.", "Khan, F.", "Dubois, P.", "Park, J.",
    "Singh, A.", "Tan, W.", "Andersson, E.", "Cohen, D.", "Vasquez, M.", "Nguyen, H.",
    "Oliveira, R.", "Almeida, T.", "Petrov, V.", "Yamada, K.", "Brown, S.", "Murray, C.",
    "Hassan, O.", "Lefebvre, J.", "Mehta, P.", "Lambert, A.", "Sokolov, D.", "Wright, B.",
]


SIGNAL_LABELS = [
    "high agreement", "rising momentum", "strong validation", "novel framing",
    "fast-moving", "high model agreement", "robust evidence", "field-defining",
]


def _hash_to_int(s: str, mod: int) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % mod


def _arxiv_id(category_code: str, idx: int, year: int) -> str:
    # arXiv style: YYMM.NNNNN
    month = (idx % 12) + 1
    base = (idx * 4373 + _hash_to_int(category_code, 9000)) % 9000 + 1000
    return f"{str(year)[-2:]}{month:02d}.{base:05d}"


def build_papers() -> list[dict[str, Any]]:
    rng = random.Random(20260201)
    now = datetime.now(timezone.utc)
    papers: list[dict[str, Any]] = []

    for cat in CATEGORIES:
        titles = TITLE_TEMPLATES[cat["code"]]
        for i, title in enumerate(titles):
            # Distribute across recent years
            year = rng.choice([2024, 2025, 2025, 2025, 2026, 2026])
            n_authors = rng.randint(2, 5)
            authors = rng.sample(AUTHOR_POOL, k=n_authors)
            score = round(rng.uniform(72.0, 97.5), 1)
            rating = int(rng.uniform(1380, 1820))
            gap = round(rng.uniform(0.2, 9.5), 2)
            model_agreement = round(rng.uniform(0.62, 0.97), 2)
            validation = round(rng.uniform(0.55, 0.95), 2)
            momentum = round(rng.uniform(-0.2, 0.95), 2)
            novelty = round(rng.uniform(0.40, 0.95), 2)
            days_ago = rng.randint(0, 89)
            added_at = now - timedelta(days=days_ago, hours=rng.randint(0, 23))
            published_at = added_at - timedelta(days=rng.randint(0, 14))
            signal_badge = None
            if model_agreement > 0.90:
                signal_badge = "high model agreement"
            elif validation > 0.85:
                signal_badge = "strong validation"
            elif momentum > 0.75:
                signal_badge = "rising momentum"
            elif novelty > 0.85:
                signal_badge = "novel framing"
            else:
                signal_badge = rng.choice(SIGNAL_LABELS)

            papers.append({
                "id": f"{cat['code']}-{i+1:03d}",
                "arxiv_id": _arxiv_id(cat["code"], i, year),
                "title": title,
                "authors": authors,
                "category_code": cat["code"],
                "category_name": cat["name"],
                "field": cat["field"],
                "year": year,
                "score": score,
                "rating": rating,
                "gap": gap,
                "published_at": published_at.isoformat(),
                "model_agreement": model_agreement,
                "validation_signal": validation,
                "momentum": momentum,
                "novelty": novelty,
                "signal_badge": signal_badge,
                "added_at": added_at.isoformat(),
                "abstract_snippet": f"We study {title.lower()} and provide new theoretical and empirical analysis within the {cat['name']} category.",
            })

    return papers


def latest_update_string(papers: list[dict[str, Any]]) -> str:
    latest = max(papers, key=lambda p: p["added_at"])
    dt = datetime.fromisoformat(latest["added_at"])
    delta = datetime.now(timezone.utc) - dt
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"
