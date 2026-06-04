import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, ChevronRight, Layers, Sparkles, ShieldCheck, GitCompareArrows,
  Gauge, TrendingUp, FlaskConical, Activity, Telescope, Filter, BarChart3,
  Database, BookOpen, GraduationCap, Building2, Users, Microscope, Newspaper,
  Search,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { api, accentFor } from "@/lib/api";

/* =========================================================================
   Panel 2 — Recent Rankings
   ========================================================================= */
export function RecentRankings() {
  const [cards, setCards] = useState([]);
  useEffect(() => { api.recent().then((d) => setCards(d.cards)); }, []);

  return (
    <section id="recent" className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="flex items-end justify-between gap-6 mb-10">
          <div>
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Recent Rankings</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 max-w-2xl leading-tight">
              Explore newly ranked papers and active research categories.
            </h2>
          </div>
          <Link to="/leaderboard" className="hidden md:inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700" data-testid="recent-view-all">
            Browse all rankings <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {cards.map((card) => {
            const a = accentFor(card.field);
            return (
              <div
                key={card.key}
                data-testid={`recent-card-${card.key}`}
                className="flex flex-col border border-slate-200 bg-white p-5 rounded-sm hover:border-slate-400 transition-colors group"
              >
                <span className={`inline-flex w-fit items-center gap-1.5 px-2 py-0.5 rounded-sm border text-[10px] font-medium ${a.bg} ${a.text} ${a.border}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${a.dot}`} />
                  {card.category_code || "newly-ranked"}
                </span>
                <h3 className="mt-3 font-serif text-lg font-medium text-slate-900 leading-snug">{card.title}</h3>
                <p className="mt-1.5 text-sm text-slate-600 leading-relaxed line-clamp-2">{card.description}</p>
                <div className="mt-auto pt-5 flex items-center justify-between text-xs text-slate-500">
                  <span>{card.count} papers · {card.latest_update}</span>
                  <Link
                    to={card.category_code ? `/leaderboard?category=${card.category_code}` : "/leaderboard?rank_type=newly_ranked"}
                    data-testid={`recent-view-${card.key}`}
                    className="font-medium text-blue-600 hover:text-blue-700 inline-flex items-center gap-1"
                  >
                    View <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 3 — Browse Categories
   ========================================================================= */
export function BrowseCategories() {
  const [cats, setCats] = useState([]);
  const [q, setQ] = useState("");
  const [field, setField] = useState("all");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { api.categories().then(setCats); }, []);

  const filtered = cats.filter((c) =>
    (field === "all" || c.field === field) &&
    (q.trim() === "" || c.name.toLowerCase().includes(q.toLowerCase()) || c.code.toLowerCase().includes(q.toLowerCase()))
  );
  const shown = showAll ? filtered : filtered.slice(0, 8);

  const fields = ["all", ...Array.from(new Set(cats.map((c) => c.field)))];

  return (
    <section id="categories" className="bg-slate-50 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-8">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Browse Categories</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Explore scientific paper rankings by live research category.</h2>
        </div>

        <div className="flex flex-col md:flex-row gap-3 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search categories…"
              data-testid="category-search"
              className="pl-9 h-10 rounded-sm border-slate-200 bg-white"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {fields.map((f) => (
              <button
                key={f}
                onClick={() => setField(f)}
                data-testid={`category-field-${f}`}
                className={`px-3 h-10 rounded-sm border text-xs font-medium transition-colors ${field === f ? "bg-slate-900 text-white border-slate-900" : "bg-white border-slate-200 text-slate-700 hover:border-slate-400"}`}
              >
                {f === "all" ? "All Fields" : f}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {shown.map((c) => {
            const a = accentFor(c.field);
            return (
              <div key={c.code} className="flex flex-col border border-slate-200 bg-white p-5 rounded-sm hover:border-slate-400 transition-colors" data-testid={`category-card-${c.code}`}>
                <div className="flex items-start justify-between">
                  <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm border text-[10px] font-medium ${a.bg} ${a.text} ${a.border}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${a.dot}`} />
                    {c.code}
                  </span>
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider">{c.broad}</span>
                </div>
                <h3 className="mt-3 font-serif text-lg font-medium text-slate-900 leading-snug">{c.name}</h3>
                <p className="mt-1 text-sm text-slate-600 line-clamp-2 leading-relaxed">{c.description}</p>
                <div className="mt-auto pt-5 flex items-center justify-between text-xs">
                  <span className="text-slate-500">{c.paper_count} papers · {c.latest_update}</span>
                  <Link to={`/leaderboard?category=${c.code}`} className="font-medium text-blue-600 hover:text-blue-700 inline-flex items-center gap-1" data-testid={`category-view-${c.code}`}>
                    Leaderboard <ChevronRight className="h-3 w-3" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>

        {filtered.length > 8 && (
          <div className="mt-8 text-center">
            <button onClick={() => setShowAll(!showAll)} data-testid="category-show-more" className="inline-flex items-center gap-1.5 rounded-sm border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              {showAll ? "Show less" : `Show ${filtered.length - 8} more categories`}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 4 — Latest Platform Activity
   ========================================================================= */
function timeAgo(iso) {
  const t = new Date(iso).getTime();
  const s = (Date.now() - t) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function LatestActivity() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.activity().then(setItems); }, []);

  return (
    <section className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-8">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Latest Platform Activity</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight max-w-3xl">See recent ranking updates, active categories, and newly ranked scientific papers across Kurate.</h2>
        </div>

        <div className="border border-slate-200 bg-white rounded-sm divide-y divide-slate-100">
          {items.map((it) => {
            const a = accentFor(it.field);
            return (
              <div key={it.id} className="flex items-start gap-4 px-5 py-4 hover:bg-slate-50/70 transition-colors" data-testid={`activity-${it.id}`}>
                <span className={`mt-1 h-8 w-8 rounded-sm border ${a.bg} ${a.text} ${a.border} flex items-center justify-center shrink-0`}>
                  {it.kind === "paper_ranked" ? <Sparkles className="h-4 w-4" strokeWidth={1.5} /> : <Activity className="h-4 w-4" strokeWidth={1.5} />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                    <span>{it.category_code}</span>
                    <span className="text-slate-300">·</span>
                    <span>{timeAgo(it.timestamp)}</span>
                  </div>
                  <div className="mt-1 text-sm font-medium text-slate-900 leading-snug">{it.title}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{it.status}</div>
                </div>
                <a href="#" data-testid={`activity-view-${it.id}`} className="text-xs font-medium text-blue-600 hover:text-blue-700 whitespace-nowrap mt-1">View →</a>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 5 — Research Intelligence Signals
   ========================================================================= */
const SIGNALS = [
  { icon: GitCompareArrows, title: "AI-assisted comparison", body: "Kurate uses AI-assisted comparison to evaluate papers within relevant research contexts and support category-based ranking." },
  { icon: Layers, title: "Category-based leaderboards", body: "Papers are organised within live research categories so users can interpret rankings in a meaningful field-specific context." },
  { icon: Gauge, title: "Model agreement", body: "Where available, model agreement indicates whether ranking signals are consistent across AI judges or comparison runs." },
  { icon: ShieldCheck, title: "Validation signal", body: "Validation indicators provide additional transparency about the reliability or consistency of ranking outputs." },
  { icon: TrendingUp, title: "Research momentum", body: "Momentum signals help users identify active or fast-moving areas of scientific work." },
  { icon: Sparkles, title: "Novelty & significance", body: "Kurate helps surface papers that may be novel, technically significant, or worth closer expert reading." },
  { icon: Telescope, title: "Field-level context", body: "Signals should be interpreted within the relevant research category rather than across unrelated scientific fields." },
  { icon: BarChart3, title: "Ranking movement", body: "Where available, movement indicators can show whether papers or categories are gaining attention over time." },
];

export function ResearchSignals() {
  return (
    <section id="methodology" className="bg-slate-50 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 max-w-3xl">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Research Intelligence Signals</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">A ranking and signal layer for scientific preprint discovery.</h2>
          <p className="mt-4 text-base text-slate-600 leading-relaxed">Kurate adds research intelligence on top of paper discovery, helping users interpret which papers may deserve closer attention.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {SIGNALS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="border border-slate-200 bg-white p-5 rounded-sm hover:border-slate-300 transition-colors" data-testid={`signal-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-sm bg-blue-50 text-blue-600 border border-blue-100 mb-4">
                <Icon className="h-4 w-4" strokeWidth={1.5} />
              </span>
              <h3 className="font-sans text-base font-semibold text-slate-900">{title}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 6 — How Kurate Rankings Work
   ========================================================================= */
const STEPS = [
  { n: "01", t: "Collect papers", d: "Kurate gathers scientific preprints from live data sources and organises them into research categories." },
  { n: "02", t: "Compare papers", d: "AI-assisted comparison evaluates papers within their relevant category contexts." },
  { n: "03", t: "Generate rankings", d: "The platform produces category-based leaderboards using available ranking scores and research signals." },
  { n: "04", t: "Expose signals", d: "Users inspect scores, categories, validation indicators, model agreement, and related discovery signals." },
  { n: "05", t: "Support reading", d: "Kurate does not replace expert judgement. It helps researchers prioritise which papers to inspect more carefully." },
];

export function HowItWorks() {
  return (
    <section className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-10">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">How Kurate Rankings Work</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight max-w-3xl">A discovery workflow for fast-moving scientific literature.</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-0 md:gap-0 border-t border-l border-slate-200">
          {STEPS.map((s, i) => (
            <div key={s.n} className="border-b border-r border-slate-200 p-6 bg-white" data-testid={`step-${s.n}`}>
              <span className="font-serif text-xl text-blue-600">{s.n}</span>
              <h3 className="mt-3 font-sans text-base font-semibold text-slate-900">{s.t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 7 — Why Category-Based Rankings Matter
   ========================================================================= */
export function WhyCategories() {
  const points = [
    { t: "Field context matters", d: "A paper's significance is easier to interpret when compared with other papers from the same or related category." },
    { t: "Broad rankings hide specialised work", d: "Important papers in smaller technical fields may be missed when discovery depends only on general popularity or social attention." },
    { t: "Category filters improve discovery", d: "Move directly into the field you care about and inspect rankings, signals, and recent activity within that category." },
  ];
  return (
    <section className="bg-slate-50 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20 grid grid-cols-1 lg:grid-cols-12 gap-10">
        <div className="lg:col-span-5">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Why Category-Based Rankings Matter</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Scientific papers are difficult to compare across unrelated fields.</h2>
          <p className="mt-5 text-base text-slate-600 leading-relaxed">
            A robotics paper, a quantum physics paper, and an economics paper may all be important — but they should not be interpreted through the same field assumptions. Kurate uses category-based leaderboards so papers are ranked and explored within more meaningful research contexts.
          </p>
        </div>
        <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {points.map((p) => (
            <div key={p.t} className="border border-slate-200 bg-white p-5 rounded-sm">
              <h3 className="font-sans text-sm font-semibold text-slate-900">{p.t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{p.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 8 — Platform Capabilities
   ========================================================================= */
const CAPS = [
  { icon: BarChart3, t: "Live paper rankings", d: "Explore dynamically updated leaderboards across supported categories." },
  { icon: Filter, t: "Category filtering", d: "Filter papers by research field, category code, time period, and year." },
  { icon: GitCompareArrows, t: "AI-assisted comparison", d: "Use model-assisted paper comparison to help surface promising research." },
  { icon: ShieldCheck, t: "Validation & agreement signals", d: "Inspect available model agreement, validation, or ranking consistency signals." },
  { icon: Newspaper, t: "Recent paper discovery", d: "Find newly ranked and recently active papers across fast-moving fields." },
  { icon: Database, t: "Research intelligence dashboard", d: "View platform-level signals such as active categories, ranking activity, and category movement." },
];

export function PlatformCapabilities() {
  return (
    <section className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 max-w-3xl">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Platform Capabilities</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Practical capabilities, packaged for research workflows.</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {CAPS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="border border-slate-200 bg-white p-6 rounded-sm hover:border-slate-300 transition-colors" data-testid={`capability-${t.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-sm bg-blue-50 text-blue-600 border border-blue-100 mb-4">
                <Icon className="h-4 w-4" strokeWidth={1.5} />
              </span>
              <h3 className="font-sans text-base font-semibold text-slate-900">{t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 9 — What Makes Kurate Different
   ========================================================================= */
export function WhatMakesDifferent() {
  const compare = [
    { a: "Search engines help users find known topics.", b: "Kurate helps users discover promising papers inside active research categories." },
    { a: "Preprint servers show what has been uploaded.", b: "Kurate helps organise what may deserve attention." },
    { a: "Citation databases are powerful but slow.", b: "Kurate focuses on early discovery before long-term citation patterns emerge." },
    { a: "Social media attention is noisy.", b: "Kurate uses structured ranking and research signals." },
  ];
  return (
    <section className="bg-slate-50 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-5">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">What Makes Kurate Different</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">A ranking and signal layer for scientific work.</h2>
            <p className="mt-5 text-base text-slate-600 leading-relaxed">
              Traditional search engines, repositories, and preprint servers are often organised around keywords, upload dates, metadata, or citation counts. Kurate adds a ranking and signal layer on top of scientific preprint discovery, helping users identify papers that may be important before conventional citation signals become available.
            </p>
          </div>
          <div className="lg:col-span-7">
            <div className="border border-slate-200 bg-white rounded-sm divide-y divide-slate-100">
              {compare.map((c, i) => (
                <div key={i} className="grid grid-cols-1 md:grid-cols-2 gap-4 px-5 py-5">
                  <div className="text-sm text-slate-500 leading-relaxed">{c.a}</div>
                  <div className="text-sm text-slate-900 font-medium leading-relaxed flex items-start gap-2">
                    <span className="font-serif italic text-blue-600 text-base shrink-0">Kurate</span>
                    <span>{c.b.replace("Kurate ", "").replace("Kurate.", "")}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 10 — Who Kurate Is For
   ========================================================================= */
const PERSONAS = [
  { icon: FlaskConical, t: "Researchers", d: "Follow fast-moving fields, identify promising preprints, and discover papers that may not yet have citation visibility." },
  { icon: GraduationCap, t: "Postgraduate students", d: "Scan active research areas, find relevant papers for literature reviews, and understand which topics are moving quickly." },
  { icon: BookOpen, t: "Research supervisors", d: "Recommend recent papers, monitor field activity, and identify emerging work for discussion with students." },
  { icon: Users, t: "Research groups & labs", d: "Track category activity, compare papers within a field, and support reading-group paper selection." },
  { icon: Building2, t: "Institutions", d: "Monitor emerging scientific areas and understand where attention is forming across research categories." },
  { icon: Newspaper, t: "Science communicators", d: "Identify papers that may become important and follow early signals in scientific literature." },
];

export function WhoFor() {
  return (
    <section id="about" className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 max-w-3xl">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Who Kurate Is For</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Built for researchers, students, supervisors, labs, institutions, and analysts.</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {PERSONAS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="border border-slate-200 bg-white p-6 rounded-sm hover:border-slate-300 transition-colors" data-testid={`persona-${t.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-sm bg-blue-50 text-blue-600 border border-blue-100 mb-4">
                <Icon className="h-4 w-4" strokeWidth={1.5} />
              </span>
              <h3 className="font-serif text-xl font-medium text-slate-900">{t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Panel 11 — Trust, Transparency, Limitations
   ========================================================================= */
export function TrustPanel() {
  const points = [
    { t: "Discovery signal, not peer review", d: "Kurate helps users decide what to read more closely. It does not certify correctness." },
    { t: "Category context matters", d: "Rankings should be interpreted within category boundaries and available data." },
    { t: "Signals require interpretation", d: "Scores, model agreement, validation, and ranking movement should be considered alongside expert reading." },
    { t: "Transparent methodology", d: "The platform links openly to methodology, validation, and model agreement documentation." },
  ];
  return (
    <section id="validation" className="bg-slate-50 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-5">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Trust, Transparency, Limitations</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">A discovery layer, not a replacement for peer review.</h2>
          </div>
          <div className="lg:col-span-7">
            <div className="border border-slate-200 bg-white p-7 rounded-sm">
              <p className="text-base text-slate-700 leading-relaxed">
                Kurate is designed as a research discovery layer, not as a replacement for peer review. Rankings should be interpreted as discovery signals that help prioritise reading, not as final judgments of scientific truth. Users should always inspect the paper, methodology, evidence, assumptions, limitations, and field context before forming conclusions.
              </p>
              <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
                {points.map((p) => (
                  <div key={p.t} className="border-l-2 border-blue-600 pl-4">
                    <h3 className="font-sans text-sm font-semibold text-slate-900">{p.t}</h3>
                    <p className="mt-1 text-sm text-slate-600 leading-relaxed">{p.d}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
