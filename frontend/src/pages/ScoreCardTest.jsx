import { Trophy, Target } from "lucide-react";

const DATA = {
  rating: 9, significance: 9.5, rigor: 9.5, novelty: 9, clarity: 8.5,
  wins: 45, losses: 4, matches: 49, winRate: 92,
  score: 1677, ci: 77, rangeMin: 700, rangeMax: 2200,
};

function CIBar({ score, ci, rangeMin, rangeMax }) {
  const range = rangeMax - rangeMin;
  const lo = score - ci;
  const hi = score + ci;
  const loPct = Math.max(0, ((lo - rangeMin) / range) * 100);
  const hiPct = Math.min(100, ((hi - rangeMin) / range) * 100);
  const scorePct = ((score - rangeMin) / range) * 100;
  return (
    <div>
      <div className="w-full h-2 bg-slate-100 rounded-full relative">
        <div className="absolute h-full bg-blue-200 rounded-full" style={{ left: `${loPct}%`, width: `${hiPct - loPct}%` }} />
        <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{ left: `${scorePct}%` }} />
      </div>
      <div className="flex justify-between mt-1 text-[10px] text-slate-400">
        <span>{rangeMin}</span><span>{rangeMax}</span>
      </div>
    </div>
  );
}

function SubBadge({ label, value, color }) {
  return <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${color}`}>{label} {value}</span>;
}

const BADGES = [
  { label: "Significance", value: DATA.significance, color: "text-blue-700 bg-blue-50 border-blue-200" },
  { label: "Rigor", value: DATA.rigor, color: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  { label: "Novelty", value: DATA.novelty, color: "text-violet-700 bg-violet-50 border-violet-200" },
  { label: "Clarity", value: DATA.clarity, color: "text-amber-700 bg-amber-50 border-amber-200" },
];

// ═══════════════════════════════════════════
// OPTION E: A+D Hybrid — Stats tiles inside Tournament box
// ═══════════════════════════════════════════
function OptionE() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* Left: Tournament Score with embedded stat tiles */}
        <div className="md:w-3/5 p-6 md:border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-2 mb-3">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-lg text-slate-400">±{DATA.ci}</span>
          </div>
          {/* CI bar */}
          <CIBar {...DATA} />
          {/* Stat tiles row */}
          <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-slate-100">
            <div className="text-center p-2.5 bg-slate-50 rounded-lg">
              <div className="text-xl font-bold text-slate-900">{DATA.winRate}%</div>
              <div className="text-[10px] text-slate-500 mt-0.5">Win Rate</div>
            </div>
            <div className="text-center p-2.5 bg-green-50 rounded-lg">
              <div className="text-xl font-bold text-green-600">{DATA.wins}</div>
              <div className="text-[10px] text-slate-500 mt-0.5">Wins</div>
            </div>
            <div className="text-center p-2.5 bg-red-50 rounded-lg">
              <div className="text-xl font-bold text-red-500">{DATA.losses}</div>
              <div className="text-[10px] text-slate-500 mt-0.5">Losses</div>
            </div>
          </div>
        </div>
        {/* Right: AI Rating */}
        <div className="md:w-2/5 p-6 bg-slate-50/50">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Target className="h-3.5 w-3.5" /> AI Rating
          </div>
          <div className="flex items-baseline gap-1 mb-4">
            <span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}.0</span>
            <span className="text-sm text-slate-400">/ 10</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION F: Tighter variant — stat tiles as pills
// ═══════════════════════════════════════════
function OptionF() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* Left: Tournament Score */}
        <div className="md:w-3/5 p-6 md:border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-baseline gap-2">
              <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
              <span className="text-lg text-slate-400">±{DATA.ci}</span>
            </div>
            {/* Inline stat pills */}
            <div className="flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-slate-100 text-slate-700">{DATA.winRate}%</span>
              <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-green-50 text-green-600 border border-green-200">{DATA.wins}W</span>
              <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-red-50 text-red-500 border border-red-200">{DATA.losses}L</span>
            </div>
          </div>
          <CIBar {...DATA} />
        </div>
        {/* Right: AI Rating */}
        <div className="md:w-2/5 p-6 bg-slate-50/50">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Target className="h-3.5 w-3.5" /> AI Rating
          </div>
          <div className="flex items-baseline gap-1 mb-4">
            <span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}.0</span>
            <span className="text-sm text-slate-400">/ 10</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION G: Score bar spans full width, tiles below
// ═══════════════════════════════════════════
function OptionG() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {/* Top: Score + CI full width */}
      <div className="p-6 pb-4">
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <Trophy className="h-3.5 w-3.5" /> Tournament Score
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
              <span className="text-lg text-slate-400">±{DATA.ci}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400 mb-1">AI Rating</div>
            <div className="flex items-baseline gap-0.5">
              <span className="text-3xl font-bold text-slate-600">{DATA.rating}.0</span>
              <span className="text-sm text-slate-400">/10</span>
            </div>
          </div>
        </div>
        <CIBar {...DATA} />
      </div>
      {/* Bottom: Tiles row */}
      <div className="grid grid-cols-4 gap-px bg-slate-200 border-t border-slate-200">
        <div className="bg-white p-3 text-center">
          <div className="text-xl font-bold text-slate-900">{DATA.winRate}%</div>
          <div className="text-[10px] text-slate-500">Win Rate</div>
        </div>
        <div className="bg-green-50/50 p-3 text-center">
          <div className="text-xl font-bold text-green-600">{DATA.wins}</div>
          <div className="text-[10px] text-slate-500">Wins</div>
        </div>
        <div className="bg-red-50/50 p-3 text-center">
          <div className="text-xl font-bold text-red-500">{DATA.losses}</div>
          <div className="text-[10px] text-slate-500">Losses</div>
        </div>
        <div className="bg-white p-3">
          <div className="flex flex-wrap gap-1 justify-center">
            {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

function ViewportLabel({ label }) {
  return (
    <div className="text-center text-xs font-medium text-slate-400 uppercase tracking-wider mb-3 mt-8 border-b border-slate-200 pb-2">{label}</div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">A+D Hybrid Options — Tournament Score with Stat Tiles</h1>

      {/* Desktop */}
      <ViewportLabel label="Desktop (max-w-4xl)" />
      <div className="max-w-4xl mx-auto space-y-8">
        <div>
          <h2 className="text-lg font-semibold text-slate-700 mb-2">Option E: Stat tiles inside tournament box</h2>
          <OptionE />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-700 mb-2">Option F: Stats as inline pills (more compact)</h2>
          <OptionF />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-700 mb-2">Option G: Full-width score bar + tile strip</h2>
          <OptionG />
        </div>
      </div>

      {/* Tablet */}
      <ViewportLabel label="Tablet (640px)" />
      <div className="max-w-[640px] mx-auto space-y-8">
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option E — Tablet</h2>
          <OptionE />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option F — Tablet</h2>
          <OptionF />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option G — Tablet</h2>
          <OptionG />
        </div>
      </div>

      {/* Mobile */}
      <ViewportLabel label="Mobile (375px)" />
      <div className="max-w-[375px] mx-auto space-y-8">
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option E — Mobile</h2>
          <OptionE />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option F — Mobile</h2>
          <OptionF />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-2">Option G — Mobile</h2>
          <OptionG />
        </div>
      </div>
    </div>
  );
}
