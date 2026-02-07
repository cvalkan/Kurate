import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import {
  Trophy, Clock, Calendar, CalendarDays, Infinity,
  Users, Swords, Activity,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const PERIODS = [
  { key: "recent", label: "Most Recent", icon: Clock },
  { key: "week", label: "This Week", icon: Calendar },
  { key: "month", label: "This Month", icon: CalendarDays },
  { key: "all", label: "All Time", icon: Infinity },
];

function RankBadge({ rank }) {
  if (rank === 1) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-amber-100 text-amber-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>1</span>;
  if (rank === 2) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-slate-100 text-slate-600 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>2</span>;
  if (rank === 3) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-orange-100 text-orange-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>3</span>;
  return <span className="inline-flex items-center justify-center w-7 h-7 font-mono text-sm text-muted-foreground" data-testid={`rank-${rank}`}>{rank}</span>;
}

export default function LeaderboardPage() {
  const [leaderboard, setLeaderboard] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");
  const [period, setPeriod] = useState("week");
  const [loading, setLoading] = useState(true);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [isRanking, setIsRanking] = useState(false);

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";

  // Load categories once
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      setCategory(res.data.default || "cs.RO");
    }).catch(() => {
      setCategories([{ id: "cs.RO", name: "Robotics" }]);
      setCategory("cs.RO");
    });
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    if (!category) return;
    try {
      const res = await axios.get(`${API}/api/leaderboard`, { params: { category, period } });
      setLeaderboard(res.data.leaderboard || []);
      setTotalPapers(res.data.total_papers || 0);
      setTotalMatches(res.data.total_matches || 0);
      setIsRanking(res.data.is_ranking || false);
    } catch (err) {
      console.error("Failed to fetch leaderboard:", err);
    } finally {
      setLoading(false);
    }
  }, [category, period]);

  useEffect(() => {
    fetchLeaderboard();
  }, [fetchLeaderboard]);

  useEffect(() => {
    const interval = setInterval(fetchLeaderboard, 30000);
    return () => clearInterval(interval);
  }, [fetchLeaderboard]);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          {categoryName} Paper Rankings
        </h1>
        <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
          AI-estimated scientific impact ranking of the latest arXiv {categoryName} papers.
          Papers are evaluated using full-text analysis by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.
        </p>
      </div>

      {/* Category Tabs */}
      {categories.length > 1 && (
        <div className="flex items-center gap-1 mb-4 p-1 bg-primary/5 rounded-lg w-fit" data-testid="category-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={category === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => { setCategory(c.id); setLoading(true); }}
              className="text-xs h-8"
              data-testid={`cat-${c.id}`}
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      {/* Status Bar */}
      <div className="flex flex-wrap items-center gap-3 mb-6 text-xs" data-testid="status-bar">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Users className="h-3.5 w-3.5" />
          <span className="font-mono">{totalPapers}</span>
          <span>papers</span>
        </div>
        <div className="w-px h-3 bg-border" />
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Swords className="h-3.5 w-3.5" />
          <span className="font-mono">{totalMatches}</span>
          <span>comparisons</span>
        </div>
        {isRanking && (
          <>
            <div className="w-px h-3 bg-border" />
            <span className="inline-flex items-center gap-1 text-xs text-accent animate-pulse">
              <Activity className="h-3 w-3" />
              Ranking in progress
            </span>
          </>
        )}
      </div>

      {/* Period Filter */}
      <div className="flex items-center gap-1 mb-6 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="period-filter">
        {PERIODS.map((p) => {
          const Icon = p.icon;
          return (
            <Button
              key={p.key}
              variant={period === p.key ? "default" : "ghost"}
              size="sm"
              onClick={() => setPeriod(p.key)}
              className="gap-1.5 text-xs h-8"
              data-testid={`filter-${p.key}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {p.label}
            </Button>
          );
        })}
      </div>

      {/* Leaderboard Table */}
      {loading ? (
        <div className="space-y-3" data-testid="loading-skeleton">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : leaderboard.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground" data-testid="empty-state">
          <Trophy className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No papers found for this period.</p>
          <p className="text-xs mt-1">Try a broader time range or wait for the next daily fetch.</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="leaderboard-table">
          {/* Table Header */}
          <div className="grid grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem] gap-2 px-3 md:px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border">
            <div>#</div>
            <div>Paper</div>
            <div className="text-right">Score</div>
            <div className="text-right">Win %</div>
            <div className="text-right">95% CI</div>
            <div className="text-right">Matches</div>
            <div className="text-right hidden md:block">Published</div>
          </div>

          {/* Table Body */}
          {leaderboard.map((paper, idx) => (
            <Link
              key={paper.id}
              to={`/paper/${paper.id}`}
              className={`grid grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem] gap-2 px-3 md:px-4 py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${
                idx < 3 ? "bg-accent/[0.02]" : ""
              }`}
              data-testid={`leaderboard-row-${idx}`}
            >
              <div><RankBadge rank={paper.rank} /></div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate leading-tight" title={paper.title}>
                  {paper.title}
                </p>
                <p className="text-xs text-muted-foreground truncate mt-0.5">
                  {paper.authors?.slice(0, 3).join(", ")}
                  {paper.authors?.length > 3 && ` +${paper.authors.length - 3}`}
                </p>
              </div>
              <div className="text-right font-mono text-sm font-medium">{paper.score}</div>
              <div className="text-right font-mono text-xs text-muted-foreground">{paper.win_rate}%</div>
              <div className="text-right font-mono text-xs text-muted-foreground">
                {paper.wilson_margin > 0 ? `\u00B1${paper.wilson_margin}%` : "--"}
              </div>
              <div className="text-right font-mono text-xs text-muted-foreground">{paper.comparisons}</div>
              <div className="text-right text-xs text-muted-foreground hidden md:block">
                {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "--"}
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Footer Info */}
      <div className="mt-6 text-center text-xs text-muted-foreground">
        Elo-style ratings from Bradley-Terry model with 95% confidence intervals.
        Papers compared using full-text deep analysis.
      </div>
    </div>
  );
}
