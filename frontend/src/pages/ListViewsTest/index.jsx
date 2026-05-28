import { Link } from "react-router-dom";
import { Table2, BarChart3, Grid3x3 } from "lucide-react";
import { useExtendedPapers } from "./_shared";

const VIEWS = [
  {
    slug: "table",
    title: "A — Dense Sortable Table",
    icon: Table2,
    pitch: "Classic spreadsheet feel. Rows = papers, columns = metrics. Cells are color-tinted by value; hover an extended-metric cell to reveal the model's one-sentence justification. Toggle columns on/off and freeze the title column.",
    bestFor: "Power users who already know which metrics they care about.",
  },
  {
    slug: "sparkline",
    title: "C — Sparkline List",
    icon: BarChart3,
    pitch: "Compact list rows with an inline mini bar-chart of all 11 metrics per paper. Color-coded per dimension. Hover any bar for the reasoning popover. Best for skim-scrolling many papers and spotting unusual profiles.",
    bestFor: "Scanning many papers and noticing imbalanced score profiles at a glance.",
  },
  {
    slug: "heatmap",
    title: "D — Heatmap Matrix",
    icon: Grid3x3,
    pitch: "Wide cell grid: rows = papers, columns = metrics, every cell colored from red→green by score. Hover any cell for value + reasoning. Sort by any column. Pattern-spotting view: where do the cold streaks and bright bands fall?",
    bestFor: "Finding outliers and visual patterns across a large set of papers.",
  },
];

export default function ListViewsIndex() {
  const { papers, loading, n } = useExtendedPapers();
  return (
    <div className="container mx-auto max-w-5xl px-4 py-10 space-y-8">
      <div>
        <span className="inline-block text-[10px] font-mono uppercase tracking-wider text-muted-foreground bg-secondary/60 px-2 py-0.5 rounded">Internal · Design Exploration</span>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Extended-Metrics List Views</h1>
        <p className="mt-2 text-sm text-muted-foreground max-w-2xl leading-relaxed">
          Candidate visualizations for browsing papers by the <b>11 directly-extracted summary metrics</b> only
          (no tournament data — no Score/Gap/Confidence). Each extended dimension has a one-sentence justification
          surfaced as a hover tooltip. {loading ? "Loading…" : <>Using <b>{n}</b> papers from the prompt-stability experiment (Claude Opus 4.6, full text).</>}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {VIEWS.map(v => {
          const Icon = v.icon;
          return (
            <Link
              key={v.slug}
              to={`/test/list-views/${v.slug}`}
              className="group border border-border rounded-lg p-5 bg-card hover:border-accent transition-colors flex flex-col gap-3"
              data-testid={`lv-card-${v.slug}`}
            >
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-accent" />
                <h2 className="text-sm font-medium group-hover:text-accent">{v.title}</h2>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed flex-1">{v.pitch}</p>
              <p className="text-[10px] text-muted-foreground border-t border-border/50 pt-2">
                <span className="font-medium text-foreground">Best for:</span> {v.bestFor}
              </p>
            </Link>
          );
        })}
      </div>

      <div className="text-xs text-muted-foreground border-t border-border pt-4 space-y-1">
        <p>
          <b>Shared mechanics</b> across all three views: keyword title search, category multi-filter, per-metric
          minimum-score sliders, hide/show metric columns, include/exclude N/A papers, persistent state per view in localStorage.
        </p>
        <p>
          <b>Note:</b> these pages intentionally exclude tournament-derived signals (TrueSkill score, gap, CI, comparison counts).
          They surface only what the LLM directly returned from the extended summary prompt.
        </p>
      </div>

      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer hover:text-foreground">Loaded paper sample</summary>
        <pre className="mt-2 p-2 rounded bg-secondary/40 overflow-x-auto text-[10px]">
{papers[0] ? JSON.stringify(papers[0], null, 2).slice(0, 800) + "…" : "Loading…"}
        </pre>
      </details>
    </div>
  );
}
