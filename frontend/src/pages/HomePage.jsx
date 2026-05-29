import { useState, useEffect, useCallback } from "react";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Link, useNavigate } from "react-router-dom";
import {
  Trophy, BarChart3, BookOpen, ArrowRight, Search,
  Brain, ChevronRight, Activity, CheckCircle2,
  ExternalLink, Shield, Users, Layers, Zap, Globe,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) {
  if (!n && n !== 0) return "\u2014";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

function daysSince(iso) {
  if (!iso) return null;
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  return d === 0 ? "today" : `${d}d ago`;
}

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
    if (q) navigate(`/?q=${encodeURIComponent(q)}&tagOpen=1&period=recent`);
    else navigate("/?tagOpen=1&period=recent");
  }, [query, navigate]);

  const topPapers = stats?.top_papers || [];
  const topCats = stats?.top_categories || [];

  return (
    <>
      <Helmet>
        <title>Kurate.org — AI-Powered Scientific Paper Rankings</title>
        <meta name="description" content="Kurate.org ranks scientific preprints using AI-assisted comparison, category-based leaderboards, and research intelligence signals." />
        <link rel="canonical" href="https://kurate.org" />
        <meta property="og:title" content="Kurate.org — AI-Powered Scientific Paper Rankings" />
        <meta property="og:description" content="Ranks scientific preprints using AI-assisted comparison and research intelligence signals." />
        <meta property="og:image" content="https://kurate.org/kurate-logo.png" />
        <meta property="og:url" content="https://kurate.org" />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:title" content="Kurate.org — AI-Powered Scientific Paper Rankings" />
        <meta name="twitter:description" content="Ranks scientific preprints using AI-assisted comparison and research intelligence signals." />
      </Helmet>

      <div className="min-h-screen bg-white" style={{ fontFamily: "'IBM Plex Sans', system-ui, sans-serif" }}>

        {/* ═══════ HERO ═══════ */}
        <section className="pt-16 sm:pt-24 pb-12 sm:pb-16" data-testid="hero-section">
          <div className="max-w-3xl mx-auto px-4 sm:px-6 text-center">
            <h1
              className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-900 leading-tight mb-6"
              style={{ fontFamily: "'Chivo', 'IBM Plex Sans', system-ui, sans-serif" }}
              data-testid="hero-heading"
            >
              AI-powered scientific paper rankings
            </h1>
            <p className="text-base sm:text-lg text-slate-600 leading-relaxed max-w-2xl mx-auto mb-10">
              Kurate.org ranks scientific preprints using AI-assisted comparison, category-based
              leaderboards, and research intelligence signals — helping researchers and
              institutions identify promising work earlier.
            </p>
            <div className="flex items-center justify-center gap-4 mb-10">
              <a
                href="/?tagOpen=1&period=recent"
                className="bg-[#1E3A8A] text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-blue-900 transition-colors inline-flex items-center gap-2"
                data-testid="cta-explore"
              >
                Explore rankings <ArrowRight className="h-4 w-4" />
              </a>
              <Link
                to="/methodology"
                className="border border-slate-300 text-slate-700 px-6 py-2.5 rounded-md text-sm font-medium hover:bg-slate-50 transition-colors"
                data-testid="cta-methodology"
              >
                Methodology
              </Link>
            </div>

            {/* Search bar */}
            <form onSubmit={handleSearch} className="relative max-w-xl mx-auto" data-testid="search-form">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
              <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search ranked papers by topic..."
                className="w-full h-12 pl-11 pr-4 rounded-lg border border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A]/40 transition-all"
                data-testid="search-input"
              />
            </form>
          </div>
        </section>

        {/* ═══════ TRUST BADGES ═══════ */}
        <div className="border-y border-slate-100 py-6" data-testid="trust-badges">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-wrap items-center justify-center gap-x-8 gap-y-3">
            {[
              { icon: Trophy, label: "AI-assisted paper rankings" },
              { icon: Layers, label: "Category-based scientific discovery" },
              { icon: Brain, label: "Research intelligence from preprints" },
              { icon: Zap, label: "Built for fast-moving fields" },
            ].map(b => (
              <span key={b.label} className="flex items-center gap-2 text-xs tracking-[0.1em] uppercase text-slate-500" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
                <b.icon className="h-3.5 w-3.5 text-slate-400" /> {b.label}
              </span>
            ))}
          </div>
        </div>

        {/* ═══════ TOP RANKED PAPERS ═══════ */}
        <section className="py-12 sm:py-16" data-testid="top-ranked-section">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              {/* Leaderboard card */}
              <div className="lg:col-span-2 border border-slate-200 rounded-lg bg-white overflow-hidden" data-testid="top-ranked-card">
                <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
                  <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                    <Trophy className="h-4.5 w-4.5 text-[#1E3A8A]" /> Top ranked papers
                  </h2>
                  <a
                    href="/?period=recent"
                    className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-1"
                    data-testid="view-full-leaderboard"
                  >
                    View full leaderboard <ChevronRight className="h-3 w-3" />
                  </a>
                </div>
                <div className="divide-y divide-slate-100">
                  {topPapers.length > 0 ? topPapers.map((p, i) => (
                    <a
                      key={p.id || i}
                      href={p.id ? `/paper/${p.id}` : "#"}
                      className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50/80 transition-colors group"
                      data-testid={`top-paper-${i}`}
                    >
                      <span
                        className="text-lg font-semibold text-slate-300 w-8 text-right shrink-0 tabular-nums"
                        style={{ fontFamily: "'IBM Plex Mono', monospace" }}
                      >
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-900 truncate group-hover:text-[#1E3A8A] transition-colors">
                          {p.title}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                            {p.primary_category}
                          </span>
                          {p.authors?.length > 0 && (
                            <span className="text-xs text-slate-400 truncate">
                              {p.authors.slice(0, 2).join(", ")}{p.authors.length > 2 ? " et al." : ""}
                            </span>
                          )}
                        </div>
                      </div>
                      <span
                        className="text-sm font-semibold text-[#1E3A8A] shrink-0 tabular-nums"
                        style={{ fontFamily: "'IBM Plex Mono', monospace" }}
                      >
                        {p.ts_score || "—"}
                      </span>
                    </a>
                  )) : (
                    <div className="px-5 py-8 text-center text-sm text-slate-400">Loading rankings...</div>
                  )}
                </div>
              </div>

              {/* Research intelligence sidebar */}
              <div className="space-y-6">
                {/* Research intelligence signals */}
                <div className="border border-slate-200 rounded-lg bg-white p-5" data-testid="research-intelligence">
                  <h3 className="text-sm font-semibold text-slate-800 mb-4 uppercase tracking-wide">Research intelligence</h3>
                  <div className="space-y-3">
                    <Link
                      to="/correlation"
                      className="flex items-center gap-3 p-3 rounded-md border border-slate-100 hover:border-[#0F766E]/30 hover:bg-[#0F766E]/5 transition-all group"
                      data-testid="signal-model-agreement"
                    >
                      <div className="w-8 h-8 rounded-md bg-[#0F766E]/10 flex items-center justify-center shrink-0">
                        <Brain className="h-4 w-4 text-[#0F766E]" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">Model agreement</p>
                        <p className="text-xs text-slate-500">Inter-judge consistency</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-[#0F766E] transition-colors" />
                    </Link>
                    <Link
                      to="/validation"
                      className="flex items-center gap-3 p-3 rounded-md border border-slate-100 hover:border-[#059669]/30 hover:bg-[#059669]/5 transition-all group"
                      data-testid="signal-validation"
                    >
                      <div className="w-8 h-8 rounded-md bg-[#059669]/10 flex items-center justify-center shrink-0">
                        <Activity className="h-4 w-4 text-[#059669]" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">Validation signals</p>
                        <p className="text-xs text-slate-500">Bias tests &amp; benchmarks</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-[#059669] transition-colors" />
                    </Link>
                    <Link
                      to="/methodology"
                      className="flex items-center gap-3 p-3 rounded-md border border-slate-100 hover:border-slate-200 hover:bg-slate-50 transition-all group"
                      data-testid="signal-methodology"
                    >
                      <div className="w-8 h-8 rounded-md bg-slate-100 flex items-center justify-center shrink-0">
                        <BookOpen className="h-4 w-4 text-slate-500" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-slate-800">Methodology</p>
                        <p className="text-xs text-slate-500">How rankings are produced</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-slate-500 transition-colors" />
                    </Link>
                  </div>
                </div>

                {/* Reviewer panel */}
                <div className="border border-slate-200 rounded-lg bg-white p-5" data-testid="reviewer-panel">
                  <h3 className="text-sm font-semibold text-slate-800 mb-3 uppercase tracking-wide">AI judge panel</h3>
                  <div className="space-y-2">
                    {[
                      { name: "GPT-5.2", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
                      { name: "Claude Opus 4.6", color: "bg-orange-50 text-orange-700 border-orange-200" },
                      { name: "Gemini 3.1 Pro", color: "bg-blue-50 text-blue-700 border-blue-200" },
                    ].map(m => (
                      <span key={m.name} className={`inline-block text-xs font-medium px-2.5 py-1 rounded border mr-2 ${m.color}`} style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
                        {m.name}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-slate-500 mt-3 leading-relaxed">
                    Three LLMs judge papers head-to-head via round-robin rotation with five distinct reviewer personas.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════ LIVE PLATFORM METRICS ═══════ */}
        <section className="py-12 sm:py-16 bg-[#F8FAFC]" data-testid="live-metrics-section">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <h2
              className="text-sm font-semibold text-slate-800 uppercase tracking-wide mb-6"
              data-testid="metrics-heading"
            >
              Live platform metrics
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricTile label="Papers ranked" value={fmt(stats?.total_papers)} />
              <MetricTile label="Active categories" value={stats?.total_categories || "\u2014"} />
              <MetricTile label="AI comparisons" value={fmt(stats?.total_matches)} />
              <MetricTile label="AI judges" value={stats?.ai_judges || 3} />
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
              <MetricTile label="Most active" value={topCats[0]?.name || "\u2014"} sub={topCats[0] ? `${fmt(topCats[0].count)} papers` : ""} />
              <MetricTile label="Recent papers" value={fmt(stats?.recent_papers)} sub="Last 7 days" />
              <MetricTile label="Latest update" value={daysSince(stats?.latest_update) || "\u2014"} />
              <MetricTile label="Reviewer personas" value="5" sub="Diverse judge profiles" />
            </div>
          </div>
        </section>

        {/* ═══════ CATEGORIES ═══════ */}
        <section className="py-12 sm:py-16" data-testid="categories-section">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-sm font-semibold text-slate-800 uppercase tracking-wide">
                Rankings by category
              </h2>
              <a href="/?tagOpen=1&period=recent" className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-1" data-testid="all-categories-link">
                All categories <ChevronRight className="h-3 w-3" />
              </a>
            </div>
            {/* Top categories with paper counts */}
            {topCats.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
                {topCats.map(tc => (
                  <a
                    key={tc.id}
                    href={`/?cat=${tc.id}&period=recent`}
                    className="flex items-center justify-between bg-white border border-slate-200 rounded-lg px-5 py-3.5 hover:border-[#1E3A8A]/30 hover:shadow-sm transition-all group"
                    data-testid={`topcat-${tc.id}`}
                  >
                    <div>
                      <p className="text-sm font-semibold text-slate-800">{tc.name}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{fmt(tc.count)} ranked papers</p>
                    </div>
                    <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-[#1E3A8A] transition-colors" />
                  </a>
                ))}
              </div>
            )}
            {/* All categories grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
              {(stats?.categories || []).map(cat => (
                <a
                  key={cat.id}
                  href={`/?cat=${cat.id}&period=recent`}
                  className="bg-white border border-slate-200 rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:border-[#1E3A8A]/30 hover:text-[#1E3A8A] transition-all flex items-center justify-between gap-2"
                  data-testid={`cat-${cat.id}`}
                >
                  <span className="truncate">{cat.name}</span>
                  <ChevronRight className="h-3 w-3 text-slate-300 shrink-0" />
                </a>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════ HOW IT WORKS ═══════ */}
        <section className="py-12 sm:py-16 bg-[#F8FAFC] border-y border-slate-100" data-testid="how-it-works">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight text-slate-800 text-center mb-12" style={{ fontFamily: "'Chivo', 'IBM Plex Sans', system-ui, sans-serif" }}>
              How Kurate ranks papers
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {[
                { icon: Users, title: "Pairwise AI tournaments", desc: "Three LLM judges compare papers head-to-head in round-robin tournaments. Five distinct reviewer personas ensure diverse evaluation perspectives." },
                { icon: BarChart3, title: "TrueSkill scoring", desc: "Match results feed into a Bayesian TrueSkill rating system that produces calibrated rankings. Scores converge as more matches are played." },
                { icon: Shield, title: "Transparent validation", desc: "Every ranking is backed by experiments: inter-model agreement, positional bias tests, and correlation analysis against human expert scores." },
              ].map((c, i) => {
                const Icon = c.icon;
                return (
                  <div key={i} className="bg-white border border-slate-200 rounded-lg p-6" data-testid={`how-${i}`}>
                    <div className="w-10 h-10 rounded-lg bg-[#1E3A8A]/10 flex items-center justify-center mb-4">
                      <Icon className="h-5 w-5 text-[#1E3A8A]" />
                    </div>
                    <h3 className="text-base font-semibold text-slate-800 mb-2">{c.title}</h3>
                    <p className="text-sm text-slate-600 leading-relaxed">{c.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* ═══════ NOT A REPLACEMENT ═══════ */}
        <section className="py-10 sm:py-14" data-testid="disclaimer-section">
          <div className="max-w-3xl mx-auto px-4 sm:px-6 text-center">
            <CheckCircle2 className="h-6 w-6 text-[#0F766E] mx-auto mb-4" />
            <h2 className="text-lg font-semibold text-slate-800 mb-3">Not a replacement for peer review</h2>
            <p className="text-sm text-slate-600 leading-relaxed max-w-xl mx-auto">
              AI rankings are an early signal for discovery and prioritisation.
              Always read the paper and apply your own expertise.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4 mt-6">
              <Link to="/methodology" className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-1.5">
                <BookOpen className="h-3.5 w-3.5" /> Methodology
              </Link>
              <Link to="/correlation" className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-1.5">
                <BarChart3 className="h-3.5 w-3.5" /> Model analysis
              </Link>
              <Link to="/validation" className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5" /> Validation
              </Link>
            </div>
          </div>
        </section>

        {/* ═══════ FOOTER ═══════ */}
        <footer className="border-t border-slate-200 bg-white" data-testid="homepage-footer">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
              <div className="md:col-span-2">
                <div className="flex items-center gap-2 mb-3">
                  <Trophy className="h-4 w-4 text-[#1E3A8A]" />
                  <span className="text-sm font-bold tracking-tight text-slate-900" style={{ fontFamily: "'Chivo', system-ui, sans-serif" }}>
                    Kurate.org
                  </span>
                </div>
                <p className="text-sm text-slate-500 leading-relaxed max-w-sm">
                  AI-powered scientific paper rankings. Helping researchers and institutions identify promising work earlier.
                </p>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Explore</h3>
                <nav className="space-y-2">
                  <a href="/?tagOpen=1&period=recent" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">All rankings</a>
                  <a href="/?period=recent" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Leaderboard</a>
                  <Link to="/methodology" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Methodology</Link>
                  <Link to="/correlation" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Model Analysis</Link>
                  <Link to="/validation" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Validation</Link>
                </nav>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Follow</h3>
                <nav className="space-y-2">
                  <a href="https://x.com/KurateOrg" target="_blank" rel="noopener noreferrer" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">X (Twitter)</a>
                  <a href="https://www.linkedin.com/company/kurate-org" target="_blank" rel="noopener noreferrer" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">LinkedIn</a>
                  <a href="https://www.instagram.com/kurate2026/" target="_blank" rel="noopener noreferrer" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Instagram</a>
                  <a href="https://www.facebook.com/Kurate/" target="_blank" rel="noopener noreferrer" className="block text-sm text-slate-600 hover:text-slate-900 transition-colors">Facebook</a>
                </nav>
              </div>
            </div>
            <div className="mt-8 pt-6 border-t border-slate-100 flex flex-wrap items-center gap-4 text-xs text-slate-400">
              <span>Kurate.org</span>
              <Link to="/privacy" className="hover:text-slate-600 transition-colors">Privacy Policy</Link>
              <Link to="/impressum" className="hover:text-slate-600 transition-colors">Impressum</Link>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}

/* ─── Sub-components ─── */
function MetricTile({ label, value, sub }) {
  return (
    <div className="p-4 sm:p-5 border border-slate-200 bg-white rounded-lg flex flex-col gap-1" data-testid={`metric-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <span className="text-xs uppercase tracking-[0.12em] text-slate-500" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
        {label}
      </span>
      <span className="text-xl sm:text-2xl font-bold text-slate-900 tabular-nums" style={{ fontFamily: "'Chivo', system-ui, sans-serif" }}>
        {value}
      </span>
      {sub && <span className="text-xs text-slate-400">{sub}</span>}
    </div>
  );
}
