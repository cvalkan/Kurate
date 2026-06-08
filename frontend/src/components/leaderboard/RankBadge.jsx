export function RankBadge({ rank }) {
  return (
    <span
      className="inline-flex items-center justify-center w-7 h-7 font-serif text-base font-medium text-blue-600"
      data-testid={`rank-${rank}`}
    >
      {rank}
    </span>
  );
}
