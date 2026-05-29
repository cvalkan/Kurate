import { useState, useEffect } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Link } from "react-router-dom";
import {
  Trophy, BarChart3, BookOpen, ArrowRight, LogIn,
  Layers, Brain, LayoutGrid, Lightbulb, TrendingUp,
  Clock, Building2, GraduationCap, Users, Briefcase,
  FileText, Globe, Shield, ChevronRight, Zap,
  Microscope, BookMarked, Sparkles, FlaskConical,
} from "lucide-react";
import {
  Accordion, AccordionItem, AccordionTrigger, AccordionContent,
} from "@/components/ui/accordion";

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) {
  if (!n) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

/* ═══════════════ MAIN COMPONENT ═══════════════ */
export default function HomePage() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/homepage/stats`).then(r => setStats(r.data)).catch(() => {});
  }, []);

  const allCats = stats?.categories || [];

  return (
    <>
      <Helmet>
        <title>Kurate.org — AI Paper Rankings</title>
        <meta name="description" content="AI-powered scientific paper rankings. Three LLMs judge which preprints have the highest potential impact across Robotics, Game Theory, Economics, Physics, and more." />
        <link rel="canonical" href="https://kurate.org" />
        <meta property="og:title" content="Kurate.org — AI Paper Rankings" />
        <meta property="og:description" content="AI-powered scientific paper rankings. Three LLMs judge which preprints have the highest potential impact." />
        <meta property="og:image" content="https://kurate.org/kurate-logo.png" />
        <meta property="og:url" content="https://kurate.org" />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:title" content="Kurate.org — AI Paper Rankings" />
        <meta name="twitter:description" content="AI-powered scientific paper rankings. Three LLMs judge which preprints have the highest potential impact." />
        <meta name="twitter:image" content="https://kurate.org/kurate-logo.png" />
      </Helmet>

      {/* ── HERO ── */}
      <section className="relative overflow-hidden border-b border-border" data-testid="hero-section">
        <div className="absolute inset-0 bg-gradient-to-b from-accent/[0.04] to-transparent pointer-events-none" />
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-12 md:py-20 relative">
          <div className="max-w-3xl mb-10">
            <h1 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-tight mb-5 text-foreground whitespace-nowrap" data-testid="hero-heading">
              Discover top-ranked arXiv preprints
            </h1>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed max-w-2xl">
              Kurate ranks <strong className="text-foreground">arXiv preprints</strong> using
              AI-assisted comparison across {stats?.total_categories || "multiple"} research
              categories — helping researchers, students, and institutions identify promising
              work before citation signals mature.
            </p>
            <div className="flex flex-wrap gap-3 mt-7">
              <button onClick={() => window.dispatchEvent(new Event("open-auth-modal"))} className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-5 py-2.5 rounded-md font-medium text-sm hover:bg-accent/90 transition-colors" data-testid="hero-signup-btn">
                <LogIn className="h-4 w-4" /> Sign up free
              </button>
              <a href="/?tagOpen=1&period=recent" className="inline-flex items-center gap-2 border border-border bg-card text-foreground px-5 py-2.5 rounded-md font-medium text-sm hover:bg-secondary transition-colors" data-testid="hero-explore-btn">
                Explore rankings <ArrowRight className="h-4 w-4" />
              </a>
              <Link to="/methodology" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors px-3 py-2.5" data-testid="hero-methodology-btn">
                <BookOpen className="h-4 w-4" /> Methodology
              </Link>
            </div>
          </div>

          {/* Hero ranking cards */}
          <h2 className="font-heading text-xl md:text-2xl font-semibold tracking-tight mb-2">Recent rankings</h2>
          <p className="text-muted-foreground text-base mb-6">Newly ranked preprints across all active categories.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-5" data-testid="hero-cards">
            <a href="/?period=recent" className="group bg-accent/[0.06] border border-accent/20 rounded-lg p-7 hover:shadow-md hover:border-accent/40 transition-all flex flex-col" data-testid="hero-card-recent">
              <Clock className="h-7 w-7 text-accent mb-4" />
              <h3 className="font-heading font-semibold text-lg mb-2">All categories</h3>
              <p className="text-muted-foreground text-sm leading-relaxed flex-1">Latest ranked preprints across every active research field.</p>
              <span className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-4 py-2 rounded-md text-sm font-medium group-hover:gap-3 transition-all mt-5 self-start">View rankings <ArrowRight className="h-4 w-4" /></span>
            </a>
            <a href="/?cat=cs.AI&period=recent" className="group bg-accent/[0.06] border border-accent/20 rounded-lg p-7 hover:shadow-md hover:border-accent/40 transition-all flex flex-col" data-testid="hero-card-ai">
              <Brain className="h-7 w-7 text-accent mb-4" />
              <h3 className="font-heading font-semibold text-lg mb-2">AI papers</h3>
              <p className="text-muted-foreground text-sm leading-relaxed flex-1">Artificial Intelligence category rankings.</p>
              <span className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-4 py-2 rounded-md text-sm font-medium group-hover:gap-3 transition-all mt-5 self-start">View rankings <ArrowRight className="h-4 w-4" /></span>
            </a>
            <a href="/?cat=quant-ph&period=recent" className="group bg-accent/[0.06] border border-accent/20 rounded-lg p-7 hover:shadow-md hover:border-accent/40 transition-all flex flex-col" data-testid="hero-card-physics">
              <Sparkles className="h-7 w-7 text-accent mb-4" />
              <h3 className="font-heading font-semibold text-lg mb-2">Quantum Physics</h3>
              <p className="text-muted-foreground text-sm leading-relaxed flex-1">Quantum Physics category rankings.</p>
              <span className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-4 py-2 rounded-md text-sm font-medium group-hover:gap-3 transition-all mt-5 self-start">View rankings <ArrowRight className="h-4 w-4" /></span>
            </a>
          </div>
        </div>
      </section>

      {/* ── RESEARCH INTELLIGENCE (new panel) ── */}
      <section className="bg-[hsl(218,60%,30%)] text-white border-b" data-testid="research-intelligence">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-tight mb-3">Research Intelligence</h2>
          <p className="text-white/75 text-base md:text-lg leading-relaxed mb-10 max-w-3xl">
            Kurate turns arXiv preprint rankings into structured research signals that help
            users discover important papers, compare activity across fields, and monitor
            emerging scientific directions.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-10">
            {[
              { icon: BarChart3, title: "Research signal mapping", desc: "Track how preprints are ranked, compared, and positioned across research categories." },
              { icon: TrendingUp, title: "Category momentum", desc: "Identify which fields and topics are becoming more active through newly ranked and top-ranked papers." },
              { icon: Brain, title: "Paper-level interpretation", desc: "Use AI-assisted analysis to understand novelty, rigour, relevance, and potential impact before deciding what to read in depth." },
              { icon: Globe, title: "Strategic discovery", desc: "Support literature review, research monitoring, editorial scanning, funding analysis, and R&D horizon scanning." },
            ].map((c, i) => {
              const Icon = c.icon;
              return (
                <div key={i} className="bg-white/[0.08] border border-white/12 rounded-lg p-6">
                  <Icon className="h-6 w-6 text-blue-200 mb-4" />
                  <h3 className="font-heading font-semibold text-lg mb-2">{c.title}</h3>
                  <p className="text-white/70 text-base leading-relaxed">{c.desc}</p>
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-3">
            <a href="/?tagOpen=1&period=recent" className="inline-flex items-center gap-2 bg-white text-[hsl(218,60%,30%)] px-5 py-2.5 rounded-md font-medium text-sm hover:bg-white/90 transition-colors">
              Explore rankings <ArrowRight className="h-4 w-4" />
            </a>
            <a href="/?period=recent" className="inline-flex items-center gap-2 border border-white/30 text-white px-5 py-2.5 rounded-md font-medium text-sm hover:bg-white/10 transition-colors">
              Browse research categories
            </a>
            <button onClick={() => window.dispatchEvent(new Event("open-auth-modal"))} className="inline-flex items-center gap-2 border border-white/30 text-white px-5 py-2.5 rounded-md font-medium text-sm hover:bg-white/10 transition-colors">
              <LogIn className="h-4 w-4" /> Create free account
            </button>
          </div>
        </div>
      </section>

      {/* ── RESEARCH CATEGORIES ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="categories-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 md:py-14">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-accent">Research categories</h2>
            <a href="/?tagOpen=1&period=recent" className="text-sm text-accent hover:underline">View all rankings</a>
          </div>
          <p className="text-muted-foreground text-sm md:text-base leading-relaxed mb-6 max-w-3xl">
            Kurate covers {stats?.total_categories || "multiple"} research categories spanning computer science,
            physics, mathematics, economics, biology, and cryptography. Each category maintains its own
            ranked leaderboard, updated as new arXiv preprints are analysed.
          </p>
          {/* Top categories with paper counts */}
          {stats?.top_categories?.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
              {stats.top_categories.map(tc => (
                <a key={tc.id} href={`/?cat=${tc.id}&period=recent`} className="group flex items-center justify-between bg-accent/[0.06] border border-accent/20 rounded-lg px-5 py-3.5 hover:border-accent/40 transition-all">
                  <div>
                    <p className="text-sm font-semibold">{tc.name}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{fmt(tc.count)} ranked preprints</p>
                  </div>
                  <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-accent transition-colors" />
                </a>
              ))}
            </div>
          )}
          {/* All categories grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
            {allCats.map(cat => (
              <a
                key={cat.id}
                href={`/?cat=${cat.id}&period=recent`}
                className="group bg-card border border-border rounded-md px-3.5 py-2.5 hover:shadow-sm hover:border-accent/40 transition-all flex items-center justify-between gap-2"
                data-testid={`category-${cat.id}`}
              >
                <span className="text-sm font-medium truncate">{cat.name}</span>
                <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0 group-hover:text-accent transition-colors" />
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* ── TOP RANKED PREPRINTS ── */}
      <section className="border-b border-border" data-testid="top-papers-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 md:py-14">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-accent mb-3">Top ranked preprints</h2>
          <p className="text-muted-foreground text-sm md:text-base leading-relaxed mb-8 max-w-3xl">
            These are the highest-ranked arXiv preprints currently on the platform. Rankings are produced
            by AI-assisted pairwise comparison across multiple models. Each paper's score reflects how
            consistently it was preferred in head-to-head evaluations within its category.
          </p>
          {/* Actual top papers */}
          {stats?.top_papers?.length > 0 && (
            <div className="bg-card border border-border rounded-lg overflow-hidden mb-8 max-w-4xl">
              <div className="divide-y divide-border">
                {stats.top_papers.slice(0, 5).map((p, i) => (
                  <Link to={`/paper/${p.id}`} key={p.id} className="flex items-center gap-4 px-5 py-3.5 hover:bg-secondary/30 transition-colors" data-testid={`top-paper-${i}`}>
                    <span className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-mono font-semibold ${
                      i === 0 ? "bg-amber-100 text-amber-700 border-2 border-amber-400 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-600"
                      : i === 1 ? "bg-slate-100 text-slate-600 border-2 border-slate-400 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-500"
                      : i === 2 ? "bg-orange-100 text-orange-700 border-2 border-orange-400 dark:bg-orange-900/40 dark:text-orange-300 dark:border-orange-600"
                      : "bg-secondary text-secondary-foreground"
                    }`}>{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{p.title}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {p.primary_category}{p.ts_score ? ` · Score ${p.ts_score.toFixed(0)}` : ""}{p.authors?.length ? ` · ${p.authors.join(", ")}` : ""}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}
          {/* Browse by category */}
          <h3 className="font-heading font-medium text-sm text-muted-foreground uppercase tracking-wider mb-3">Browse top papers by category</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2 max-w-5xl">
            {allCats.map(cat => (
              <a
                key={cat.id}
                href={`/?cat=${cat.id}&period=recent&sort=rank&dir=asc`}
                className="group flex items-center justify-between py-2.5 border-b border-border/60 hover:border-accent/40 transition-colors"
                data-testid={`top-cat-${cat.id}`}
              >
                <span className="text-sm font-medium">{cat.name}</span>
                <span className="text-xs text-accent opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                  View top papers <ChevronRight className="h-3 w-3" />
                </span>
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* ── PLATFORM OVERVIEW ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="metrics-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 md:py-14">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-accent mb-3">Platform overview</h2>
          <p className="text-muted-foreground text-sm md:text-base leading-relaxed mb-8 max-w-3xl">
            Kurate continuously analyses arXiv preprints using multiple AI models. Papers are compared
            in pairwise evaluations and ranked within their research category. The metrics below
            reflect the current scale of the platform.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
            <MetricCard icon={FileText} label="Preprints analysed" value={fmt(stats?.total_papers)} testId="metric-papers" />
            <MetricCard icon={LayoutGrid} label="Research categories" value={stats?.total_categories || "—"} testId="metric-categories" />
            <MetricCard icon={Zap} label="AI comparisons" value={fmt(stats?.total_matches)} testId="metric-matches" />
            <MetricCard icon={Brain} label="AI judges" value={stats?.ai_judges || 3} testId="metric-judges" />
            {stats?.top_categories?.[0] && (
              <MetricCard icon={TrendingUp} label="Most active field" value={stats.top_categories[0].name} sub={`${fmt(stats.top_categories[0].count)} preprints`} testId="metric-active" />
            )}
          </div>
          <div className="flex flex-wrap gap-4">
            <a href="/?tagOpen=1&period=recent" className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              <ArrowRight className="h-4 w-4" /> Explore all rankings
            </a>
            <Link to="/methodology" className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              <BookOpen className="h-4 w-4" /> Read the methodology
            </Link>
          </div>
        </div>
      </section>

      {/* ── HOW KURATE WORKS — #3 larger text ── */}
      <section className="bg-[hsl(218,60%,30%)] text-white border-b" data-testid="how-it-works">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-tight mb-3">How Kurate works</h2>
          <p className="text-white/70 text-base md:text-lg mb-10 max-w-2xl leading-relaxed">
            Kurate processes arXiv preprints daily, applies AI-assisted analysis, and produces
            category-level rankings to help users discover and compare research.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {[
              { icon: FileText, title: "Collect preprints", desc: "Kurate monitors new arXiv submissions and organises them by research category." },
              { icon: Brain, title: "Analyse research signals", desc: "Multiple AI models read paper content and evaluate research characteristics such as novelty, rigour, and potential impact." },
              { icon: Trophy, title: "Rank by category", desc: "Papers are ranked within their research area, producing a leaderboard that is updated as new preprints arrive." },
              { icon: Lightbulb, title: "Support discovery", desc: "Researchers can browse ranked categories, compare papers, and identify work that may be relevant to their interests." },
            ].map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={i} className="bg-white/[0.10] border border-white/15 rounded-lg p-6">
                  <Icon className="h-6 w-6 text-blue-200 mb-4" />
                  <h3 className="font-heading font-semibold text-lg mb-3">{s.title}</h3>
                  <p className="text-white/75 text-base leading-relaxed">{s.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── RANKINGS ARE SIGNALS ── */}
      <section className="bg-accent/[0.07] border-b border-border" data-testid="responsible-discovery">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-3">Rankings are signals, not verdicts</h2>
          <p className="text-muted-foreground text-base md:text-lg mb-8 max-w-3xl leading-relaxed">
            Kurate rankings are designed to support discovery, filtering, and prioritisation.
            They provide an early signal about which preprints may be worth reading — but they
            do not replace peer review, expert judgement, or careful reading of the paper itself.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { icon: Brain, text: "Multiple AI models reduce dependence on any single perspective." },
              { icon: LayoutGrid, text: "Papers are compared within their research category, not across unrelated fields." },
              { icon: Shield, text: "AI models have limitations. Users should read papers directly and apply domain expertise." },
              { icon: BookOpen, text: "The methodology is documented and the ranking approach can evolve over time." },
            ].map((p, i) => {
              const Icon = p.icon;
              return (
                <div key={i} className="flex items-start gap-3 bg-card border border-accent/20 rounded-lg p-5">
                  <Icon className="h-5 w-5 text-accent shrink-0 mt-0.5" />
                  <p className="text-sm font-medium text-foreground/80 leading-relaxed">{p.text}</p>
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-4 mt-8">
            <Link to="/methodology" className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              <BookOpen className="h-4 w-4" /> Read the methodology
            </Link>
            <Link to="/correlation" className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              <BarChart3 className="h-4 w-4" /> Model analysis
            </Link>
            <Link to="/validation" className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline">
              <FlaskConical className="h-4 w-4" /> Validation experiments
            </Link>
          </div>
        </div>
      </section>

      {/* ── FEATURES & ROADMAP — #2 linked items ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="features-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-3">Features and roadmap</h2>
          <p className="text-muted-foreground text-sm mb-10 max-w-2xl">
            Kurate currently focuses on arXiv preprint ranking and discovery.
            Additional research intelligence features are in development.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Current — linked */}
            <div>
              <h3 className="font-heading font-medium text-sm uppercase tracking-wider text-accent mb-4">Available now</h3>
              <div className="space-y-3">
                {[
                  { icon: FileText, title: "arXiv preprint discovery", desc: "Browse and search preprints across multiple research areas.", href: "/?tagOpen=1&period=recent" },
                  { icon: Trophy, title: "Category-based rankings", desc: "Papers ranked within their field by AI-assisted comparison.", href: "/?period=recent" },
                  { icon: BarChart3, title: "Model analysis", desc: "Compare how different AI judges agree and disagree on paper rankings.", to: "/correlation" },
                  { icon: FlaskConical, title: "Validation experiments", desc: "Ground-truth benchmarks that test ranking accuracy against expert judgements.", to: "/validation" },
                  { icon: BookMarked, title: "Bookmarks and reading lists", desc: "Save papers and organise reading lists for later review.", href: "/bookmarks" },
                ].map((f, i) => {
                  const Icon = f.icon;
                  const inner = (
                    <>
                      <Icon className="h-4 w-4 text-accent shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <p className="text-sm font-medium group-hover:text-accent transition-colors">{f.title}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{f.desc}</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </>
                  );
                  return f.to ? (
                    <Link key={i} to={f.to} className="group flex items-start gap-3 bg-card border border-border rounded-lg p-4 hover:border-accent/40 transition-all">
                      {inner}
                    </Link>
                  ) : (
                    <a key={i} href={f.href} className="group flex items-start gap-3 bg-card border border-border rounded-lg p-4 hover:border-accent/40 transition-all">
                      {inner}
                    </a>
                  );
                })}
              </div>
            </div>
            {/* Coming soon */}
            <div>
              <h3 className="font-heading font-medium text-sm uppercase tracking-wider text-muted-foreground mb-4">Coming soon</h3>
              <div className="space-y-3">
                {[
                  { icon: Lightbulb, title: "Semantic search", desc: "Find papers by meaning, not just keywords." },
                  { icon: Layers, title: "Similarity landscape", desc: "Visual maps of how papers relate to each other within a field." },
                  { icon: Sparkles, title: "Novelty and difficulty signals", desc: "Indicators for methodological novelty and technical difficulty." },
                  { icon: TrendingUp, title: "Emerging topic detection", desc: "Identify research themes that are gaining early attention." },
                  { icon: Globe, title: "Broader source coverage", desc: "Extend beyond arXiv to additional preprint and publication sources." },
                ].map((f, i) => {
                  const Icon = f.icon;
                  return (
                    <div key={i} className="flex items-start gap-3 bg-card border border-border/60 rounded-lg p-4 opacity-80">
                      <Icon className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">{f.title}</p>
                        <p className="text-xs text-muted-foreground/80 mt-0.5">{f.desc}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── USE CASES ── */}
      <section className="border-b border-border" data-testid="use-cases">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight mb-8">Who uses Kurate</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { icon: Microscope, title: "Researchers", desc: "Prioritise reading across fast-moving fields and track preprints that may become important." },
              { icon: GraduationCap, title: "Postgraduate students", desc: "Build literature review pathways and understand research clusters without being overwhelmed." },
              { icon: Building2, title: "Universities and research offices", desc: "Monitor strategic fields and identify early signals across disciplines." },
              { icon: Briefcase, title: "Industry R&D teams", desc: "Scan scientific developments relevant to technical strategy and product direction." },
              { icon: Users, title: "Funding bodies", desc: "Track scientific momentum and compare research areas across categories." },
              { icon: BookMarked, title: "Publishers and editors", desc: "Understand emerging topics and detect active research communities." },
            ].map((u, i) => {
              const Icon = u.icon;
              return (
                <div key={i} className="bg-accent/[0.04] border border-accent/15 rounded-lg p-6" data-testid={`usecase-${i}`}>
                  <Icon className="h-6 w-6 text-accent mb-4" />
                  <h3 className="font-heading font-semibold text-base mb-2">{u.title}</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">{u.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="faq-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-8">Frequently asked questions</h2>
          <div className="max-w-3xl">
            <Accordion type="single" collapsible className="space-y-2">
              {[
                { q: "What is Kurate.org?", a: "Kurate.org analyses arXiv preprints and ranks them using AI-assisted comparison across multiple research categories. It is designed to help researchers discover and prioritise papers earlier." },
                { q: "How are papers ranked?", a: "Kurate uses multiple AI models to compare papers within each research category. The resulting rankings reflect AI-estimated research signals such as novelty, rigour, and potential impact." },
                { q: "Does Kurate replace peer review?", a: "No. Kurate rankings are an early discovery signal. They should be used alongside expert judgement, direct reading, and peer review." },
                { q: "Which research areas does Kurate cover?", a: `Kurate currently covers ${stats?.total_categories || "multiple"} research categories across computer science, physics, economics, mathematics, biology, and more.` },
                { q: "Are rankings based on citations?", a: "No. Kurate is designed for early-stage discovery, where citation counts may not yet exist. Rankings are based on AI-assisted analysis of paper content." },
                { q: "Can universities or research offices use Kurate?", a: "Yes. Kurate can support literature scanning, field monitoring, and research strategy discussions across disciplines." },
                { q: "How should I interpret a ranking?", a: "Treat rankings as an early signal for discovery and prioritisation, not as a definitive quality judgement. Always read the paper and apply your own expertise." },
              ].map((f, i) => (
                <AccordionItem key={i} value={`faq-${i}`} className="bg-card border border-border rounded-lg px-5 overflow-hidden" data-testid={`faq-${i}`}>
                  <AccordionTrigger className="text-sm font-medium py-4 hover:no-underline">{f.q}</AccordionTrigger>
                  <AccordionContent className="text-sm text-muted-foreground">{f.a}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </div>
      </section>

      {/* ── FOOTER — #1 white logo text ── */}
      <footer className="bg-[hsl(218,60%,30%)] text-white" data-testid="homepage-footer">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-12 md:py-16">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Trophy className="h-5 w-5 text-blue-300" />
                <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 brightness-0 invert" />
              </div>
              <p className="text-white/60 text-sm leading-relaxed max-w-xs">
                AI-assisted arXiv preprint rankings and research discovery across multiple fields.
              </p>
            </div>
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wider text-white/40 mb-4">Explore</h3>
              <nav className="space-y-2">
                <a href="/?tagOpen=1&period=recent" className="block text-sm text-white/70 hover:text-white transition-colors">All rankings</a>
                <a href="/?period=recent" className="block text-sm text-white/70 hover:text-white transition-colors">Leaderboard</a>
                <Link to="/methodology" className="block text-sm text-white/70 hover:text-white transition-colors">Methodology</Link>
                <Link to="/correlation" className="block text-sm text-white/70 hover:text-white transition-colors">Model Analysis</Link>
                <Link to="/validation" className="block text-sm text-white/70 hover:text-white transition-colors">Validation</Link>
              </nav>
            </div>
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wider text-white/40 mb-4">Follow</h3>
              <nav className="space-y-2">
                <a href="https://x.com/KurateOrg" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-x">X (Twitter)</a>
                <a href="https://www.linkedin.com/company/kurate-org" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-linkedin">LinkedIn</a>
                <a href="https://www.instagram.com/kurate2026/" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-instagram">Instagram</a>
                <a href="https://www.facebook.com/Kurate/" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-facebook">Facebook</a>
              </nav>
            </div>
          </div>
          <div className="mt-10 pt-6 border-t border-white/10 flex flex-wrap items-center gap-4 text-xs text-white/40">
            <span>Kurate.org</span>
            <Link to="/privacy" className="hover:text-white/70 transition-colors">Privacy Policy</Link>
            <Link to="/impressum" className="hover:text-white/70 transition-colors">Impressum</Link>
          </div>
        </div>
      </footer>
    </>
  );
}

function MetricCard({ icon: Icon, label, value, sub, testId }) {
  return (
    <div className="bg-accent/[0.07] border border-accent/20 rounded-lg p-4" data-testid={testId}>
      <Icon className="h-4 w-4 text-accent mb-2" />
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-heading font-semibold mt-1">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}
