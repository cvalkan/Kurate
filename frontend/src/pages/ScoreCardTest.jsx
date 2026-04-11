import { Trophy, Target, Share2, Award, Medal } from "lucide-react";
import { Link } from "react-router-dom";

const DATA = {
  rating: 8.8, significance: 9.5, rigor: 7.5, novelty: 8, clarity: 8.5,
  wins: 105, losses: 3, matches: 108, winRate: 97,
  score: 1708, ci: 22, rangeMin: 1050, rangeMax: 1800,
  title: "Tight Quantum Lower Bounds for Approximate Counting with Quantum States",
  category: "quant-ph",
};

const TIERS = {
  gold: { name: "Gold", rank: 1, color: "#D4A012", bg: "#FEFCE8", border: "#D4A012" },
  silver: { name: "Silver", rank: 2, color: "#6B7280", bg: "#F3F4F6", border: "#9CA3AF" },
  bronze: { name: "Bronze", rank: 3, color: "#CD7F32", bg: "#FFF7ED", border: "#CD7F32" },
};

function CIBar({ score, ci, rangeMin, rangeMax }) {
  const range = rangeMax - rangeMin || 1;
  const loPct = Math.max(0, ((score - ci - rangeMin) / range) * 100);
  const hiPct = Math.min(100, ((score + ci - rangeMin) / range) * 100);
  const scorePct = ((score - rangeMin) / range) * 100;
  return (
    <div>
      <div className="w-full h-2 bg-slate-100 rounded-full relative">
        <div className="absolute h-full bg-blue-200 rounded-full" style={{ left: `${loPct}%`, width: `${hiPct - loPct}%` }} />
        <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{ left: `${scorePct}%` }} />
      </div>
      <div className="flex justify-between mt-1 text-[10px] text-slate-400"><span>{rangeMin}</span><span>{rangeMax}</span></div>
    </div>
  );
}

