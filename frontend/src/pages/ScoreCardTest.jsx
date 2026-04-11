import { Trophy, Target, Share2, Award, Hash, BarChart2 } from "lucide-react";

const DATA = {
  score: 1708, ci: 22, rangeMin: 1050, rangeMax: 1800,
  rating: 8.8, significance: 9.5, rigor: 7.5, novelty: 8, clarity: 8.5,
  wins: 105, losses: 3, matches: 108, winRate: 97,
};

// Scenarios
const BADGE_GOLD = { tier: "Gold", rank: 1, color: "#D4A012", bg: "#FEFCE8", category_name: "Quantum Physics", archive_label: "Week 15, 2026" };
const BADGE_SILVER = { tier: "Silver", rank: 2, color: "#6B7280", bg: "#F3F4F6", category_name: "Robotics", archive_label: "Week 14, 2026" };
const NO_BADGE = null;

function Header({ badge, currentRank, totalPapers, categoryName }) {
  return null; // placeholder
}

// ═══════════════════════════════════════════
// VARIANT A: Full-width bar, rank left, badge right
// ═══════════════════════════════════════════
function VariantA({ badge, currentRank, totalPapers, categoryName }) {
  const hasBadge = !!badge;
  return (
    <div className={`flex items-center justify-between px-4 py-2.5 border-b ${hasBadge ? "" : "bg-slate-50"}`}
      style={hasBadge ? { backgroundColor: badge.bg, borderBottomColor: `${badge.color}33` } : {}}>
      <div className="flex items-center gap-2.5">
        <div className="flex items-center gap-1.5 text-sm">
          <Hash className="h-3.5 w-3.5 text-slate-400" />
          <span className="font-bold text-slate-900">{currentRank}</span>
          <span className="text-slate-400">of {totalPapers}</span>
          <span className="text-slate-300 mx-1">·</span>
          <span className="text-slate-500">{categoryName}</span>
        </div>
      </div>
      {hasBadge && (
        <a href="#" className="flex items-center gap-1.5 text-sm font-semibold transition-opacity hover:opacity-80" style={{ color: badge.color }}>
          <Award className="h-4 w-4" />
          {badge.tier} · Week 15
          <Share2 className="h-3 w-3 opacity-50 ml-1" />
        </a>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// VARIANT B: Rank as large number, category + badge inline
// ═══════════════════════════════════════════
function VariantB({ badge, currentRank, totalPapers, categoryName }) {
  const hasBadge = !!badge;
  return (
    <div className={`flex items-center gap-4 px-4 py-2.5 border-b ${hasBadge ? "" : "bg-slate-50"}`}
      style={hasBadge ? { backgroundColor: badge.bg, borderBottomColor: `${badge.color}33` } : {}}>
      <div className="flex items-baseline gap-0.5">
        <span className="text-2xl font-black text-slate-900">#{currentRank}</span>
        <span className="text-xs text-slate-400">/{totalPapers}</span>
      </div>
      <div className="text-xs text-slate-500">{categoryName}</div>
      <div className="flex-1" />
      {hasBadge && (
        <a href="#" className="flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-semibold transition-opacity hover:opacity-80"
          style={{ color: badge.color, borderColor: `${badge.color}44`, backgroundColor: `${badge.color}08` }}>
          <Award className="h-3.5 w-3.5" />
          {badge.tier} · {badge.archive_label}
          <Share2 className="h-3 w-3 opacity-40" />
        </a>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// VARIANT C: Rank pill left, category center, badge pill right
// ═══════════════════════════════════════════
function VariantC({ badge, currentRank, totalPapers, categoryName }) {
  const hasBadge = !!badge;
  return (
    <div className={`flex items-center justify-between px-4 py-2 border-b ${hasBadge ? "" : "bg-slate-50/80"}`}
      style={hasBadge ? { backgroundColor: badge.bg, borderBottomColor: `${badge.color}33` } : {}}>
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 bg-slate-900 text-white text-xs font-bold px-2.5 py-1 rounded-full">
          #{currentRank}
          <span className="text-slate-400 font-normal">/ {totalPapers}</span>
        </span>
        <span className="text-xs text-slate-500">{categoryName}</span>
      </div>
      {hasBadge && (
        <a href="#" className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold transition-opacity hover:opacity-80"
          style={{ color: badge.color, backgroundColor: `${badge.color}15` }}>
          <Award className="h-3.5 w-3.5" />
          {badge.tier} · {badge.archive_label}
          <Share2 className="h-3 w-3 opacity-40" />
        </a>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// VARIANT D: Minimal — thin bar with rank and optional badge
// ═══════════════════════════════════════════
function VariantD({ badge, currentRank, totalPapers, categoryName }) {
  const hasBadge = !!badge;
  return (
    <div className={`flex items-center justify-between px-4 py-1.5 border-b text-xs ${hasBadge ? "" : "bg-slate-50/60"}`}
      style={hasBadge ? { backgroundColor: badge.bg, borderBottomColor: `${badge.color}33` } : {}}>
      <span className="text-slate-500">
        Ranked <span className="font-bold text-slate-900">#{currentRank}</span> of {totalPapers} in {categoryName}
      </span>
      {hasBadge && (
        <a href="#" className="flex items-center gap-1 font-semibold transition-opacity hover:opacity-80" style={{ color: badge.color }}>
          <Award className="h-3.5 w-3.5" />
          {badge.tier} · {badge.archive_label}
          <Share2 className="h-2.5 w-2.5 opacity-40 ml-0.5" />
        </a>
      )}
    </div>
  );
}

function ScoreCardBody() {
  return (
    <div className="flex flex-row">
      <div className="w-[70%] p-5 border-r border-slate-200">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5" /> Tournament Score</div>
        <div className="flex items-baseline gap-2 mb-2"><span className="text-4xl font-bold tracking-tight text-slate-900">{DATA.score}</span><span className="text-lg text-slate-400">±{DATA.ci}</span></div>
        <div className="h-2 bg-slate-100 rounded-full relative mb-3">
          <div className="absolute h-full bg-blue-200 rounded-full" style={{ left: "60%", width: "8%" }} />
          <div className="absolute h-3 w-3 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{ left: "64%" }} />
        </div>
        <div className="grid grid-cols-4 gap-2 pt-3 border-t border-slate-100">
          <div className="text-center p-2 bg-slate-50 rounded-lg"><div className="text-lg font-bold text-slate-900">{DATA.winRate}%</div><div className="text-[9px] text-slate-500">Win Rate</div></div>
          <div className="text-center p-2 bg-green-50 rounded-lg"><div className="text-lg font-bold text-green-600">{DATA.wins}</div><div className="text-[9px] text-slate-500">Wins</div></div>
          <div className="text-center p-2 bg-red-50 rounded-lg"><div className="text-lg font-bold text-red-500">{DATA.losses}</div><div className="text-[9px] text-slate-500">Losses</div></div>
          <div className="text-center p-2 bg-slate-50 rounded-lg"><div className="text-lg font-bold text-slate-900">{DATA.matches}</div><div className="text-[9px] text-slate-500">Matches</div></div>
        </div>
      </div>
      <div className="w-[30%] p-5 bg-slate-50/50">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2"><Target className="h-3.5 w-3.5 inline mr-1" />Rating</div>
        <div className="flex items-baseline gap-1 mb-3"><span className="text-3xl font-bold text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/10</span></div>
        <div className="flex flex-col gap-2">
          {[["Significance", 9.5], ["Rigor", 7.5], ["Novelty", 8], ["Clarity", 8.5]].map(([l, v]) => (
            <div key={l}><div className="flex justify-between text-[10px] text-slate-500 mb-0.5"><span>{l}</span><span className="font-bold text-slate-700">{v}</span></div><div className="h-1.5 bg-slate-200 rounded-full overflow-hidden"><div className="h-full bg-slate-400 rounded-full" style={{ width: `${v * 10}%` }} /></div></div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Card({ Variant, badge, rank, total, cat, label }) {
  return (
    <div className="mb-3">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
        <Variant badge={badge} currentRank={rank} totalPapers={total} categoryName={cat} />
        <ScoreCardBody />
      </div>
    </div>
  );
}

export default function ScoreCardTest() {
  const variants = [
    { name: "A: Rank left, badge right", Comp: VariantA },
    { name: "B: Large rank number + pill badge", Comp: VariantB },
    { name: "C: Rank pill + badge pill", Comp: VariantC },
    { name: "D: Minimal text bar", Comp: VariantD },
  ];

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-12">
      <h1 className="text-2xl font-bold text-slate-900">Score Card Header — Rank + Badge Integration</h1>

      {variants.map(({ name, Comp }) => (
        <div key={name}>
          <h2 className="text-lg font-semibold text-slate-700 mb-3">{name}</h2>
          <div className="space-y-4">
            <Card Variant={Comp} badge={BADGE_GOLD} rank={1} total={507} cat="Quantum Physics" label="Gold #1 badge" />
            <Card Variant={Comp} badge={BADGE_SILVER} rank={2} total={1736} cat="Robotics" label="Silver #2 badge" />
            <Card Variant={Comp} badge={NO_BADGE} rank={43} total={234} cat="Information Theory" label="No badge — just rank" />
          </div>
        </div>
      ))}
    </div>
  );
}
