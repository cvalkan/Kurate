import { Trophy, Target, Activity, TrendingUp } from "lucide-react";

// Sample data matching the screenshot
const DATA = {
  rating: 9, significance: 9.5, rigor: 9.5, novelty: 9, clarity: 8.5,
  wins: 45, losses: 4, matches: 49, winRate: 92,
  score: 1677, ci: 77, rangeMin: 700, rangeMax: 2200,
};

function CIBar({ score, ci, rangeMin, rangeMax, height = "h-1.5" }) {
  const range = rangeMax - rangeMin;
  const lo = score - ci;
  const hi = score + ci;
  const loPct = Math.max(0, ((lo - rangeMin) / range) * 100);
  const hiPct = Math.min(100, ((hi - rangeMin) / range) * 100);
  const scorePct = ((score - rangeMin) / range) * 100;
  return (
    <div className={`w-full ${height} bg-slate-100 rounded-full relative`}>
      <div className="absolute h-full bg-blue-200 rounded-full" style={{ left: `${loPct}%`, width: `${hiPct - loPct}%` }} />
      <div className="absolute h-3 w-3 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{ left: `${scorePct}%` }} />
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
// OPTION 1: The Bento Row (Equal 3-Column)
// ═══════════════════════════════════════════
function Option1() {
  return (
    <div className="flex flex-col md:flex-row divide-y md:divide-y-0 md:divide-x divide-slate-200 border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden" data-testid="score-card-option-1">
      {/* Rating */}
      <div className="flex-1 p-5" data-testid="overall-rating">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Target className="h-3.5 w-3.5" /> Rating
        </div>
        <div className="flex items-baseline gap-1 mb-3">
          <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.rating}.0</span>
          <span className="text-sm text-slate-400">/ 10</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
        </div>
      </div>
      {/* Stats */}
      <div className="flex-1 p-5" data-testid="tournament-stats">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Trophy className="h-3.5 w-3.5" /> Tournament
        </div>
        <div className="flex items-baseline gap-1 mb-3">
          <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.winRate}%</span>
          <span className="text-sm text-slate-400">win rate</span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-green-600 font-semibold">{DATA.wins}W</span>
          <span className="text-slate-300">/</span>
          <span className="text-red-600 font-semibold">{DATA.losses}L</span>
          <span className="text-slate-300">·</span>
          <span className="text-slate-500">{DATA.matches} matches</span>
        </div>
      </div>
      {/* CI */}
      <div className="flex-1 p-5" data-testid="confidence-interval">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Activity className="h-3.5 w-3.5" /> Score (95% CI)
        </div>
        <div className="flex items-baseline gap-1 mb-4">
          <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
          <span className="text-sm text-slate-400">±{DATA.ci}</span>
        </div>
        <CIBar {...DATA} />
        <div className="flex justify-between mt-1 text-[10px] text-slate-400">
          <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 2: Hero Left Sidebar (Asymmetric)
// ═══════════════════════════════════════════
function Option2() {
  return (
    <div className="flex flex-col md:flex-row border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden" data-testid="score-card-option-2">
      {/* Left sidebar */}
      <div className="md:w-1/3 bg-slate-50 p-6 flex flex-col justify-between border-b md:border-b-0 md:border-r border-slate-200">
        <div>
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Overall Rating</div>
          <div className="flex items-baseline gap-1">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.rating}.0</span>
            <span className="text-lg text-slate-400">/ 10</span>
          </div>
        </div>
        <div className="mt-4">
          <div className="flex items-baseline gap-1 mb-1">
            <span className="text-2xl font-bold tracking-tight text-blue-600">{DATA.score}</span>
            <span className="text-xs text-slate-400">±{DATA.ci}</span>
          </div>
          <CIBar {...DATA} />
          <div className="flex justify-between mt-1 text-[10px] text-slate-400">
            <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
          </div>
        </div>
      </div>
      {/* Right content */}
      <div className="md:w-2/3 p-6">
        <div className="flex flex-wrap gap-1.5 mb-5">
          {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="text-center p-3 bg-green-50 rounded-lg border border-green-200">
            <div className="text-2xl font-bold text-green-600">{DATA.wins}</div>
            <div className="text-xs text-slate-500 mt-0.5">Wins</div>
          </div>
          <div className="text-center p-3 bg-red-50 rounded-lg border border-red-200">
            <div className="text-2xl font-bold text-red-600">{DATA.losses}</div>
            <div className="text-xs text-slate-500 mt-0.5">Losses</div>
          </div>
          <div className="text-center p-3 bg-slate-50 rounded-lg border border-slate-200">
            <div className="text-2xl font-bold text-slate-900">{DATA.matches}</div>
            <div className="text-xs text-slate-500 mt-0.5">Matches</div>
          </div>
          <div className="text-center p-3 bg-blue-50 rounded-lg border border-blue-200">
            <div className="text-2xl font-bold text-blue-600">{DATA.winRate}%</div>
            <div className="text-xs text-slate-500 mt-0.5">Win Rate</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 3: Compact Strip (Ultra-dense)
// ═══════════════════════════════════════════
function Option3() {
  return (
    <div className="flex flex-wrap md:flex-nowrap items-center justify-between p-4 border border-slate-200 rounded-xl bg-white shadow-sm gap-4 md:gap-0" data-testid="score-card-option-3">
      {/* Rating */}
      <div className="flex items-center gap-3 md:pr-4 md:border-r border-slate-200">
        <div className="flex items-baseline gap-0.5">
          <span className="text-3xl font-bold tracking-tight text-slate-900">{DATA.rating}.0</span>
          <span className="text-sm text-slate-400">/10</span>
        </div>
      </div>
      {/* Sub-scores */}
      <div className="flex flex-wrap gap-1 md:px-4 md:border-r border-slate-200">
        {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
      </div>
      {/* Stats */}
      <div className="flex items-center gap-3 md:px-4 md:border-r border-slate-200">
        <div>
          <span className="text-xl font-bold text-slate-900">{DATA.winRate}%</span>
          <span className="text-xs text-slate-500 ml-1">win rate</span>
        </div>
        <div className="text-xs text-slate-500">
          <span className="text-green-600 font-semibold">{DATA.wins}W</span>
          {" - "}
          <span className="text-red-600 font-semibold">{DATA.losses}L</span>
        </div>
      </div>
      {/* CI */}
      <div className="flex items-center gap-3 md:pl-4 flex-1 min-w-[200px]">
        <div className="shrink-0">
          <span className="text-xl font-bold text-blue-600">{DATA.score}</span>
          <span className="text-xs text-slate-400 ml-0.5">±{DATA.ci}</span>
        </div>
        <div className="flex-1">
          <CIBar {...DATA} />
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 4: 2×2 Feature Card
// ═══════════════════════════════════════════
function Option4() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-slate-200 border border-slate-200 rounded-xl overflow-hidden shadow-sm" data-testid="score-card-option-4">
      {/* Top-Left: Rating */}
      <div className="bg-white p-5">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <Target className="h-3.5 w-3.5" /> Rating
        </div>
        <div className="flex items-baseline gap-1 mb-3">
          <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.rating}.0</span>
          <span className="text-sm text-slate-400">/ 10</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
        </div>
      </div>
      {/* Top-Right: Stats */}
      <div className="bg-white p-5">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <Trophy className="h-3.5 w-3.5" /> Tournament
        </div>
        <div className="flex items-baseline gap-1 mb-3">
          <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.winRate}%</span>
          <span className="text-sm text-slate-400">win rate</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500" /><span className="text-green-600 font-semibold">{DATA.wins}</span><span className="text-slate-400">wins</span></div>
          <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" /><span className="text-red-600 font-semibold">{DATA.losses}</span><span className="text-slate-400">losses</span></div>
          <div className="text-slate-400">{DATA.matches} total</div>
        </div>
      </div>
      {/* Bottom: CI (full width) */}
      <div className="md:col-span-2 bg-white p-5">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5" /> Score (95% CI)
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-sm text-slate-400">±{DATA.ci}</span>
          </div>
        </div>
        <CIBar {...DATA} height="h-2" />
        <div className="flex justify-between mt-1 text-[10px] text-slate-400">
          <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
        </div>
      </div>
    </div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="max-w-4xl mx-auto p-8 space-y-12">
      <h1 className="text-2xl font-bold text-slate-900">Score Card Design Options</h1>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option 1: Bento Row (Equal 3-Column)</h2>
        <Option1 />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option 2: Hero Left Sidebar (Asymmetric)</h2>
        <Option2 />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option 3: Compact Strip (Ultra-Dense)</h2>
        <Option3 />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option 4: 2×2 Feature Card</h2>
        <Option4 />
      </div>
    </div>
  );
}
