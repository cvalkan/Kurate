import { useState, useEffect } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Link } from "react-router-dom";
import {
  Trophy, BarChart3, FlaskConical, BookOpen, ArrowRight,
  Layers, Brain, GitCompare, LayoutGrid, Lightbulb, TrendingUp,
  Search, Clock, Building2, GraduationCap, Users, Briefcase,
  FileText, Globe, Shield, ChevronRight, Activity, Zap,
  Target, Eye, Network, Microscope, BookMarked
} from "lucide-react";
import {
  Accordion, AccordionItem, AccordionTrigger, AccordionContent,
} from "@/components/ui/accordion";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";

const API = process.env.REACT_APP_BACKEND_URL;

/* ─────────── helpers ─────────── */
function fmt(n) {
  if (!n) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}
function timeAgo(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  const now = new Date();
  const hrs = Math.floor((now - d) / 36e5);
  if (hrs < 1) return "Just now";
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "Yesterday" : `${days}d ago`;
}

/* ─────────── category metadata ─────────── */
const CATEGORY_META = {
  "cs.AI": { label: "Artificial Intelligence", desc: "Ranked papers, topic signals, and early discovery context." },
  "cs.LG": { label: "Machine Learning", desc: "Ranked papers, topic signals, and early discovery context." },
  "cs.RO": { label: "Robotics", desc: "Ranked papers, topic signals, and early discovery context." },
  "quant-ph": { label: "Quantum Physics", desc: "Ranked papers, topic signals, and early discovery context." },
  "stat.ML": { label: "Statistics (ML)", desc: "Ranked papers, topic signals, and early discovery context." },
  "econ.GN": { label: "Economics", desc: "Ranked papers, topic signals, and early discovery context." },
  "math.PR": { label: "Mathematics", desc: "Ranked papers, topic signals, and early discovery context." },
  "cs.CL": { label: "All categories", desc: "Ranked papers, topic signals, and early discovery context." },
};
const FEATURED_CATS = ["cs.AI", "cs.LG", "cs.RO", "quant-ph", "stat.ML", "econ.GN", "math.PR", "cs.CL"];
const CAT_COLORS = [
  "border-l-blue-500", "border-l-violet-500", "border-l-emerald-500", "border-l-amber-500",
  "border-l-rose-500", "border-l-cyan-500", "border-l-indigo-500", "border-l-teal-500",
];

/* ─────────── FAQ data ─────────── */
const FAQ = [
  { q: "What is Kurate.org?", a: "Kurate.org is an AI-assisted scientific paper ranking and research intelligence platform for discovering promising preprints earlier." },
  { q: "How are papers ranked?", a: "Kurate uses AI-assisted comparison and category-based evaluation signals to help organise and prioritise scientific preprints." },
  { q: "Does Kurate replace peer review?", a: "No. Kurate provides an early discovery signal and should be used alongside expert judgment, direct reading, replication, and peer review." },
  { q: "Which research areas does Kurate cover?", a: "Kurate supports multiple research categories, including artificial intelligence, machine learning, robotics, quantum physics, statistics, economics, mathematics, and computer science." },
  { q: "Are rankings based on citations?", a: "Kurate is designed for early-stage discovery, where citation counts may not yet exist or may not reflect emerging importance." },
  { q: "Why use AI models to compare papers?", a: "AI-assisted comparison can help organise fast-moving research streams and provide an additional discovery signal across large volumes of preprints." },
  { q: "Can universities or research offices use Kurate?", a: "Yes. Kurate can support horizon scanning, grant preparation, emerging topic monitoring, and research strategy discussions." },
  { q: "How should researchers interpret a ranking?", a: "A ranking should be treated as an early signal for discovery and prioritisation, not as a final judgment of quality or truth." },
];

