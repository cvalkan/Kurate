# Kurate.org — Investor Pitch

## The Problem

**Scientific peer review is broken.** Over 5 million research papers are published annually, yet the system that evaluates them — peer review — hasn't changed in 350 years. It's slow (3–12 months), expensive ($2–5B annually in donated reviewer time), inconsistent (reviewers disagree on the same paper 60–75% of the time), and increasingly overwhelmed. Major venues like NeurIPS and ICLR now receive 15,000+ submissions per cycle with rejection rates above 75%. Reviewers are burned out, editors are desperate, and researchers waste months waiting for verdicts that are often arbitrary.

Meanwhile, researchers drown in volume. There is no reliable, real-time way to discover which new papers in your field actually matter — you either follow Twitter or read everything.

---

## The Solution

**Kurate.org is an AI-powered scientific paper ranking platform.** We use multiple frontier AI models as judges — GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro — to evaluate papers through pairwise tournaments, producing ranked leaderboards per research field that update in real time.

Think of it as **a "Rotten Tomatoes for science"** — but instead of aggregating human critic scores, we aggregate AI judge evaluations using tournament-grade ranking algorithms and validate them rigorously against human expert benchmarks.

### How it works

1. **Papers are automatically ingested** from ArXiv and ChemRxiv across 14+ research categories
2. **Each paper receives a detailed AI impact assessment** from three independent AI models — analyzing novelty, methodology, real-world impact, and rigor
3. **Papers compete in pairwise tournaments** — AI judges compare papers head-to-head, and results feed into statistical ranking algorithms (Win-Rate, TrueSkill, OpenSkill)
4. **Rankings converge** using adaptive matchmaking that focuses comparisons where uncertainty is highest, reaching statistical stability with ~30 matches per paper
5. **Validation benchmarks** continuously measure how well AI rankings correlate with human expert judgments across 9 peer-reviewed datasets (ICLR, PeerRead, eLife, and more)

---

## Why Now

Three converging trends make this the right moment:

- **Frontier AI models crossed a quality threshold.** Our benchmarks show AI judges achieve 0.70+ Spearman correlation with human expert rankings — comparable to the 0.49 correlation between individual human reviewers themselves. AI isn't just "pretty good" — it's already within striking distance of human consensus.

- **Publication volume is exponential.** ArXiv alone adds 20,000+ papers per month. No human system can keep up. Researchers need automated curation that's transparent and auditable.

- **The AI evaluation methodology is now scientifically grounded.** The ReviewerToo framework (arXiv:2510.08867) established that diverse AI reviewer personas can match human panel accuracy — a result we're building into our multi-model architecture.

---

## Traction

| Metric | Value |
|--------|-------|
| Research categories covered | 14 (CS, Physics, Chemistry, Economics, Biology, Cosmology) |
| Papers ranked | 5,100+ |
| AI pairwise comparisons | 150,000+ tournament matches |
| Validation benchmark matches | 150,000+ (against human ground truth) |
| AI–human correlation (Spearman ρ) | 0.70 pooled across 9 benchmark datasets |
| Human internal agreement (single reviewer vs panel) | 0.49 — AI already outperforms |
| Total platform cost to date | ~$700 in LLM API calls |
| Match throughput | ~50 comparisons/minute (scalable to 100+) |
| Correlation page load time | <200ms (real-time interactive analytics) |

All built and operated by a single founder with $700 in API costs — demonstrating extreme capital efficiency.

---

## Product

### For Researchers (Free Tier)
- **Real-time ranked leaderboards** per field — see what's trending in your area this week
- **Paper detail pages** with AI impact assessments, win/loss records, and head-to-head comparisons
- **Model Correlation dashboard** — transparent methodology showing how AI judges agree with each other and with human reviewers

### For Power Users (Premium)
- **Email alerts** when new top-ranked papers appear in your field
- **Author verification** — claim your papers and track their ranking trajectory
- **Custom category creation** — create private leaderboards for niche topics
- **API access** for institutions integrating rankings into internal tools

### For Conferences & Journals (Enterprise)
- **AI-assisted reviewer assignment** — match papers to reviewers based on AI-assessed topic and difficulty
- **Submission triage** — pre-screen thousands of submissions to prioritize human review effort
- **Benchmark-as-a-service** — validate your own AI review pipeline against our human-expert benchmarks

---

## Unique Advantages

