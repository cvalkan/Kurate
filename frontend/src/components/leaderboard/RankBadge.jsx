export function RankBadge({ rank, isSorted = false }) {
  if (!isSorted && rank === 1) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-amber-100 text-amber-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>1</span>;
  if (!isSorted && rank === 2) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-slate-100 text-slate-600 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>2</span>;
  if (!isSorted && rank === 3) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-orange-100 text-orange-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>3</span>;
  return <span className="inline-flex items-center justify-center w-7 h-7 font-mono text-sm text-muted-foreground" data-testid={`rank-${rank}`}>{rank}</span>;
}