const BADGES = [
  { label: "Significance", value: DATA.significance, color: "text-blue-700 bg-blue-50 border-blue-200" },
  { label: "Rigor", value: DATA.rigor, color: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  { label: "Novelty", value: DATA.novelty, color: "text-violet-700 bg-violet-50 border-violet-200" },
  { label: "Clarity", value: DATA.clarity, color: "text-amber-700 bg-amber-50 border-amber-200" },
];

function StatTiles() {
  return (
    <div className="grid grid-cols-4 gap-2 mt-4 pt-4 border-t border-slate-100">
      <div className="text-center p-2.5 bg-slate-50 rounded-lg"><div className="text-xl font-bold text-slate-900">{DATA.winRate}%</div><div className="text-[10px] text-slate-500 mt-0.5">Win Rate</div></div>
      <div className="text-center p-2.5 bg-green-50 rounded-lg"><div className="text-xl font-bold text-green-600">{DATA.wins}</div><div className="text-[10px] text-slate-500 mt-0.5">Wins</div></div>
      <div className="text-center p-2.5 bg-red-50 rounded-lg"><div className="text-xl font-bold text-red-500">{DATA.losses}</div><div className="text-[10px] text-slate-500 mt-0.5">Losses</div></div>
      <div className="text-center p-2.5 bg-slate-50 rounded-lg"><div className="text-xl font-bold text-slate-900">{DATA.matches}</div><div className="text-[10px] text-slate-500 mt-0.5">Matches</div></div>
    </div>
  );
}

function RatingPanel() {
  return (
    <div className="p-6 bg-slate-50/50">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col gap-1.5">
        {BADGES.map(b => (<div key={b.label} className={`flex items-center justify-between text-xs font-medium px-3 py-1.5 rounded-lg border ${b.color}`}><span>{b.label}</span><span className="font-bold">{b.value}</span></div>))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 1: Prestigious Header Bar
// ═══════════════════════════════════════════
function Option1({ tier }) {
  const t = tier ? TIERS[tier] : null;
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {t && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ backgroundColor: t.bg, borderBottomColor: `${t.border}33` }}>
          <div className="flex items-center gap-2">
            <Award className="h-4 w-4" style={{ color: t.color }} />
            <span className="text-sm font-semibold" style={{ color: t.color }}>
              {t.name} Medalist · #{t.rank} in {DATA.category} · Week 15, 2026
            </span>
          </div>
          <button className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border transition-colors hover:opacity-80" style={{ color: t.color, borderColor: `${t.border}44` }} data-testid="share-badge-button">
            <Share2 className="h-3 w-3" /> Share
          </button>
        </div>
      )}
      <div className="flex flex-row">
        <div className="w-[70%] p-6 border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5" /> Tournament Score</div>
          <div className="flex items-baseline gap-2 mb-3"><span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span><span className="text-lg text-slate-400">±{DATA.ci}</span></div>
          <CIBar {...DATA} />
          <StatTiles />
        </div>
        <div className="w-[30%]"><RatingPanel /></div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 2: Inline Pill beside score
// ═══════════════════════════════════════════
function Option2({ tier }) {
  const t = tier ? TIERS[tier] : null;
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="flex flex-row">
        <div className="w-[70%] p-6 border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5" /> Tournament Score</div>
          <div className="flex items-center gap-3 mb-3">
            <div className="flex items-baseline gap-2"><span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span><span className="text-lg text-slate-400">±{DATA.ci}</span></div>
            {t && (
              <a href="#" className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm font-semibold transition-all hover:scale-105" style={{ color: t.color, backgroundColor: `${t.color}15`, borderColor: `${t.border}33` }} data-testid="score-card-badge-pill">
                <Award className="h-3.5 w-3.5" />
                #{t.rank} {DATA.category} · W15
                <Share2 className="h-3 w-3 opacity-50" />
              </a>
            )}
          </div>
          <CIBar {...DATA} />
          <StatTiles />
        </div>
        <div className="w-[30%]"><RatingPanel /></div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 3: Medallion Seal (corner overlay)
// ═══════════════════════════════════════════
function Option3({ tier }) {
  const t = tier ? TIERS[tier] : null;
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="flex flex-row">
        <div className="w-[70%] p-6 border-r border-slate-200 relative">
          {t && (
            <div className="absolute top-4 right-4 group cursor-pointer" data-testid="score-card-medallion">
              <div className="w-14 h-14 rounded-full shadow-lg border-2 border-white flex flex-col items-center justify-center transition-transform group-hover:scale-110" style={{ background: `linear-gradient(135deg, ${t.color}88, ${t.color})` }}>
                <span className="text-white font-bold text-lg leading-none">#{t.rank}</span>
                <span className="text-white/80 text-[8px] font-medium">{t.name}</span>
              </div>
              <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 text-white text-[10px] rounded px-2 py-1 whitespace-nowrap">
                {t.name} · {DATA.category} · Week 15, 2026
                <Share2 className="h-2.5 w-2.5 inline ml-1" />
              </div>
            </div>
          )}
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5" /> Tournament Score</div>
          <div className="flex items-baseline gap-2 mb-3"><span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span><span className="text-lg text-slate-400">±{DATA.ci}</span></div>
          <CIBar {...DATA} />
          <StatTiles />
        </div>
        <div className="w-[30%]"><RatingPanel /></div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// OPTION 4: Medallion on divider
// ═══════════════════════════════════════════
function Option4({ tier }) {
  const t = tier ? TIERS[tier] : null;
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden relative">
      <div className="flex flex-row">
        <div className="w-[70%] p-6 border-r border-slate-200">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5" /> Tournament Score</div>
          <div className="flex items-baseline gap-2 mb-3"><span className="text-5xl font-bold tracking-tight text-slate-900">{DATA.score}</span><span className="text-lg text-slate-400">±{DATA.ci}</span></div>
          <CIBar {...DATA} />
          <StatTiles />
        </div>
        <div className="w-[30%]"><RatingPanel /></div>
      </div>
      {t && (
        <div className="absolute top-6 left-[70%] -translate-x-1/2 z-10 cursor-pointer group" data-testid="score-card-divider-medal">
          <div className="w-12 h-12 rounded-full shadow-xl border-[3px] border-white flex flex-col items-center justify-center transition-transform group-hover:scale-110" style={{ background: `linear-gradient(135deg, ${t.color}88, ${t.color})` }}>
            <span className="text-white font-bold text-base leading-none">#{t.rank}</span>
          </div>
          <div className="text-center mt-0.5"><span className="text-[8px] font-bold uppercase tracking-wider" style={{ color: t.color }}>{t.name}</span></div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// Shareable Badge Card (premium trading card style)
// ═══════════════════════════════════════════
function ShareableCard({ tier }) {
  const t = TIERS[tier];
  const bgImages = {
    gold: "url('https://static.prod-images.emergentagent.com/jobs/e0fcc738-861f-436d-9055-d6287883867d/images/cd22302876e8b36b5ca15a4e802d3cd44ad660119390991adb8612f968669a36.png')",
    silver: "url('https://static.prod-images.emergentagent.com/jobs/e0fcc738-861f-436d-9055-d6287883867d/images/7bed49a70aa265897236478c185031e24f22c421342b74177da582dd2f301cd3.png')",
    bronze: "linear-gradient(135deg, #3f2b1c, #21160e)",
  };
  return (
    <div className="w-full max-w-sm aspect-[3/4] rounded-2xl p-8 flex flex-col justify-between overflow-hidden relative shadow-[0_20px_50px_rgba(0,0,0,0.3)] border border-white/10" style={{ backgroundImage: bgImages[tier], backgroundSize: "cover", backgroundPosition: "center", backgroundColor: "#0a0a0a" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.2em] text-white/40 font-medium">kurate.org</span>
        <div className="backdrop-blur-md bg-white/10 border border-white/20 rounded-full px-3 py-1"><span className="text-xs text-white font-semibold">Score: {DATA.score}</span></div>
      </div>
      {/* Main rank */}
      <div className="text-center my-6">
        <div className="text-[100px] font-black leading-none tracking-tight" style={{ color: t.color, textShadow: `0 4px 30px ${t.color}55` }}>#{t.rank}</div>
        <div className="text-xs uppercase tracking-[0.25em] font-bold mt-2" style={{ color: `${t.color}CC` }}>{t.name} Medalist</div>
      </div>
      {/* Paper details */}
      <div>
        <h3 className="text-lg font-semibold text-white leading-snug mb-2">{DATA.title}</h3>
        <div className="flex items-center gap-2 text-xs text-white/50">
          <span className="px-2 py-0.5 rounded border border-white/20 bg-white/5">{DATA.category}</span>
          <span>Week 15, 2026</span>
        </div>
      </div>
    </div>
  );
}

function Section({ title, desc, children }) {
  return (
    <div className="mb-12">
      <h2 className="text-lg font-semibold text-slate-700 mb-1">{title}</h2>
      {desc && <p className="text-sm text-slate-500 mb-4">{desc}</p>}
      {children}
    </div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="max-w-5xl mx-auto p-8 space-y-4">
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Badge Integration + Shareable Card Designs</h1>

      <Section title="Option 1: Prestigious Header Bar" desc="Full-width tinted bar inside the card. Appears only when badge exists.">
        <div className="space-y-4">
          <Option1 tier="gold" />
          <div className="grid grid-cols-2 gap-4"><Option1 tier="silver" /><Option1 tier="bronze" /></div>
          <div><p className="text-xs text-slate-400 mb-2">Without badge:</p><Option1 tier={null} /></div>
        </div>
      </Section>

      <Section title="Option 2: Inline Pill" desc="Badge sits next to the Tournament Score as a clickable pill.">
        <div className="space-y-4">
          <Option2 tier="gold" />
          <div className="grid grid-cols-2 gap-4"><Option2 tier="silver" /><Option2 tier="bronze" /></div>
          <div><p className="text-xs text-slate-400 mb-2">Without badge:</p><Option2 tier={null} /></div>
        </div>
      </Section>

      <Section title="Option 3: Medallion Seal" desc="Circular medal overlay in the top-right corner. Hover reveals details.">
        <div className="space-y-4">
          <Option3 tier="gold" />
          <div className="grid grid-cols-2 gap-4"><Option3 tier="silver" /><Option3 tier="bronze" /></div>
          <div><p className="text-xs text-slate-400 mb-2">Without badge:</p><Option3 tier={null} /></div>
        </div>
      </Section>

      <Section title="Option 4: Divider Medallion" desc="Medal sits on the divider between Tournament and Rating panels.">
        <div className="space-y-4">
          <Option4 tier="gold" />
          <div className="grid grid-cols-2 gap-4"><Option4 tier="silver" /><Option4 tier="bronze" /></div>
          <div><p className="text-xs text-slate-400 mb-2">Without badge:</p><Option4 tier={null} /></div>
        </div>
      </Section>

      <Section title="Shareable Badge Cards" desc="Premium trading-card style for the /badge/ sharing page.">
        <div className="flex gap-6 flex-wrap">
          <ShareableCard tier="gold" />
          <ShareableCard tier="silver" />
          <ShareableCard tier="bronze" />
        </div>
      </Section>
    </div>
  );
}
