import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, Layers, GitCompareArrows, Telescope, Filter,
  BarChart3, BookOpen, GraduationCap, Building2, Users, Newspaper, Clock3,
} from "lucide-react";
import { homepageApi } from "@/lib/homepage-api";

/* =========================================================================
   Recent Rankings — dynamic from live category data
   ========================================================================= */
export function RecentRankings() {
  const [cards, setCards] = useState([]);
  useEffect(() => { homepageApi.recent().then((d) => setCards(d.cards)); }, []);

  return (
    <section id="categories" className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
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
            return (
              <div
                key={card.key}
                data-testid={`recent-card-${card.key}`}
                className="flex flex-col border border-slate-200 bg-white p-5 rounded-sm hover:border-slate-400 transition-colors group"
              >
                <span className="inline-flex w-fit items-center gap-1.5 px-2 py-0.5 rounded-sm border text-[10px] font-medium bg-blue-50 text-blue-700 border-blue-200">
                  <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
                  {card.category_code || "newly-ranked"}
                </span>
                <h3 className="mt-3 font-serif text-lg font-medium text-slate-900 leading-snug">{card.title}</h3>
                <p className="mt-1.5 text-sm text-slate-600 leading-relaxed line-clamp-2">{card.description}</p>
                <div className="mt-auto pt-5 flex items-center justify-between text-xs text-slate-500">
                  <span>{card.count} papers{card.time_label ? ` · ${card.time_label}` : ""}</span>
                  <Link
                    to={card.category_code ? `/leaderboard?cat=${card.category_code}` : "/leaderboard"}
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
   Research Intelligence and Current Capabilities
   ========================================================================= */
const CAPS = [
  { icon: GitCompareArrows, t: "AI-assisted comparison", d: "Papers are compared using AI-assisted pairwise evaluation to produce category-level rankings." },
  { icon: Layers, t: "Category-based leaderboards", d: "Papers are organised within live arXiv categories so rankings can be read in their proper field context." },
  { icon: BarChart3, t: "Score: comparative tournament ranking", d: "Score is the comparative tournament-based ranking score derived from AI-assisted paper comparisons within a category." },
  { icon: Telescope, t: "Rating: standalone scientific impact (1 to 10)", d: "Rating is a standalone scientific impact rating on a 1 to 10 scale. It is independent of the tournament and does not come from pairwise comparison." },
  { icon: Filter, t: "Gap: percentile difference between Score and Rating", d: "Gap shows how far the comparative Score sits from the standalone Rating, expressed as a percentile difference between the two signals." },
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
    <section id="capabilities" className="bg-slate-50 border-t border-slate-200" data-testid="capabilities-section">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 max-w-3xl">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Research Intelligence & Current Capabilities</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">What Kurate supports today.</h2>
          <p className="mt-4 text-base text-slate-600 leading-relaxed">A ranking and discovery layer for scientific preprints. The capabilities below reflect what is currently live on the platform.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {CAPS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="border border-slate-200 bg-white p-6 rounded-sm hover:border-slate-300 transition-colors">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-sm bg-blue-50 text-blue-600 border border-blue-100 mb-4">
                <Icon className="h-4 w-4" strokeWidth={1.5} />
              </span>
              <h3 className="hp-sans text-base font-semibold text-slate-900">{t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{d}</p>
            </div>
          ))}
        </div>

        <div className="mt-10 border border-dashed border-slate-300 bg-white p-6 rounded-sm">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-slate-500 mb-3">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" /> Coming Soon
          </div>
          <p className="text-sm text-slate-600 mb-4 max-w-2xl leading-relaxed">Planned features under active development. These are not yet part of the live platform.</p>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
            {COMING_SOON.map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-slate-600">
                <span className="mt-2 h-1 w-1 rounded-full bg-slate-400 shrink-0" />
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
  { n: "02", t: "Evaluate papers", d: "Papers are reviewed, rated, and compared through AI-assisted pairwise evaluation within each category. Three independent AI models judge each pair to produce robust rankings." },
  { n: "03", t: "Score, Rating, Gap", d: "Pairwise comparisons produce a tournament-based Score using TrueSkill. Each paper also receives a standalone Rating (1 to 10) based on scientific impact, independent of the tournament. Gap measures how far the two signals diverge for a given paper." },
  { n: "04", t: "Explore rankings", d: "Browse ranked papers by category, time period, or search to find work worth closer reading." },
];

export function HowItWorks() {
  return (
    <section id="methodology" className="bg-white border-t border-slate-200" data-testid="how-it-works">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 flex flex-col md:flex-row md:items-end md:justify-between gap-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">How Kurate Rankings Work</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight max-w-3xl">A discovery workflow for fast-moving scientific literature.</h2>
            <p className="mt-4 text-base text-slate-600 leading-relaxed max-w-2xl">Kurate compares papers using AI-assisted evaluation and produces category-based rankings that help researchers identify work worth closer inspection.</p>
          </div>
          <Link to="/methodology" data-testid="hiw-methodology-link" className="inline-flex items-center justify-center gap-2 rounded-sm border border-slate-200 bg-white px-4 h-10 text-sm font-medium text-slate-700 hover:bg-slate-50 whitespace-nowrap shrink-0">
            <BookOpen className="h-4 w-4" /> Read full methodology
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 border-t border-l border-slate-200">
          {STEPS.map((s) => (
            <div key={s.n} className="border-b border-r border-slate-200 p-6 bg-white">
              <span className="font-serif text-xl text-blue-600">{s.n}</span>
              <h3 className="mt-3 hp-sans text-base font-semibold text-slate-900">{s.t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{s.d}</p>
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
    <section className="bg-slate-50 border-t border-slate-200" data-testid="why-categories">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20 grid grid-cols-1 lg:grid-cols-12 gap-10">
        <div className="lg:col-span-5">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Why Category-Based Rankings Matter</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Scientific papers are difficult to compare across unrelated fields.</h2>
          <p className="mt-5 text-base text-slate-600 leading-relaxed">
            A robotics paper, a quantum physics paper, and an economics paper may all be important, but they should not be interpreted through the same field assumptions. Kurate uses category-based leaderboards so papers are ranked within more meaningful research contexts.
          </p>
        </div>
        <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {points.map((p) => (
            <div key={p.t} className="border border-slate-200 bg-white p-5 rounded-sm">
              <h3 className="hp-sans text-sm font-semibold text-slate-900">{p.t}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed">{p.d}</p>
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
    <section className="bg-white border-t border-slate-200" data-testid="what-makes-different">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-5">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">What Makes Kurate Different</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">A ranking layer for scientific preprints.</h2>
            <p className="mt-5 text-base text-slate-600 leading-relaxed">
              Kurate adds a ranking layer on top of preprint discovery, combining category-based leaderboards with AI-assisted comparison so users can explore work that may deserve closer reading.
            </p>
          </div>
          <div className="lg:col-span-7">
            <div className="border border-slate-200 bg-white rounded-sm divide-y divide-slate-100">
              {compare.map((c, i) => (
                <div key={i} className="grid grid-cols-1 md:grid-cols-2 gap-4 px-5 py-5">
                  <div className="text-sm text-slate-500 leading-relaxed">{c.a}</div>
                  <div className="text-sm text-slate-900 font-medium leading-relaxed flex items-start gap-2">
                    <span className="font-serif italic text-blue-600 text-base shrink-0">Kurate</span>
                    <span>{c.b.replace("Kurate ", "")}</span>
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
    <section id="about" className="bg-slate-50 border-t border-slate-200" data-testid="who-for">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
        <div className="mb-10 max-w-3xl">
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Who Kurate Is For</div>
          <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Built for researchers, students, supervisors, labs, institutions, and analysts.</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {PERSONAS.map(({ icon: Icon, t, d }) => (
            <div key={t} className="border border-slate-200 bg-white p-6 rounded-sm hover:border-slate-300 transition-colors">
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
   Trust, Transparency, Limitations
   ========================================================================= */
export function TrustPanel() {
  return (
    <section className="bg-white border-t border-slate-200" data-testid="trust-panel">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-5">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Trust, Transparency, Limitations</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">A discovery layer, not a replacement for peer review.</h2>
          </div>
          <div className="lg:col-span-7">
            <div className="border border-slate-200 bg-white p-7 rounded-sm">
              <p className="text-base text-slate-700 leading-relaxed">
                Kurate rankings are discovery signals, not peer review. They are intended to help users prioritise papers for closer reading. Users should still inspect the paper, methodology, evidence, assumptions, limitations, and field context before forming conclusions.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
