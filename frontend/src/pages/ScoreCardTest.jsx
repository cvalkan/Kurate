import { Trophy, Target, Share2, Award } from "lucide-react";

const TIER_COLORS = {
  Gold: { color: "#D4A012", bg: "#FEFCE8" },
  Silver: { color: "#6B7280", bg: "#F3F4F6" },
  Bronze: { color: "#CD7F32", bg: "#FFF7ED" },
};

function BadgeHeader({ tier, rank, categoryName, archiveLabel }) {
  const tc = TIER_COLORS[tier];
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden mb-4">
      <a href="#" className="flex items-center justify-between px-4 py-2.5 border-b transition-opacity hover:opacity-80" style={{ backgroundColor: tc.bg, borderBottomColor: `${tc.color}33` }}>
        <div className="flex items-center gap-2">
          <Award className="h-4 w-4" style={{ color: tc.color }} />
          <span className="text-sm font-semibold" style={{ color: tc.color }}>
            {tier} · #{rank} in {categoryName} · {archiveLabel}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-sm font-semibold px-3 py-1 rounded-full border" style={{ color: tc.color, borderColor: `${tc.color}44` }}>
          <Share2 className="h-3.5 w-3.5" /> Share
        </div>
      </a>
      <div className="p-6 text-sm text-slate-500">Score card content would go here...</div>
    </div>
  );
}

function NoBadgeHeader() {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden mb-4">
      <div className="flex items-center justify-between px-4 py-2 border-b bg-slate-50/80">
        <span className="text-xs text-slate-500">cs.RO</span>
        <button className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 px-2.5 py-1 rounded-full border border-slate-200 hover:border-slate-300 transition-colors">
          <Share2 className="h-3 w-3" /> Share
        </button>
      </div>
      <div className="p-6 text-sm text-slate-500">Score card content (no badge)...</div>
    </div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="max-w-4xl mx-auto p-8 space-y-2">
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Badge Header — Final Design</h1>
      <BadgeHeader tier="Gold" rank={1} categoryName="Quantum Physics" archiveLabel="Week 15, 2026" />
      <BadgeHeader tier="Silver" rank={2} categoryName="Robotics" archiveLabel="Week 14, 2026" />
      <BadgeHeader tier="Bronze" rank={3} categoryName="Information Theory" archiveLabel="Week 13, 2026" />
      <NoBadgeHeader />
    </div>
  );
}
