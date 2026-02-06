import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Trophy, Clock, Calendar, CalendarDays, Infinity,
  ChevronUp, ChevronDown, Minus, ExternalLink, Activity, Users, Swords,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const PERIODS = [
  { key: "today", label: "Today", icon: Clock },
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

function ConfidenceBar({ confidence }) {
  if (!confidence || confidence.comparisons === 0) return <span className="text-xs text-muted-foreground font-mono">--</span>;
  const pct = Math.round(confidence.win_rate * 100);
  const lo = Math.round(confidence.lower_bound * 100);
  const hi = Math.round(confidence.upper_bound * 100);
  return (
    <div className="flex items-center gap-2" data-testid="confidence-bar">
      <div className="w-16 h-1.5 bg-slate-100 rounded-full relative overflow-hidden">
        <div
          className="absolute h-full bg-accent/30 rounded-full"
          style={{ left: `${lo}%`, width: `${hi - lo}%` }}
        />
        <div
          className="absolute h-full w-1 bg-accent rounded-full"
          style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
        />
      </div>
      <span className="font-mono text-xs text-muted-foreground">{pct}%</span>
    </div>
  );
}

export default function LeaderboardPage() {
  const [leaderboard, setLeaderboard] = useState([]);
  const [status, setStatus] = useState(null);
  const [period, setPeriod] = useState("all");
  const [loading, setLoading] = useState(true);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);

  const fetchLeaderboard = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/leaderboard`, { params: { period } });
      setLeaderboard(res.data.leaderboard || []);
      setTotalPapers(res.data.total_papers || 0);
      setTotalMatches(res.data.total_matches || 0);
    } catch (err) {
      console.error("Failed to fetch leaderboard:", err);
    } finally {
      setLoading(false);
    }
  }, [period]);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/status`);
      setStatus(res.data);
    } catch (err) {
      console.error("Failed to fetch status:", err);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchLeaderboard();
  }, [fetchLeaderboard]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(() => {
      fetchLeaderboard();
      fetchStatus();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchLeaderboard, fetchStatus]);

  const isProcessing = status?.scheduler?.is_processing || status?.scheduler?.is_fetching;

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Robotics Paper Rankings
        </h1>
        <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
          AI-powered ranking of the latest arXiv Robotics papers, updated daily.
          Papers are compared using GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.
        </p>
      </div>

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
        {status?.scheduler?.last_fetch_at && (
          <>
            <div className="w-px h-3 bg-border" />
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>Last fetch: {new Date(status.scheduler.last_fetch_at).toLocaleDateString()}</span>
            </div>
          </>
        )}
        {isProcessing && (
          <>
            <div className="w-px h-3 bg-border" />
            <Badge variant="outline" className="text-xs gap-1 animate-pulse border-accent text-accent">
              <Activity className="h-3 w-3" />
              {status?.scheduler?.current_activity || "Processing..."}
            </Badge>
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
          <div className="grid grid-cols-[3rem_1fr_5rem_5rem_5rem] md:grid-cols-[3rem_1fr_6rem_6rem_5rem_7rem] gap-2 px-3 md:px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border">
            <div>#</div>
            <div>Paper</div>
            <div className="text-right">BT Score</div>
            <div className="text-right">Win Rate</div>
            <div className="text-right">Matches</div>
            <div className="text-right hidden md:block">Published</div>
          </div>

          {/* Table Body */}
          {leaderboard.map((paper, idx) => (
            <Link
              key={paper.id}
              to={`/paper/${paper.id}`}
              className={`grid grid-cols-[3rem_1fr_5rem_5rem_5rem] md:grid-cols-[3rem_1fr_6rem_6rem_5rem_7rem] gap-2 px-3 md:px-4 py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${
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
              <div className="text-right font-mono text-sm font-medium">{paper.bt_score.toFixed(2)}</div>
              <div className="text-right">
                <ConfidenceBar confidence={paper.confidence} />
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
        Rankings computed using Bradley-Terry model with Wilson confidence intervals.
        Papers compared using full-text deep analysis.
      </div>
    </div>
  );
}
