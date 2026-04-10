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

const BADGES = [
  { label: "Significance", value: DATA.significance, color: "text-blue-700 bg-blue-50 border-blue-200" },
  { label: "Rigor", value: DATA.rigor, color: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  { label: "Novelty", value: DATA.novelty, color: "text-violet-700 bg-violet-50 border-violet-200" },
  { label: "Clarity", value: DATA.clarity, color: "text-amber-700 bg-amber-50 border-amber-200" },
];

// ═══════════════════════════════════════════
// E2 — Desktop/Tablet: side-by-side 70/30
//       Mobile: stacked, redesigned for narrow screens
// ═══════════════════════════════════════════
function E2() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {/* Desktop/Tablet: side-by-side */}
      <div className="hidden md:flex flex-row">
        <div className="w-[70%] p-6 border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-2 mb-3">
            <span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-lg text-slate-400">±{DATA.ci}</span>
          </div>
          <CIBar {...DATA} />
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
        <div className="w-[30%] p-6 bg-slate-50/50">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Target className="h-3.5 w-3.5" /> AI Rating
          </div>
          <div className="flex items-baseline gap-1 mb-4">
            <span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}.0</span>
            <span className="text-sm text-slate-400">/ 10</span>
          </div>
          <div className="flex flex-col gap-1.5">
            {BADGES.map(b => (
              <div key={b.label} className={`flex items-center justify-between text-xs font-medium px-3 py-1.5 rounded-lg border ${b.color}`}>
                <span>{b.label}</span>
                <span className="font-bold">{b.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Mobile: stacked layout */}
      <div className="md:hidden">
        {/* Tournament Score */}
        <div className="p-5">
          <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <Trophy className="h-3 w-3" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-1.5 mb-2.5">
            <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-base text-slate-400">±{DATA.ci}</span>
          </div>
          <CIBar {...DATA} />
          <div className="grid grid-cols-3 gap-1.5 mt-3 pt-3 border-t border-slate-100">
            <div className="text-center py-2 bg-slate-50 rounded-lg">
              <div className="text-lg font-bold text-slate-900">{DATA.winRate}%</div>
              <div className="text-[9px] text-slate-500">Win Rate</div>
            </div>
            <div className="text-center py-2 bg-green-50 rounded-lg">
              <div className="text-lg font-bold text-green-600">{DATA.wins}</div>
              <div className="text-[9px] text-slate-500">Wins</div>
            </div>
            <div className="text-center py-2 bg-red-50 rounded-lg">
              <div className="text-lg font-bold text-red-500">{DATA.losses}</div>
              <div className="text-[9px] text-slate-500">Losses</div>
            </div>
          </div>
        </div>
        {/* AI Rating */}
        <div className="p-5 pt-0">
          <div className="border-t border-slate-200 pt-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5">
                <Target className="h-3 w-3 text-slate-500" />
                <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">AI Rating</span>
              </div>
              <div className="flex items-baseline gap-0.5">
                <span className="text-2xl font-bold text-slate-700">{DATA.rating}.0</span>
                <span className="text-xs text-slate-400">/ 10</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {BADGES.map(b => (
                <div key={b.label} className={`flex items-center justify-between text-[11px] font-medium px-2.5 py-1.5 rounded-lg border ${b.color}`}>
                  <span>{b.label}</span>
                  <span className="font-bold">{b.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ViewportLabel({ label }) {
  return (
    <div className="text-center text-xs font-medium text-slate-400 uppercase tracking-wider mb-3 mt-10 border-b border-slate-200 pb-2">{label}</div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">E2 — Final with Mobile Fix</h1>

      <ViewportLabel label="Desktop (full width)" />
      <div className="max-w-4xl mx-auto">
        <E2 />
      </div>

      <ViewportLabel label="Tablet (640px)" />
      <div className="max-w-[640px] mx-auto">
        <E2 />
      </div>

      <ViewportLabel label="Mobile (375px) — actual viewport simulation" />
      <p className="text-xs text-slate-500 text-center">Note: To see the true mobile layout, resize your browser to &lt;768px. Below is the mobile-specific layout rendered directly.</p>

      {/* Force mobile layout by rendering only the mobile portion */}
      <div className="max-w-[375px] mx-auto border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
        <div className="p-5">
          <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
            <Trophy className="h-3 w-3" /> Tournament Score
          </div>
          <div className="flex items-baseline gap-1.5 mb-2.5">
            <span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.score}</span>
            <span className="text-base text-slate-400">±{DATA.ci}</span>
          </div>
          <CIBar {...DATA} />
          <div className="grid grid-cols-3 gap-1.5 mt-3 pt-3 border-t border-slate-100">
            <div className="text-center py-2 bg-slate-50 rounded-lg">
              <div className="text-lg font-bold text-slate-900">{DATA.winRate}%</div>
              <div className="text-[9px] text-slate-500">Win Rate</div>
            </div>
            <div className="text-center py-2 bg-green-50 rounded-lg">
              <div className="text-lg font-bold text-green-600">{DATA.wins}</div>
              <div className="text-[9px] text-slate-500">Wins</div>
            </div>
            <div className="text-center py-2 bg-red-50 rounded-lg">
              <div className="text-lg font-bold text-red-500">{DATA.losses}</div>
              <div className="text-[9px] text-slate-500">Losses</div>
            </div>
          </div>
        </div>
        <div className="p-5 pt-0">
          <div className="border-t border-slate-200 pt-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5">
                <Target className="h-3 w-3 text-slate-500" />
                <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">AI Rating</span>
              </div>
              <div className="flex items-baseline gap-0.5">
                <span className="text-2xl font-bold text-slate-700">{DATA.rating}.0</span>
                <span className="text-xs text-slate-400">/ 10</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {BADGES.map(b => (
                <div key={b.label} className={`flex items-center justify-between text-[11px] font-medium px-2.5 py-1.5 rounded-lg border ${b.color}`}>
                  <span>{b.label}</span>
                  <span className="font-bold">{b.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
