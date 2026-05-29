import { useState, useEffect, useCallback } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Link, useNavigate } from "react-router-dom";
import {
  Trophy, BarChart3, BookOpen, ArrowRight, LogIn,
  Brain, LayoutGrid, Lightbulb, TrendingUp, Search,
  Building2, GraduationCap, Briefcase, Shield,
  FileText, Globe, ChevronRight, Zap, Sparkles, FlaskConical,
  BookMarked, ExternalLink,
} from "lucide-react";
import {
  Accordion, AccordionItem, AccordionTrigger, AccordionContent,
} from "@/components/ui/accordion";

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) {
  if (!n) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

const CHIPS = [
  { label: "Artificial Intelligence", cat: "cs.AI" },
  { label: "Machine Learning", cat: "cs.LG" },
  { label: "Robotics", cat: "cs.RO" },
  { label: "Quantum Physics", cat: "quant-ph" },
  { label: "Economics", cat: "econ.GN" },
  { label: "Cryptography", cat: "cs.CR" },
  { label: "Materials Science", cat: "cond-mat.mtrl-sci" },
  { label: "Cosmology", cat: "astro-ph.CO" },
];

export default function HomePage() {
  const [stats, setStats] = useState(null);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    axios.get(`${API}/api/homepage/stats`).then(r => setStats(r.data)).catch(() => {});
  }, []);

  const handleSearch = useCallback((e) => {
    e.preventDefault();
    const q = query.trim();
    if (q) {
      navigate(`/?q=${encodeURIComponent(q)}&tagOpen=1&period=recent`);
    } else {
      navigate("/?tagOpen=1&period=recent");
    }
  }, [query, navigate]);

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

      {/* ════════ HERO — full viewport, app-like ════════ */}
      <section className="relative min-h-[calc(90vh-3.5rem)] flex flex-col items-center justify-center px-4" data-testid="hero-section">
        {/* Subtle dot grid background */}
        <div className="absolute inset-0 opacity-[0.03]" style={{
          backgroundImage: "radial-gradient(circle, hsl(217,60%,50%) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }} />

        <div className="relative w-full max-w-3xl mx-auto text-center">
          {/* Headline */}
          <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight text-foreground mb-5 leading-[1.1]" data-testid="hero-heading">
            Discover the most significant research<br className="hidden sm:block" /> before everyone else
          </h1>

          {/* Subtitle */}
          <p className="text-muted-foreground text-base md:text-lg leading-relaxed max-w-2xl mx-auto mb-10">
            Kurate helps researchers explore preprints and academic papers through ranked
            signals, topic intelligence, and field-level context.
          </p>

          {/* Search bar */}
          <form onSubmit={handleSearch} className="relative max-w-2xl mx-auto mb-6" data-testid="search-form">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search papers, topics, or research areas..."
              className="w-full h-14 pl-12 pr-36 rounded-xl border border-border bg-card text-foreground text-base placeholder:text-muted-foreground/60 shadow-sm focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent transition-all"
              data-testid="search-input"
            />
            <button type="submit" className="absolute right-2 top-1/2 -translate-y-1/2 bg-accent text-accent-foreground px-5 py-2.5 rounded-lg font-medium text-sm hover:bg-accent/90 transition-colors" data-testid="search-btn">
              Explore Research
            </button>
          </form>

          {/* Category chips */}
          <div className="flex flex-wrap items-center justify-center gap-2 mb-8" data-testid="category-chips">
            {CHIPS.map(c => (
              <a
                key={c.cat}
                href={`/?cat=${c.cat}&period=recent`}
                className="px-3 py-1.5 text-xs font-medium text-muted-foreground border border-border rounded-full hover:border-accent/50 hover:text-accent transition-all bg-card"
                data-testid={`chip-${c.cat}`}
              >
                {c.label}
              </a>
            ))}
            <a href="/?tagOpen=1&period=recent" className="px-3 py-1.5 text-xs font-medium text-accent border border-accent/30 rounded-full hover:bg-accent/5 transition-all" data-testid="chip-all">
              All categories
            </a>
          </div>

          {/* Secondary links */}
          <div className="flex items-center justify-center gap-5 text-sm">
            <a href="/?period=recent" className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5" data-testid="link-leaderboards">
              <Trophy className="h-4 w-4" /> View Leaderboards
            </a>
            <a href="/?tagOpen=1&period=recent" className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5" data-testid="link-categories">
              <LayoutGrid className="h-4 w-4" /> Browse Categories
            </a>
            <Link to="/methodology" className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5" data-testid="link-methodology">
              <BookOpen className="h-4 w-4" /> Methodology
            </Link>
          </div>

          {/* Trust line */}
          <p className="text-xs text-muted-foreground/60 mt-10">
            Built for research discovery. Not a replacement for peer review.
          </p>
        </div>
      </section>

      {/* ════════ PANEL 2 — What Kurate does ════════ */}
      <section className="border-t border-border bg-secondary/20" data-testid="what-kurate-does">
        <div className="container mx-auto px-4 md:px-6 max-w-6xl py-16 md:py-24">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-center mb-12">What Kurate does</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              { icon: Trophy, title: "Rank emerging research", desc: "Papers are evaluated through AI-assisted pairwise comparison and ranked within their category, surfacing work that may be significant." },
              { icon: Sparkles, title: "Show signals beyond citations", desc: "Kurate evaluates novelty, methodological strength, relevance, and potential impact — signals that citations take years to reveal." },
              { icon: Lightbulb, title: "Help users understand significance", desc: "Ranked leaderboards, model analysis, and validation experiments give researchers structured context for deciding what to read." },
            ].map((c, i) => {
              const Icon = c.icon;
              return (
                <div key={i} className="text-center">
                  <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent/10 mb-5">
                    <Icon className="h-6 w-6 text-accent" />
                  </div>
                  <h3 className="font-heading font-semibold text-lg mb-2">{c.title}</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">{c.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ════════ PANEL 3 — Research signals ════════ */}
      <section className="border-t border-border" data-testid="research-signals">
        <div className="container mx-auto px-4 md:px-6 max-w-6xl py-16 md:py-24">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-center mb-4">Research signals</h2>
          <p className="text-muted-foreground text-sm md:text-base text-center mb-12 max-w-2xl mx-auto">
            Kurate surfaces structured signals for each paper and category, going beyond simple metadata.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {[
              { icon: Sparkles, label: "Novelty" },
              { icon: Brain, label: "Method strength" },
              { icon: TrendingUp, label: "Field momentum" },
              { icon: Globe, label: "Relevance" },
              { icon: BarChart3, label: "Ranking movement" },
              { icon: FileText, label: "Topic-level context" },
              { icon: Zap, label: "Attention patterns" },
              { icon: ExternalLink, label: "Paper visibility" },
            ].map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={i} className="bg-accent/[0.05] border border-accent/15 rounded-lg px-4 py-4 flex items-center gap-3">
                  <Icon className="h-4 w-4 text-accent shrink-0" />
                  <span className="text-sm font-medium">{s.label}</span>
                </div>
              );
            })}
          </div>
          {/* Live platform numbers */}
          <div className="flex flex-wrap items-center justify-center gap-8 mt-12 pt-8 border-t border-border">
            <Stat label="Preprints analysed" value={fmt(stats?.total_papers)} />
            <Stat label="Research categories" value={stats?.total_categories || "—"} />
            <Stat label="AI comparisons" value={fmt(stats?.total_matches)} />
            <Stat label="AI judges" value={stats?.ai_judges || 3} />
          </div>
        </div>
      </section>

      {/* ════════ PANEL 4 — Leaderboards & categories ════════ */}
      <section className="border-t border-border bg-secondary/20" data-testid="leaderboards-categories">
        <div className="container mx-auto px-4 md:px-6 max-w-6xl py-16 md:py-24">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-center mb-4">Leaderboards and categories</h2>
          <p className="text-muted-foreground text-sm md:text-base text-center mb-10 max-w-2xl mx-auto">
            Rankings are organised by research area. Explore any category to see which preprints are currently ranked highest.
          </p>
          {/* Top categories with counts */}
          {stats?.top_categories?.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-8 max-w-4xl mx-auto">
              {stats.top_categories.map(tc => (
                <a key={tc.id} href={`/?cat=${tc.id}&period=recent`} className="group flex items-center justify-between bg-card border border-border rounded-lg px-5 py-3.5 hover:border-accent/40 hover:shadow-sm transition-all">
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
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2 max-w-5xl mx-auto">
            {allCats.map(cat => (
              <a key={cat.id} href={`/?cat=${cat.id}&period=recent`} className="group bg-card border border-border rounded-md px-3 py-2 text-sm font-medium hover:border-accent/40 transition-all flex items-center justify-between gap-2" data-testid={`cat-${cat.id}`}>
                <span className="truncate">{cat.name}</span>
                <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0 group-hover:text-accent transition-colors" />
              </a>
            ))}
          </div>
          <div className="text-center mt-8">
            <a href="/?tagOpen=1&period=recent" className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-5 py-2.5 rounded-lg font-medium text-sm hover:bg-accent/90 transition-colors" data-testid="all-rankings-btn">
              View all rankings <ArrowRight className="h-4 w-4" />
            </a>
          </div>
        </div>
      </section>

      {/* ════════ PANEL 5 — For whom ════════ */}
      <section className="border-t border-border" data-testid="for-whom">
        <div className="container mx-auto px-4 md:px-6 max-w-6xl py-16 md:py-24">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-center mb-12">For researchers, readers, and institutions</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              { icon: GraduationCap, title: "For researchers", desc: "Track field visibility, discover newly ranked preprints, and understand how your area of research is evolving." },
              { icon: BookMarked, title: "For readers", desc: "Find important papers faster by browsing ranked leaderboards instead of scrolling through chronological feeds." },
              { icon: Building2, title: "For institutions and labs", desc: "Understand emerging research areas, monitor topic movement, and support strategic research planning across disciplines." },
            ].map((c, i) => {
              const Icon = c.icon;
              return (
                <div key={i} className="bg-accent/[0.04] border border-accent/15 rounded-lg p-6" data-testid={`audience-${i}`}>
                  <Icon className="h-6 w-6 text-accent mb-4" />
                  <h3 className="font-heading font-semibold text-base mb-2">{c.title}</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">{c.desc}</p>
                </div>
              );
            })}
          </div>
          <div className="text-center mt-10">
            <button onClick={() => window.dispatchEvent(new Event("open-auth-modal"))} className="inline-flex items-center gap-2 bg-accent text-accent-foreground px-6 py-3 rounded-lg font-medium text-sm hover:bg-accent/90 transition-colors" data-testid="signup-cta">
              <LogIn className="h-4 w-4" /> Create free account
            </button>
          </div>
        </div>
      </section>

      {/* ════════ PANEL 6 — Not a replacement ════════ */}
      <section className="border-t border-border bg-accent/[0.05]" data-testid="responsible-discovery">
        <div className="container mx-auto px-4 md:px-6 max-w-3xl py-14 md:py-20 text-center">
          <Shield className="h-8 w-8 text-accent mx-auto mb-5" />
          <h2 className="font-heading text-xl md:text-2xl font-semibold tracking-tight mb-4">Not a replacement for peer review</h2>
          <p className="text-muted-foreground text-base leading-relaxed">
            Kurate does not replace peer review or expert reading. It provides discovery signals
            that help users decide which papers deserve closer attention. Rankings are early indicators
            — always read the paper and apply your own expertise.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4 mt-8">
            <Link to="/methodology" className="text-sm font-medium text-accent hover:underline flex items-center gap-1.5">
              <BookOpen className="h-4 w-4" /> Methodology
            </Link>
            <Link to="/correlation" className="text-sm font-medium text-accent hover:underline flex items-center gap-1.5">
              <BarChart3 className="h-4 w-4" /> Model analysis
            </Link>
            <Link to="/validation" className="text-sm font-medium text-accent hover:underline flex items-center gap-1.5">
              <FlaskConical className="h-4 w-4" /> Validation
            </Link>
          </div>
        </div>
      </section>

      {/* ════════ PANEL 7 — FAQ ════════ */}
      <section className="border-t border-border" data-testid="faq-section">
        <div className="container mx-auto px-4 md:px-6 max-w-3xl py-14 md:py-20">
          <h2 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight text-center mb-10">Frequently asked questions</h2>
          <Accordion type="single" collapsible className="space-y-2">
            {[
              { q: "What is Kurate.org?", a: "Kurate.org analyses arXiv preprints and ranks them using AI-assisted comparison across multiple research categories. It is designed to help researchers discover and prioritise papers earlier." },
              { q: "How are papers ranked?", a: "Kurate uses multiple AI models to compare papers within each research category. The resulting rankings reflect AI-estimated research signals such as novelty, rigour, and potential impact." },
              { q: "Does Kurate replace peer review?", a: "No. Kurate rankings are an early discovery signal. They should be used alongside expert judgement, direct reading, and peer review." },
              { q: "Which research areas does Kurate cover?", a: `Kurate currently covers ${stats?.total_categories || "multiple"} research categories across computer science, physics, economics, mathematics, biology, and more.` },
              { q: "Are rankings based on citations?", a: "No. Kurate is designed for early-stage discovery, where citation counts may not yet exist. Rankings are based on AI-assisted analysis of paper content." },
              { q: "Can universities use Kurate?", a: "Yes. Kurate can support literature scanning, field monitoring, and research strategy discussions across disciplines." },
              { q: "How should I interpret a ranking?", a: "Treat rankings as an early signal for discovery and prioritisation, not as a definitive quality judgement. Always read the paper and apply your own expertise." },
            ].map((f, i, arr) => {
              const t = i / Math.max(arr.length - 1, 1);
              const bg = `hsl(217, ${60 + t * 15}%, ${97 - t * 12}%)`;
              const white = (97 - t * 12) < 88;
              return (
                <AccordionItem key={i} value={`faq-${i}`} className="border-0 rounded-lg px-5 overflow-hidden" style={{ backgroundColor: bg }} data-testid={`faq-${i}`}>
                  <AccordionTrigger className="text-sm font-medium py-4 hover:no-underline text-foreground">{f.q}</AccordionTrigger>
                  <AccordionContent className="text-sm text-foreground/80">{f.a}</AccordionContent>
                </AccordionItem>
              );
            })}
          </Accordion>
        </div>
      </section>

      {/* ════════ FOOTER ════════ */}
      <footer className="bg-[hsl(218,60%,30%)] text-white" data-testid="homepage-footer">
        <div className="container mx-auto px-4 md:px-6 max-w-6xl py-12 md:py-16">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Trophy className="h-5 w-5 text-blue-300" />
                <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 brightness-0 invert" />
              </div>
              <p className="text-white/60 text-sm leading-relaxed max-w-xs">
                Research discovery and ranking signals for preprints and academic papers.
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
                <a href="https://x.com/KurateOrg" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors">X (Twitter)</a>
                <a href="https://www.linkedin.com/company/kurate-org" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors">LinkedIn</a>
                <a href="https://www.instagram.com/kurate2026/" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors">Instagram</a>
                <a href="https://www.facebook.com/Kurate/" target="_blank" rel="noopener noreferrer" className="block text-sm text-white/70 hover:text-white transition-colors">Facebook</a>
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

/* ─── Sub-components ─── */
function Stat({ label, value }) {
  return (
    <div className="text-center">
      <p className="text-2xl font-heading font-semibold text-foreground">{value}</p>
      <p className="text-xs text-muted-foreground mt-1">{label}</p>
    </div>
  );
}