/* ═══════════════ MAIN COMPONENT ═══════════════ */
export default function HomePage() {
  const [stats, setStats] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [lbLoading, setLbLoading] = useState(true);
  const [showRatingCol, setShowRatingCol] = useState(true);
  const [showGapCol, setShowGapCol] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch leaderboard first (fast, cached) — stats in parallel
    axios.get(`${API}/api/leaderboard`, {
      params: { show_all: true, limit: 10, sort_by: "ts_score", sort_dir: "desc", global_stats: true },
    }).then(r => {
      setLeaderboard((r.data.leaderboard || []).map((e, i) => ({ ...e, rank: i + 1 })));
      if (r.data.show_rating_column !== undefined) setShowRatingCol(r.data.show_rating_column);
      if (r.data.show_gap_column !== undefined) setShowGapCol(r.data.show_gap_column);
      setLbLoading(false);
    }).catch(() => setLbLoading(false));

    axios.get(`${API}/api/homepage/stats`).then(r => {
      setStats(r.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

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
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 md:py-14 relative">
          <div className="max-w-3xl mb-8">
            <h1 className="font-heading text-2xl sm:text-3xl lg:text-4xl font-semibold tracking-tight mb-5 text-foreground whitespace-nowrap" data-testid="hero-heading">
              Scientific papers ranked by AI
            </h1>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed max-w-2xl">
              Kurate.org ranks arXiv preprints by predict scientific impact and other research intelligence signals, helping researchers and institutions identify promising work earlier.
            </p>
            <div className="flex flex-wrap gap-3 mt-7">
              <a href="/?period=recent" className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-5 py-2.5 rounded-md font-medium text-sm hover:bg-accent/90 transition-colors" data-testid="hero-explore-btn">
                Explore rankings <ArrowRight className="h-4 w-4" />
              </a>
              <Link to="/methodology" className="inline-flex items-center gap-2 border border-border bg-card text-foreground px-5 py-2.5 rounded-md font-medium text-sm hover:bg-secondary transition-colors" data-testid="hero-methodology-btn">
                <BookOpen className="h-4 w-4" /> Methodology
              </Link>
            </div>
          </div>

          {/* Category chips — colored left border, single row */}
          <div className="grid grid-cols-4 sm:grid-cols-8 gap-2" data-testid="hero-cards">
            {FEATURED_CATS.map((catId, i) => {
              const meta = CATEGORY_META[catId];
              const href = catId === "cs.CL" ? "/?show_all=true" : `/?cat=${catId}&period=recent`;
              return (
                <a
                  key={catId}
                  href={href}
                  className={`bg-card border border-border border-l-[3px] ${CAT_COLORS[i]} rounded-md px-3 py-2 hover:shadow-md hover:border-accent/40 transition-all text-center`}
                  data-testid={`hero-cat-${catId}`}
                >
                  <span className="font-heading font-medium text-xs">{meta.label}</span>
                </a>
              );
            })}
          </div>

          {/* Full leaderboard table — All Time top ranked */}
          <div className="mt-6" data-testid="hero-ranking-preview">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">All-time top ranked papers</span>
              <a href="/?period=recent" className="text-xs text-accent hover:underline">View full leaderboard</a>
            </div>
            <TooltipProvider delayDuration={200}>
              <LeaderboardTable
                leaderboard={leaderboard}
                loading={lbLoading}
                showCatCol={true}
                hasSelectedTags={false}
                globalStats={true}
                debouncedKeyword=""
                keyword=""
                onLoadMore={null}
                hasMore={false}
                loadingMore={false}
                sortKey="rank"
                sortDir="asc"
                onSort={() => {}}
                showRatingCol={showRatingCol}
                showGapCol={showGapCol}
                scoringMethod="ts"
              />
            </TooltipProvider>
          </div>
        </div>
      </section>

      {/* ── LIVE METRICS ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="metrics-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 md:py-14">
          <h2 className="font-heading text-base md:text-lg font-medium text-muted-foreground mb-6 uppercase tracking-wider">Live platform metrics</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <MetricCard icon={FileText} label="Papers ranked" value={fmt(stats?.total_papers)} testId="metric-papers" />
            <MetricCard icon={LayoutGrid} label="Active categories" value={stats?.total_categories || "—"} testId="metric-categories" />
            <MetricCard icon={Activity} label="Recent papers" value={fmt(stats?.recent_papers)} sub="Last 7 days" testId="metric-recent" />
            <MetricCard icon={Zap} label="AI comparisons" value={fmt(stats?.total_matches)} testId="metric-matches" />
            <MetricCard icon={Brain} label="AI judges" value={stats?.ai_judges || 3} testId="metric-judges" />
            {stats?.top_categories?.[0] && (
              <MetricCard icon={TrendingUp} label="Most active" value={stats.top_categories[0].name} sub={`${fmt(stats.top_categories[0].count)} papers`} testId="metric-active" />
            )}
            {stats?.latest_update && (
              <MetricCard icon={Clock} label="Latest update" value={timeAgo(stats.latest_update)} testId="metric-update" />
            )}
            <a href="/correlation" className="bg-card border border-border rounded-lg p-4 hover:shadow-md hover:border-accent/40 transition-all" data-testid="metric-agreement">
              <BarChart3 className="h-4 w-4 text-accent mb-2" />
              <p className="text-xs text-muted-foreground">Model agreement</p>
              <p className="text-sm font-medium mt-1">View analysis</p>
            </a>
            <a href="/validation" className="bg-card border border-border rounded-lg p-4 hover:shadow-md hover:border-accent/40 transition-all" data-testid="metric-validation">
              <FlaskConical className="h-4 w-4 text-accent mb-2" />
              <p className="text-xs text-muted-foreground">Validation signal</p>
              <p className="text-sm font-medium mt-1">View report</p>
            </a>
          </div>
        </div>
      </section>

      {/* ── POSITIONING STRIP ── */}
      <section className="bg-accent text-accent-foreground" data-testid="positioning-strip">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-center sm:text-left">
            {[
              "AI-assisted paper rankings",
              "Category-based scientific discovery",
              "Research intelligence from preprints",
              "Built for fast-moving fields",
            ].map((t, i) => (
              <p key={i} className="text-sm font-medium opacity-95">{t}</p>
            ))}
          </div>
        </div>
      </section>

      {/* ── WHAT KURATE DOES ── */}
      <section className="border-b border-border" data-testid="what-kurate-does">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-4">What Kurate does</h2>
          <div className="bg-accent/[0.06] border border-accent/20 rounded-lg p-6 md:p-8 max-w-4xl">
            <p className="text-muted-foreground text-sm md:text-base leading-relaxed">
              Kurate transforms the daily flow of scientific preprints into structured research discovery.
              Instead of relying only on upload order, keyword search, social attention, or late citation counts,
              Kurate provides an early ranking layer that helps users identify papers that may be novel,
              methodologically interesting, practically significant, theoretically important, or relevant
              to emerging research directions.
            </p>
          </div>
        </div>
      </section>

      {/* ── WHY DISCOVERY NEEDS RANKING ── */}
      <section className="bg-secondary/30 border-b border-border" data-testid="why-ranking">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-3">
            The research literature is growing faster than traditional discovery tools
          </h2>
          <p className="text-muted-foreground text-sm md:text-base mb-8 max-w-2xl">
            Preprint servers release many papers daily. Researchers cannot manually evaluate everything.
            Keyword search is useful but limited, citation counts arrive late, and social media attention is noisy.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <InfoCard icon={Layers} title="Information overload" desc="Researchers face more papers than they can read, compare, or prioritise." />
            <InfoCard icon={Clock} title="Late citation signals" desc="Citation counts often mature long after a paper first becomes strategically important." />
            <InfoCard icon={Globe} title="Fragmented discovery" desc="Important work may be hidden across categories, fields, and fast-moving subdomains." />
            <InfoCard icon={Eye} title="Early ideas are hard to see" desc="Emerging methods and clusters need structured discovery signals before they become obvious." />
          </div>
        </div>
      </section>

      {/* ── HOW KURATE WORKS ── */}
      <section className="bg-[hsl(222,47%,11%)] text-white border-b" data-testid="how-it-works">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-8">How Kurate works</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {[
              { icon: FileText, title: "Preprints", desc: "Kurate monitors new scientific preprints and organises them by research category." },
              { icon: Brain, title: "AI evaluation", desc: "Kurate analyses available paper information, including titles, abstracts, metadata, and research signals." },
              { icon: GitCompare, title: "Model comparison", desc: "Kurate uses AI-assisted comparison to help evaluate papers within categories." },
              { icon: Trophy, title: "Category ranking", desc: "Papers are ranked within relevant research areas, making each category easier to scan." },
              { icon: Lightbulb, title: "Research intelligence", desc: "The ranking layer can support trend detection, topic monitoring, semantic discovery, and institutional analysis." },
            ].map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={i} className="bg-white/[0.06] border border-white/10 rounded-lg p-5">
                  <Icon className="h-5 w-5 text-blue-300 mb-3" />
                  <h3 className="font-heading font-medium text-sm mb-2">{s.title}</h3>
                  <p className="text-white/70 text-xs leading-relaxed">{s.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── RANKING IS A SIGNAL ── */}
      <section className="border-b border-border" data-testid="ranking-signal">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-3">Ranking is a signal, not a verdict</h2>
          <p className="text-muted-foreground text-sm md:text-base mb-8 max-w-3xl">
            Kurate rankings provide an early discovery signal — not peer review. They help users decide what to read,
            compare, or track while preserving the role of expert judgment, replication, and domain expertise.
            AI models may have biases and limitations; the methodology should remain transparent and continuously improved.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <InfoCard icon={Brain} title="Multi-model evaluation" desc="Multiple AI perspectives reduce dependence on a single model judgement." />
            <InfoCard icon={LayoutGrid} title="Category-specific comparison" desc="Papers are evaluated within relevant research areas and leaderboards." />
            <InfoCard icon={Shield} title="Read the papers" desc="Users should read papers directly and apply domain expertise alongside rankings." />
            <InfoCard icon={TrendingUp} title="Continuous improvement" desc="The ranking layer evolves as methods, categories, and evaluation principles improve." />
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/methodology" className="inline-flex items-center gap-2 text-sm text-accent hover:underline" data-testid="link-methodology">
              <BookOpen className="h-4 w-4" /> Methodology
            </Link>
            <Link to="/correlation" className="inline-flex items-center gap-2 text-sm text-accent hover:underline" data-testid="link-model-analysis">
              <BarChart3 className="h-4 w-4" /> Model Analysis
            </Link>
            <Link to="/validation" className="inline-flex items-center gap-2 text-sm text-accent hover:underline" data-testid="link-validation">
              <FlaskConical className="h-4 w-4" /> Validation
            </Link>
          </div>
        </div>
      </section>

      {/* ── RESEARCH INTELLIGENCE ── */}
      <section className="bg-[hsl(222,47%,11%)] text-white border-b" data-testid="research-intelligence">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-3">
            From paper rankings to research intelligence
          </h2>
          <p className="text-white/70 text-sm md:text-base mb-8 max-w-3xl">
            Kurate is not only a leaderboard. It can support emerging topic detection, research trend monitoring,
            literature scanning, semantic discovery paths, institutional strategy, grant intelligence, and early
            identification of active research clusters.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-10">
            {[
              { icon: Search, title: "Emerging topic detection", desc: "Identify themes that are appearing repeatedly and gaining early attention." },
              { icon: Network, title: "Semantic discovery paths", desc: "Connect closest papers, neighbouring clusters, bridge papers, and guided reading paths." },
              { icon: Target, title: "Grant and funding intelligence", desc: "Recognise promising methods, active authors, and early topic clusters." },
              { icon: TrendingUp, title: "Rising topic monitoring", desc: "Track which research areas are becoming more active over time." },
              { icon: LayoutGrid, title: "Category-level intelligence", desc: "See field-level signals from paper-level rankings." },
            ].map((c, i) => {
              const Icon = c.icon;
              return (
                <div key={i} className="bg-white/[0.06] border border-white/10 rounded-lg p-5">
                  <Icon className="h-5 w-5 text-blue-300 mb-3" />
                  <h3 className="font-heading font-medium text-sm mb-2">{c.title}</h3>
                  <p className="text-white/60 text-xs leading-relaxed">{c.desc}</p>
                </div>
              );
            })}
          </div>

          {/* Research intelligence snapshot */}
          <div className="bg-white/[0.04] border border-white/10 rounded-lg p-6">
            <h3 className="font-heading font-medium text-sm mb-4 text-white/80 uppercase tracking-wider">Research intelligence snapshot</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <p className="text-xs text-white/50 mb-2">Rising topics</p>
                <div className="flex flex-wrap gap-2">
                  {["AI evaluation", "Quantum optimisation", "Robotics agents", "LLM reasoning"].map(t => (
                    <span key={t} className="bg-blue-500/20 text-blue-200 text-xs px-2.5 py-1 rounded-full">{t}</span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-white/50 mb-2">Reading path</p>
                <div className="space-y-1.5">
                  {["General overview", "Core method paper", "Bridge paper", "Specialised extension"].map((s, i) => (
                    <div key={s} className="flex items-center gap-2 text-xs text-white/70">
                      <span className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center text-[10px] font-mono">{i + 1}</span>
                      {s}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── INSTITUTIONAL INTELLIGENCE ── */}
      <section className="border-b border-border" data-testid="institutional-intelligence">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-3">
            Research intelligence for institutions
          </h2>
          <p className="text-muted-foreground text-sm md:text-base mb-8 max-w-3xl">
            Institutions need structured visibility into what is emerging, where research attention is moving,
            and which areas may become strategically important. Kurate can support research offices, academic leaders,
            innovation teams, and grant development teams by turning paper-level discovery into field-level intelligence.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              "Horizon scanning", "Grant preparation", "Capability analysis", "Research cluster identification",
              "Strategic planning", "Industry collaboration", "Emerging field monitoring", "Research trend reporting",
            ].map(label => (
              <div key={label} className="bg-accent/[0.06] border border-accent/15 rounded-lg px-4 py-3 text-center">
                <p className="text-xs font-medium text-foreground">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── USE CASES ── */}
      <section className="border-b border-border" data-testid="use-cases">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-8">Who uses Kurate</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[
              { icon: Microscope, title: "Researchers", desc: "Prioritise reading, track emerging topics, and discover papers that may become important before citation signals mature." },
              { icon: GraduationCap, title: "Postgraduate students", desc: "Build literature review pathways and understand research clusters without being overwhelmed by paper volume." },
              { icon: Building2, title: "Universities and research offices", desc: "Monitor strategic fields, support grant planning, and identify early signals across disciplines." },
              { icon: Briefcase, title: "Industry R&D teams", desc: "Scan fast-moving scientific developments relevant to technical strategy, innovation, and product direction." },
              { icon: Users, title: "Funding bodies and policy teams", desc: "Track scientific momentum, compare research areas, and identify early signals before citation metrics mature." },
              { icon: BookMarked, title: "Publishers and editors", desc: "Understand emerging topics, detect active research communities, and monitor fast-moving domains." },
            ].map((u, i) => {
              const Icon = u.icon;
              return (
                <div key={i} className="bg-card border border-border rounded-lg p-5 hover:shadow-sm transition-all" data-testid={`usecase-${i}`}>
                  <Icon className="h-5 w-5 text-accent mb-3" />
                  <h3 className="font-heading font-medium text-sm mb-2">{u.title}</h3>
                  <p className="text-muted-foreground text-xs leading-relaxed">{u.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="border-b border-border" data-testid="faq-section">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-medium tracking-tight mb-8">Frequently asked questions</h2>
          <div className="max-w-3xl">
            <Accordion type="single" collapsible className="space-y-2">
              {FAQ.map((f, i) => (
                <AccordionItem key={i} value={`faq-${i}`} className="bg-card border border-border rounded-lg px-5 overflow-hidden" data-testid={`faq-${i}`}>
                  <AccordionTrigger className="text-sm font-medium py-4 hover:no-underline">{f.q}</AccordionTrigger>
                  <AccordionContent className="text-sm text-muted-foreground">{f.a}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="bg-[hsl(222,47%,11%)] text-white" data-testid="homepage-footer">
        <div className="container mx-auto px-4 md:px-6 max-w-7xl py-12 md:py-16">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Brand */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Trophy className="h-5 w-5 text-blue-300" />
                <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 invert" />
              </div>
              <p className="text-white/60 text-sm leading-relaxed max-w-xs">
                AI-assisted scientific paper rankings and research intelligence for fast-moving fields.
              </p>
            </div>

            {/* Pages */}
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wider text-white/40 mb-4">Explore</h3>
              <nav className="space-y-2">
                <a href="/?period=recent" className="block text-sm text-white/70 hover:text-white transition-colors">Leaderboard</a>
                <Link to="/methodology" className="block text-sm text-white/70 hover:text-white transition-colors">Methodology</Link>
                <Link to="/correlation" className="block text-sm text-white/70 hover:text-white transition-colors">Model Analysis</Link>
                <Link to="/validation" className="block text-sm text-white/70 hover:text-white transition-colors">Validation</Link>
              </nav>
            </div>

            {/* Social */}
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wider text-white/40 mb-4">Follow</h3>
              <nav className="space-y-2">
                <a href="https://x.com/KurateOrg" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-x">X (Twitter)</a>
                <a href="https://www.linkedin.com/company/kurate-org" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-linkedin">LinkedIn</a>
                <a href="https://github.com/cvalkan/PaperSumo/" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors" data-testid="footer-github">GitHub</a>
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

/* ─────────── sub-components ─────────── */
function MetricCard({ icon: Icon, label, value, sub, testId }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4" data-testid={testId}>
      <Icon className="h-4 w-4 text-accent mb-2" />
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-heading font-semibold mt-1">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

function InfoCard({ icon: Icon, title, desc }) {
  return (
    <div className="bg-card border border-border rounded-lg p-5">
      <Icon className="h-5 w-5 text-accent mb-3" />
      <h3 className="font-heading font-medium text-sm mb-2">{title}</h3>
      <p className="text-muted-foreground text-xs leading-relaxed">{desc}</p>
    </div>
  );
}
