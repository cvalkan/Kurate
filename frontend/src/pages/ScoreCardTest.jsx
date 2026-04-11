import { Target } from "lucide-react";

const DATA = { rating: 8.8, significance: 9.5, rigor: 7.5, novelty: 8, clarity: 8.5 };

const DIMS = [
  { label: "Significance", value: DATA.significance },
  { label: "Rigor", value: DATA.rigor },
  { label: "Novelty", value: DATA.novelty },
  { label: "Clarity", value: DATA.clarity },
];

// A: Uniform light grey with subtle left border accent
function StyleA() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col gap-1.5">
        {DIMS.map(d => (
          <div key={d.label} className="flex items-center justify-between text-xs font-medium px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600">
            <span>{d.label}</span><span className="font-bold text-slate-800">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// B: Clean white rows with bottom border separator
function StyleB() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col">
        {DIMS.map((d, i) => (
          <div key={d.label} className={`flex items-center justify-between text-xs font-medium px-1 py-2 text-slate-600 ${i < DIMS.length - 1 ? "border-b border-slate-200" : ""}`}>
            <span>{d.label}</span><span className="font-bold text-slate-800">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// C: Alternating shades (zebra)
function StyleC() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col rounded-lg overflow-hidden border border-slate-200">
        {DIMS.map((d, i) => (
          <div key={d.label} className={`flex items-center justify-between text-xs font-medium px-3 py-2 ${i % 2 === 0 ? "bg-white" : "bg-slate-50"} text-slate-600`}>
            <span>{d.label}</span><span className="font-bold text-slate-800">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// D: Minimal with score bars
function StyleD() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col gap-2.5">
        {DIMS.map(d => (
          <div key={d.label}>
            <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1">
              <span>{d.label}</span><span className="font-bold text-slate-700">{d.value}</span>
            </div>
            <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div className="h-full bg-slate-400 rounded-full" style={{ width: `${d.value * 10}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// E: Outline border, all same grey
function StyleE() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="flex flex-col gap-1.5">
        {DIMS.map(d => (
          <div key={d.label} className="flex items-center justify-between text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600">
            <span>{d.label}</span><span className="font-bold text-slate-800">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// F: Compact 2x2 grid tiles
function StyleF() {
  return (
    <div className="w-[280px] p-6 bg-slate-50/50 rounded-r-xl">
      <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Target className="h-3.5 w-3.5" /> Rating</div>
      <div className="flex items-baseline gap-1 mb-4"><span className="text-4xl font-bold tracking-tight text-slate-700">{DATA.rating}</span><span className="text-sm text-slate-400">/ 10</span></div>
      <div className="grid grid-cols-2 gap-1.5">
        {DIMS.map(d => (
          <div key={d.label} className="text-center p-2 bg-slate-100 rounded-lg">
            <div className="text-lg font-bold text-slate-800">{d.value}</div>
            <div className="text-[9px] text-slate-500 mt-0.5">{d.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ScoreCardTest() {
  return (
    <div className="max-w-5xl mx-auto p-8">
      <h1 className="text-2xl font-bold text-slate-900 mb-8">Sub-score Style Options (Greyscale)</h1>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-8">
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">A: Uniform grey pills</h3><StyleA /></div>
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">B: Clean rows with separators</h3><StyleB /></div>
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">C: Zebra striping</h3><StyleC /></div>
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">D: Score bars</h3><StyleD /></div>
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">E: Outline border</h3><StyleE /></div>
        <div><h3 className="text-sm font-semibold text-slate-600 mb-3">F: 2x2 grid tiles</h3><StyleF /></div>
      </div>
    </div>
  );
}
