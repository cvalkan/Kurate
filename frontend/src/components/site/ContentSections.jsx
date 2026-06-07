import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, Layers, GitCompareArrows, Telescope, Filter,
  BarChart3, BookOpen, GraduationCap, Building2, Users, Newspaper, Clock3,
} from "lucide-react";
import { homepageApi, accentFor } from "@/lib/homepage-api";

/* =========================================================================
   Recent Rankings — dynamic from live category data
   ========================================================================= */
export function RecentRankings() {
  const [cards, setCards] = useState([]);
  useEffect(() => { homepageApi.recent().then((d) => setCards(d.cards)); }, []);

  return (
    <section id="categories" className="w-full border-t border-slate-200 bg-white" data-testid="recent-rankings">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Recent Rankings</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">Explore newly ranked papers and active research categories.</h2>
        <Link to="/leaderboard" className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 mt-3" data-testid="recent-browse-link">
          Browse all rankings <ArrowRight className="h-3 w-3" />
        </Link>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
          {cards.map((card) => {
            const a = accentFor(card.field);
            return (
              <div key={card.key} className="border border-slate-200 rounded-sm p-4 hover:shadow-sm transition-shadow" data-testid={`recent-card-${card.key}`}>
                <span className={`inline-block text-[10px] font-mono font-medium px-1.5 py-0.5 rounded ${a.bg} ${a.text}`}>
                  {card.category_code || "newly-ranked"}
                </span>
                <h3 className="font-serif text-base text-slate-900 mt-2 line-clamp-2">{card.title}</h3>
                <p className="text-xs text-slate-500 mt-1 line-clamp-2">{card.description}</p>
                <div className="flex items-center justify-between mt-3 text-[11px] text-slate-400">
                  <span>{card.count} papers · {card.latest_update}</span>
                  <span className="font-medium text-blue-600">View</span>
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
   Research Intelligence and Current Capabilities
   ========================================================================= */
const CAPS = [
  { icon: GitCompareArrows, t: "AI-assisted comparison", d: "Papers are compared using AI-assisted pairwise evaluation to produce category-level rankings." },
  { icon: Layers, t: "Category-based leaderboards", d: "Papers are organised within live arXiv categories so rankings can be read in their proper field context." },
  { icon: BarChart3, t: "Score — comparative tournament ranking", d: "Score is the comparative tournament-based ranking score derived from AI-assisted paper comparisons within a category." },
  { icon: Telescope, t: "Rating — standalone scientific impact (1.0-10.0)", d: "Rating is a standalone scientific impact rating on a 1.0-10.0 scale. It is independent of the tournament and does not come from pairwise comparison." },
  { icon: Filter, t: "Gap — percentile difference between Score and Rating", d: "Gap shows how far the comparative Score sits from the standalone Rating, expressed as a percentile difference between the two signals." },
  { icon: Clock3, t: "Recent rankings & search", d: "Recently ranked papers and updated categories are surfaced on the homepage, with search and time-period filtering across papers." },
];

const COMING_SOON = [
  "Extended novelty and significance signals",
  "Field-level validation reporting",
  "Non-tournament ranking mechanisms",
  "Cross-model agreement metrics",
];

export function ResearchAndCapabilities() {
  return (
    <section className="w-full border-t border-slate-200 bg-slate-50/40" data-testid="capabilities-section">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Research Intelligence & Current Capabilities</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">What Kurate supports today.</h2>
        <p className="text-sm text-slate-500 max-w-xl mt-2">
          A ranking and discovery layer for scientific preprints. The capabilities below reflect what is currently live on the platform.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mt-10">
          {CAPS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="flex gap-3">
              <Icon className="h-5 w-5 text-slate-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">{t}</h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">{d}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-12 border border-slate-200 rounded-sm p-5 bg-white">
          <h3 className="text-sm font-semibold text-slate-900">Coming Soon</h3>
          <p className="text-xs text-slate-500 mt-1">Planned features under active development. These are not yet part of the live platform.</p>
          <ul className="mt-3 space-y-1.5">
            {COMING_SOON.map((item) => (
              <li key={item} className="text-xs text-slate-600 flex items-start gap-2">
                <span className="mt-1.5 h-1 w-1 rounded-full bg-slate-300 shrink-0" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   How Kurate Rankings Work — 4 steps
   ========================================================================= */
const STEPS = [
  { n: "01", t: "Collect papers", d: "Kurate gathers scientific preprints from supported arXiv categories." },
  { n: "02", t: "Compare papers", d: "Papers are evaluated through AI-assisted pairwise judgement within each category." },
  { n: "03", t: "Generate Score, Rating, Gap", d: "Tournament comparisons produce the comparative Score. A separate process assigns each paper a standalone Rating on a 1.0-10.0 scale. Gap is the percentile difference between Score and Rating." },
  { n: "04", t: "Explore rankings", d: "Researchers explore ranked papers within each arXiv category to identify work worth closer reading." },
];

export function HowItWorks() {
  return (
    <section className="w-full border-t border-slate-200 bg-white" data-testid="how-it-works">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">How Kurate Rankings Work</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">A discovery workflow for fast-moving scientific literature.</h2>
        <p className="text-sm text-slate-500 max-w-xl mt-2">
          Kurate compares papers using AI-assisted evaluation and produces category-based rankings that help researchers identify work worth closer inspection.
        </p>
        <Link to="/methodology" className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 mt-3" data-testid="hiw-methodology-link">
          Read full methodology <ArrowRight className="h-3 w-3" />
        </Link>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 mt-10">
          {STEPS.map((s) => (
            <div key={s.n} className="relative">
              <span className="text-4xl font-serif text-slate-200">{s.n}</span>
              <h3 className="text-sm font-semibold text-slate-900 mt-2">{s.t}</h3>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Why Category-Based Rankings Matter
   ========================================================================= */
export function WhyCategories() {
  const points = [
    { t: "Field context matters", d: "A paper's significance is easier to interpret when compared with other papers from the same arXiv category." },
    { t: "Broad rankings hide specialised work", d: "Important papers in smaller technical fields may be missed when discovery depends only on general popularity or social attention." },
    { t: "Category filters improve discovery", d: "Move directly into the arXiv category you care about and inspect ranked papers within that context." },
  ];
  return (
    <section className="w-full border-t border-slate-200 bg-slate-50/40" data-testid="why-categories">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Why Category-Based Rankings Matter</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">Scientific papers are difficult to compare across unrelated fields.</h2>
        <p className="text-sm text-slate-500 max-w-xl mt-2">
          A robotics paper, a quantum physics paper, and an economics paper may all be important — but they should not be interpreted through the same field assumptions. Kurate uses category-based leaderboards so papers are ranked within more meaningful research contexts.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 mt-10">
          {points.map((p) => (
            <div key={p.t}>
              <h3 className="text-sm font-semibold text-slate-900">{p.t}</h3>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">{p.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   What Makes Kurate Different
   ========================================================================= */
export function WhatMakesDifferent() {
  const compare = [
    { a: "Preprint servers show what has been uploaded.", b: "Kurate helps organise ranked papers within each category." },
    { a: "Search tools help users find known topics.", b: "Kurate helps users discover ranked preprints inside active research categories." },
    { a: "Citation databases are useful but slower to reflect new work.", b: "Kurate focuses on earlier discovery through AI-assisted comparison." },
  ];
  return (
    <section className="w-full border-t border-slate-200 bg-white" data-testid="what-makes-different">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">What Makes Kurate Different</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">A ranking layer for scientific preprints.</h2>
        <p className="text-sm text-slate-500 max-w-xl mt-2">
          Kurate adds a ranking layer on top of preprint discovery, combining category-based leaderboards with AI-assisted comparison so users can explore work that may deserve closer reading.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-10">
          {compare.map((c, i) => (
            <div key={i} className="border border-slate-200 rounded-sm p-4 space-y-3">
              <p className="text-xs text-slate-500 leading-relaxed">{c.a}</p>
              <div className="border-t border-slate-100" />
              <p className="text-xs text-slate-900 font-medium leading-relaxed"><span className="text-blue-600">Kurate</span>{c.b.replace("Kurate", "")}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Who Kurate Is For
   ========================================================================= */
const PERSONAS = [
  { icon: BookOpen, t: "Researchers", d: "Follow fast-moving fields, identify ranked preprints, and discover papers that may not yet have citation visibility." },
  { icon: GraduationCap, t: "Postgraduate students", d: "Scan active arXiv categories, find relevant preprints for literature discovery, and follow which topics are moving quickly." },
  { icon: Newspaper, t: "Research supervisors", d: "Recommend recent ranked papers, monitor category activity, and identify emerging work for discussion." },
  { icon: Users, t: "Research groups & labs", d: "Track category activity, compare ranked papers within a field, and support reading-group paper selection." },
  { icon: Building2, t: "Institutions", d: "Monitor emerging scientific areas and where attention is forming across research categories." },
  { icon: Telescope, t: "Science communicators", d: "Identify ranked papers that may become important and follow early signals in the scientific literature." },
];

export function WhoFor() {
  return (
    <section id="about" className="w-full border-t border-slate-200 bg-slate-50/40" data-testid="who-for">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Who Kurate Is For</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">Built for researchers, students, supervisors, labs, institutions, and analysts.</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mt-10">
          {PERSONAS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="flex gap-3">
              <Icon className="h-5 w-5 text-slate-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">{t}</h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">{d}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* =========================================================================
   Trust, Transparency, Limitations
   ========================================================================= */
export function TrustPanel() {
  return (
    <section className="w-full border-t border-slate-200 bg-white" data-testid="trust-panel">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Trust, Transparency, Limitations</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">A discovery layer, not a replacement for peer review.</h2>
        <p className="text-sm text-slate-500 max-w-2xl mt-2 leading-relaxed">
          Kurate rankings are discovery signals, not peer review. They are intended to help users prioritise papers for closer reading. Users should still inspect the paper, methodology, evidence, assumptions, limitations, and field context before forming conclusions.
        </p>
      </div>
    </section>
  );
}