**Multi-model consensus, not single-model opinion.** Three frontier models judge independently. Inter-model agreement rates and per-model rankings are fully transparent — users can see where models agree and where they diverge.

**Validated against human experts.** We don't just claim AI can rank papers — we prove it. Nine peer-reviewed benchmark datasets with controlled experiments, published methodology, and reproducible results. No other platform does this.

**Statistically rigorous ranking.** Tournament-grade algorithms (TrueSkill, OpenSkill) with confidence intervals, convergence goals, and adaptive matchmaking. Every ranking comes with a statistical uncertainty estimate.

**Extreme cost efficiency.** An AI comparison costs ~$0.005. A human peer review costs ~$500 in reviewer time. That's a 100,000x cost advantage — enabling exhaustive evaluation at scale that's economically impossible with humans.

**Real-time.** Papers are ranked within hours of appearing on ArXiv, not months. Researchers get signal when it matters most — during the critical first weeks after publication.

---

## Market

### Target Audience
- **2.5M active researchers** publishing on ArXiv annually (primary)
- **50,000+ conference organizers and journal editors** managing peer review (enterprise)
- **10,000+ R&D teams** at companies tracking academic literature (API)

### Market Size
- Global academic publishing: **$28B** (2024)
- Peer review management tools: **$1.2B** and growing 15% annually
- Research discovery platforms: **$3.5B** (Semantic Scholar, ResearchGate, Google Scholar)

### Competitive Landscape

| Platform | What they do | What they lack |
|----------|-------------|----------------|
| **Semantic Scholar** | AI-powered paper search + citation analysis | No quality ranking, no pairwise evaluation |
| **Google Scholar** | Citation indexing | Citations ≠ quality; 3–5 year lag |
| **ResearchGate** | Social network for researchers | Engagement metrics, not quality assessment |
| **OpenReview** | Open peer review for conferences | Human-only, slow, per-conference |
| **Scite.ai** | Citation context analysis | Backward-looking (existing citations only) |
| **Kurate.org** | **AI-judged real-time ranking with human validation** | **Us — no one else does this** |

**Our moat:** The combination of multi-model AI evaluation + rigorous human-expert validation + tournament-grade statistics. Competitors would need to replicate our 300K+ match dataset, benchmark infrastructure, and ranking methodology — a 12+ month effort even with funding.

---

## Business Model

**Freemium subscription** with three tiers:

| Tier | Price | Features |
|------|-------|----------|
| **Free** | $0 | Leaderboards, paper pages, methodology transparency |
| **Pro** | $15/month | Email alerts, author profiles, saved searches, API (1K calls/mo) |
| **Institution** | $500/month | Unlimited API, custom categories, bulk export, priority support |
| **Enterprise** | Custom | Conference triage, reviewer matching, white-label benchmarks |

**Revenue projections (conservative):**
- Year 1: 500 Pro + 20 Institution = ~$210K ARR
- Year 2: 5,000 Pro + 100 Institution + 5 Enterprise = ~$1.8M ARR
- Year 3: 25,000 Pro + 500 Institution + 25 Enterprise = ~$10M ARR

---

## The Ask

**Raising $500K pre-seed** to:

1. **Expand to 50+ categories** covering all major scientific fields ($100K — LLM costs + infrastructure)
2. **Build premium features** — alerts, author verification, API ($150K — engineering)
3. **Launch enterprise pilot** with 2–3 major conferences ($100K — BD + integration)
4. **Grow the research community** — content marketing, academic partnerships ($100K — marketing)
5. **Operations runway** — 18 months to Series A metrics ($50K)

**Target milestones for Series A:**
- 50K monthly active researchers
- 100+ institutional subscribers
- 2+ enterprise conference pilots
- $500K+ ARR

---

## Why This Team, Why Now

Kurate.org was built from zero to 5,100 papers, 150K matches, and 14 categories — by a single founder spending $700 total. The platform already produces rankings that correlate with human expert judgment at ρ = 0.70, outperforming individual human reviewers (ρ = 0.49).

The infrastructure is production-grade: auto-scaling tournaments, real-time dashboards, and a validated benchmarking pipeline that no competitor has. Everything that follows — more categories, premium features, enterprise deals — is distribution, not invention.

**The core technology works. The market is massive. The timing is now.**

---

*kurate.org — AI-powered science ranking, validated by humans.*
