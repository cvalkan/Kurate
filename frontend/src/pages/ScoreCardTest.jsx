import { Trophy, Target, TrendingUp, Zap } from "lucide-react";

const DATA = {
  rating: 9, significance: 9.5, rigor: 9.5, novelty: 9, clarity: 8.5,
  wins: 45, losses: 4, matches: 49, winRate: 92,
  score: 1677, ci: 77, rangeMin: 700, rangeMax: 2200,
};

function CIBar({ score, ci, rangeMin, rangeMax, height = "h-2" }) {
  const range = rangeMax - rangeMin;
  const lo = score - ci;
  const hi = score + ci;
  const loPct = Math.max(0, ((lo - rangeMin) / range) * 100);
  const hiPct = Math.min(100, ((hi - rangeMin) / range) * 100);
  const scorePct = ((score - rangeMin) / range) * 100;
  return (
    <div className={`w-full ${height} bg-slate-100 rounded-full relative`}>
      <div className="absolute h-full bg-blue-200 rounded-full" style={{ left: `${loPct}%`, width: `${hiPct - loPct}%` }} />
      <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{ left: `${scorePct}%` }} />
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
// OPTION A: Score Hero + Rating Aside
// Tournament score dominates, CI bar directly beneath it,
// rating is secondary on the right
// ═══════════════════════════════════════════
function OptionA() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* Left: Tournament Score (hero) */}
        <div className="md:w-3/5 p-6 md:border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-lg text-slate-400">±{DATA.ci}</span>
          </div>
          {/* CI bar */}
          <div className="mt-3 mb-4">
            <CIBar {...DATA} />
            <div className="flex justify-between mt-1 text-[10px] text-slate-400">
              <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
            </div>
          </div>
          {/* Stats row */}
          <div className="flex items-center gap-4 text-sm pt-3 border-t border-slate-100">
            <div className="flex items-center gap-1.5">
              <span className="text-2xl font-bold text-slate-900">{DATA.winRate}%</span>
              <span className="text-xs text-slate-400">win rate</span>
            </div>
            <span className="text-slate-200">|</span>
            <span className="text-green-600 font-semibold">{DATA.wins} wins</span>
            <span className="text-red-500 font-semibold">{DATA.losses} losses</span>
            <span className="text-slate-400">{DATA.matches} matches</span>
          </div>
        </div>
        {/* Right: AI Rating (secondary) */}
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
// OPTION B: Stacked with Score Banner
// Large score banner on top with integrated CI,
// stats + rating below in two columns
// ═══════════════════════════════════════════
function OptionB() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {/* Top banner: Score + CI */}
      <div className="bg-slate-900 text-white p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-blue-400" />
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Tournament Score</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-green-400 font-semibold">{DATA.wins}W</span>
            <span className="text-slate-600">/</span>
            <span className="text-red-400 font-semibold">{DATA.losses}L</span>
            <span className="text-slate-500">·</span>
            <span className="text-slate-400">{DATA.winRate}% win rate</span>
          </div>
        </div>
        <div className="flex items-end gap-3 mb-4">
          <span className="text-5xl font-bold tracking-tight">{DATA.score}</span>
          <span className="text-lg text-slate-400 pb-1">±{DATA.ci}</span>
        </div>
        <div className="relative">
          <div className="w-full h-2 bg-slate-700 rounded-full relative">
            <div className="absolute h-full bg-blue-500/40 rounded-full" style={{
              left: `${Math.max(0, ((DATA.score - DATA.ci - DATA.rangeMin) / (DATA.rangeMax - DATA.rangeMin)) * 100)}%`,
              width: `${(DATA.ci * 2 / (DATA.rangeMax - DATA.rangeMin)) * 100}%`
            }} />
            <div className="absolute h-3.5 w-3.5 bg-blue-400 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-slate-900 shadow" style={{
              left: `${((DATA.score - DATA.rangeMin) / (DATA.rangeMax - DATA.rangeMin)) * 100}%`
            }} />
          </div>
          <div className="flex justify-between mt-1 text-[10px] text-slate-500">
            <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
          </div>
        </div>
      </div>
      {/* Bottom: Rating */}
      <div className="p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">AI Rating</div>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold text-slate-700">{DATA.rating}.0</span>
              <span className="text-sm text-slate-400">/ 10</span>
            </div>
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
// OPTION C: Integrated Gauge
// Score as the primary number with CI bar,
// win/loss as a mini progress bar, rating inline
// ═══════════════════════════════════════════
function OptionC() {
  const winPct = (DATA.wins / DATA.matches) * 100;
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm p-6">
      {/* Score + CI (hero) */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-lg text-slate-400">±{DATA.ci}</span>
          </div>
        </div>
        {/* Rating badge (compact, secondary) */}
        <div className="text-right">
          <div className="text-xs text-slate-400 mb-1">AI Rating</div>
          <div className="inline-flex items-baseline gap-0.5 bg-slate-100 px-3 py-1.5 rounded-lg">
            <span className="text-2xl font-bold text-slate-700">{DATA.rating}.0</span>
            <span className="text-xs text-slate-400">/10</span>
          </div>
        </div>
      </div>

      {/* CI bar */}
      <CIBar {...DATA} />
      <div className="flex justify-between mt-1 text-[10px] text-slate-400 mb-5">
        <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
      </div>

      {/* Win/Loss bar + stats + sub-scores in one row */}
      <div className="flex flex-col md:flex-row md:items-center gap-4 pt-4 border-t border-slate-100">
        {/* Win/Loss visual bar */}
        <div className="flex items-center gap-3 md:w-1/3">
          <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden flex">
            <div className="bg-green-500 h-full rounded-l-full" style={{ width: `${winPct}%` }} />
            <div className="bg-red-400 h-full rounded-r-full" style={{ width: `${100 - winPct}%` }} />
          </div>
          <div className="text-xs text-slate-500 shrink-0">
            <span className="text-green-600 font-semibold">{DATA.wins}W</span>
            {" · "}
            <span className="text-red-500 font-semibold">{DATA.losses}L</span>
            {" · "}
            <span className="font-semibold">{DATA.winRate}%</span>
          </div>
        </div>
        {/* Sub-scores */}
        <div className="flex flex-wrap gap-1.5 md:ml-auto">
          {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION D: Dashboard Tiles
// Score tile is 2x size, stats + rating are smaller tiles
// ═══════════════════════════════════════════
function OptionD() {
  return (
    <div className="grid grid-cols-6 gap-2">
      {/* Score (spans 3 cols, 2 rows) */}
      <div className="col-span-6 md:col-span-3 md:row-span-2 border border-slate-200 rounded-xl bg-white shadow-sm p-5 flex flex-col justify-between">
        <div>
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-lg text-slate-400">±{DATA.ci}</span>
          </div>
        </div>
        <div className="mt-4">
          <CIBar {...DATA} />
          <div className="flex justify-between mt-1 text-[10px] text-slate-400">
            <span>{DATA.rangeMin}</span><span>{DATA.rangeMax}</span>
          </div>
        </div>
      </div>
      {/* Win Rate */}
      <div className="col-span-3 md:col-span-1 border border-slate-200 rounded-xl bg-white shadow-sm p-4 text-center">
        <div className="text-2xl font-bold text-slate-900">{DATA.winRate}%</div>
        <div className="text-[10px] text-slate-500 mt-0.5">Win Rate</div>
      </div>
      {/* Wins */}
      <div className="col-span-1 border border-green-200 rounded-xl bg-green-50 shadow-sm p-4 text-center">
        <div className="text-2xl font-bold text-green-600">{DATA.wins}</div>
        <div className="text-[10px] text-slate-500 mt-0.5">Wins</div>
      </div>
      {/* Losses */}
      <div className="col-span-1 border border-red-200 rounded-xl bg-red-50 shadow-sm p-4 text-center">
        <div className="text-2xl font-bold text-red-600">{DATA.losses}</div>
        <div className="text-[10px] text-slate-500 mt-0.5">Losses</div>
      </div>
      {/* Rating */}
      <div className="col-span-3 border border-slate-200 rounded-xl bg-slate-50 shadow-sm p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-1">
            <Target className="h-3 w-3" /> AI Rating
          </div>
          <div className="flex items-baseline gap-0.5">
            <span className="text-2xl font-bold text-slate-700">{DATA.rating}.0</span>
            <span className="text-xs text-slate-400">/10</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {BADGES.map(b => <SubBadge key={b.label} {...b} />)}
        </div>
      </div>
    </div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="max-w-4xl mx-auto p-8 space-y-12">
      <h1 className="text-2xl font-bold text-slate-900">Score Card Options — Tournament Score Emphasized</h1>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option A: Score Hero + Rating Aside</h2>
        <p className="text-sm text-slate-500 mb-3">Tournament score dominates left (60%), CI bar directly beneath it. Rating is secondary on the right.</p>
        <OptionA />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option B: Dark Score Banner</h2>
        <p className="text-sm text-slate-500 mb-3">Dark banner for tournament score + CI. Rating in a light strip below. Strong visual hierarchy.</p>
        <OptionB />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option C: Integrated Gauge</h2>
        <p className="text-sm text-slate-500 mb-3">Score + CI as hero. Rating compact top-right. Win/loss as a colored progress bar. Sub-scores inline.</p>
        <OptionC />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-slate-700 mb-3">Option D: Dashboard Tiles</h2>
        <p className="text-sm text-slate-500 mb-3">Score tile is 2x size. Stats as small tiles. Rating as a compact tile. Asymmetric grid.</p>
        <OptionD />
      </div>
    </div>
  );
}
