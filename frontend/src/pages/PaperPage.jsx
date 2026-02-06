import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, ExternalLink, Trophy, XCircle, CheckCircle2, Clock, Bot,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function ModelBadge({ model }) {
  if (!model || !model.provider) return null;
  const colors = {
    openai: "bg-green-50 text-green-700 border-green-200",
    anthropic: "bg-orange-50 text-orange-700 border-orange-200",
    gemini: "bg-blue-50 text-blue-700 border-blue-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border ${colors[model.provider] || "bg-secondary text-muted-foreground border-border"}`}>
      <Bot className="h-2.5 w-2.5" />
      {model.model?.split("-").slice(0, 2).join("-") || model.provider}
    </span>
  );
}

export default function PaperPage() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchPaper = async () => {
      try {
        const res = await axios.get(`${API}/api/papers/${id}`);
        setData(res.data);
      } catch (err) {
        console.error("Failed to fetch paper:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchPaper();
  }, [id]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-4xl py-10">
        <div className="space-y-4">
          <div className="h-8 w-48 bg-secondary/50 rounded animate-pulse" />
          <div className="h-6 w-full bg-secondary/50 rounded animate-pulse" />
          <div className="h-40 bg-secondary/50 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-4xl py-10 text-center text-muted-foreground">
        Paper not found.
      </div>
    );
  }

  const { paper, matches, stats } = data;
  const winRate = stats.comparisons > 0 ? Math.round((stats.wins / stats.comparisons) * 100) : 0;

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-4xl py-6 md:py-10">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors" data-testid="back-link">
        <ArrowLeft className="h-4 w-4" />
        Back to Leaderboard
      </Link>

      {/* Paper Header */}
      <div className="mb-8" data-testid="paper-header">
        <h1 className="font-heading text-xl md:text-2xl font-semibold tracking-tight mb-3 leading-tight">
          {paper.title}
        </h1>
        <p className="text-sm text-muted-foreground mb-3">
          {paper.authors?.join(", ")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {paper.published && (
            <Badge variant="outline" className="text-xs gap-1">
              <Clock className="h-3 w-3" />
              {new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
            </Badge>
          )}
          {paper.arxiv_id && (
            <a
              href={paper.link || `https://arxiv.org/abs/${paper.arxiv_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
              data-testid="arxiv-link"
            >
              arXiv:{paper.arxiv_id}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>

      {/* Abstract */}
      {paper.abstract && (
        <div className="mb-8 p-4 bg-secondary/30 rounded-lg border border-border" data-testid="paper-abstract">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Abstract</h3>
          <p className="text-sm leading-relaxed">{paper.abstract}</p>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8" data-testid="paper-stats">
        <div className="p-3 bg-secondary/30 rounded-lg border border-border text-center">
          <div className="font-mono text-2xl font-bold text-green-600">{stats.wins}</div>
          <div className="text-xs text-muted-foreground mt-1">Wins</div>
        </div>
        <div className="p-3 bg-secondary/30 rounded-lg border border-border text-center">
          <div className="font-mono text-2xl font-bold text-red-500">{stats.losses}</div>
          <div className="text-xs text-muted-foreground mt-1">Losses</div>
        </div>
        <div className="p-3 bg-secondary/30 rounded-lg border border-border text-center">
          <div className="font-mono text-2xl font-bold">{stats.comparisons}</div>
          <div className="text-xs text-muted-foreground mt-1">Matches</div>
        </div>
        <div className="p-3 bg-secondary/30 rounded-lg border border-border text-center">
          <div className="font-mono text-2xl font-bold text-accent">{winRate}%</div>
          <div className="text-xs text-muted-foreground mt-1">Win Rate</div>
        </div>
      </div>

      {/* Confidence */}
      {stats.confidence && stats.confidence.comparisons > 0 && (
        <div className="mb-8 p-4 bg-secondary/30 rounded-lg border border-border" data-testid="confidence-details">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">Confidence Interval (95%)</h3>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">{Math.round(stats.confidence.lower_bound * 100)}%</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full relative overflow-hidden">
              <div
                className="absolute h-full bg-accent/20 rounded-full"
                style={{
                  left: `${stats.confidence.lower_bound * 100}%`,
                  width: `${(stats.confidence.upper_bound - stats.confidence.lower_bound) * 100}%`,
                }}
              />
              <div
                className="absolute h-full w-1.5 bg-accent rounded-full"
                style={{ left: `${stats.confidence.win_rate * 100}%`, transform: "translateX(-50%)" }}
              />
            </div>
            <span className="font-mono text-xs text-muted-foreground">{Math.round(stats.confidence.upper_bound * 100)}%</span>
          </div>
        </div>
      )}

      {/* Comparison Logs */}
      <div data-testid="comparison-logs">
        <h2 className="font-heading text-lg font-medium mb-4">
          Comparison History ({matches.length})
        </h2>

        {matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">No comparisons yet.</p>
        ) : (
          <div className="space-y-2">
            {matches.filter(m => !m.failed).map((match) => (
              <div
                key={match.id}
                className="p-3 border border-border rounded-lg hover:bg-secondary/20 transition-colors"
                data-testid={`match-${match.id}`}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    {match.won ? (
                      <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                    )}
                    <span className="text-sm truncate">
                      vs. <span className="font-medium">{match.opponent_title}</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <ModelBadge model={match.model_used} />
                    {match.created_at && (
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {new Date(match.created_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
                {match.reasoning && (
                  <p className="text-xs text-muted-foreground leading-relaxed pl-6">
                    {match.reasoning}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
