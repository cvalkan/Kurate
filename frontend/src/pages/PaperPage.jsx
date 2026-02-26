import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ModelBadge } from "@/components/ModelBadge";
import {
  ArrowLeft, ExternalLink, XCircle, CheckCircle2, Clock, Sparkles, Tag,
} from "lucide-react";
import katex from "katex";
import "katex/dist/katex.min.css";

const API = process.env.REACT_APP_BACKEND_URL;

const SUMMARY_LABELS = {
  anthropic: { label: "Claude", color: "text-orange-500" },
  gemini: { label: "Gemini", color: "text-blue-500" },
  openai: { label: "GPT", color: "text-green-500" },
};

function getSummaryEntries(summaries, summaryDates) {
  if (!summaries || typeof summaries !== "object") return [];
  const dates = summaryDates || {};
  const entries = Object.entries(summaries)
    .map(([key, val]) => {
      const provider = key.split(":")[0];
      const meta = SUMMARY_LABELS[provider] || { label: provider, color: "text-foreground" };
      let text = val;
      if (typeof val === "object" && val !== null) {
        const strs = Object.values(val).filter(v => typeof v === "string" && v.length > 50);
        text = strs.length ? strs.reduce((a, b) => a.length > b.length ? a : b) : "";
      }
      return { key, tabId: provider, provider, text, date: dates[key] || null, ...meta };
    })
    .filter(e => typeof e.text === "string" && e.text.length > 50);
  // Deduplicate by provider — prefer newer model keys (4.6 over 4.5)
  const byProvider = {};
  for (const e of entries) {
    if (!byProvider[e.provider] || e.key > byProvider[e.provider].key) {
      byProvider[e.provider] = e;
    }
  }
  const deduped = Object.values(byProvider);
  // Sort so Claude (anthropic) is first
  const order = { anthropic: 0, openai: 1, gemini: 2 };
  deduped.sort((a, b) => (order[a.provider] ?? 9) - (order[b.provider] ?? 9));
  return deduped;
}

/** Render LaTeX expressions in a string. Handles $...$, $$...$$, \(...\), and \[...\] delimiters. */
function renderLatex(text) {
  if (!text) return text;
  // Block math: $$...$$ 
  let result = text.replace(/\$\$(.+?)\$\$/gs, (_, expr) => {
    try { return katex.renderToString(expr.trim(), { displayMode: true, throwOnError: false }); }
    catch { return `$$${expr}$$`; }
  });
  // Block math: \[...\]
  result = result.replace(/\\\[(.+?)\\\]/gs, (_, expr) => {
    try { return katex.renderToString(expr.trim(), { displayMode: true, throwOnError: false }); }
    catch { return `\\[${expr}\\]`; }
  });
  // Inline math: \(...\)
  result = result.replace(/\\\((.+?)\\\)/g, (_, expr) => {
    try { return katex.renderToString(expr.trim(), { displayMode: false, throwOnError: false }); }
    catch { return `\\(${expr}\\)`; }
  });
  // Inline math: $...$ (but not $$)
  result = result.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, expr) => {
    try { return katex.renderToString(expr.trim(), { displayMode: false, throwOnError: false }); }
    catch { return `$${expr}$`; }
  });
  return result;
}

/** Render a text line with inline bold and LaTeX */
function RenderedLine({ text }) {
  // Apply bold markdown first, then LaTeX
  let html = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = renderLatex(html);
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function SummaryText({ text }) {
  if (!text) return null;
  return (
    <div className="text-sm leading-relaxed space-y-2">
      {text.split("\n").filter(l => l.trim()).map((line, i) => {
        // Markdown headers: ## or ###
        const h2Match = line.match(/^#{1,3}\s+(.+)$/);
        if (h2Match) {
          return <h4 key={i} className="font-heading font-semibold text-sm mt-4 first:mt-0"><RenderedLine text={h2Match[1]} /></h4>;
        }
        // Bold-only lines: **Title**
        const boldMatch = line.match(/^\*\*(.+?)\*\*$/);
        if (boldMatch) {
          return <h4 key={i} className="font-heading font-semibold text-sm mt-4 first:mt-0"><RenderedLine text={boldMatch[1]} /></h4>;
        }
        // Numbered headings: **1. Title**
        const numberedBold = line.match(/^\*\*(\d+[\.\)]\s*.+?)\*\*$/);
        if (numberedBold) {
          return <h4 key={i} className="font-heading font-semibold text-sm mt-3 first:mt-0"><RenderedLine text={numberedBold[1]} /></h4>;
        }
        // Bullet points
        const bulletMatch = line.match(/^[-*]\s+(.+)$/);
        if (bulletMatch) {
          const html = renderLatex(bulletMatch[1].replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"));
          return <li key={i} className="ml-4 list-disc" dangerouslySetInnerHTML={{ __html: html }} />;
        }
        // Regular line with inline formatting + LaTeX
        const html = renderLatex(line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"));
        if (html !== line) {
          return <p key={i} dangerouslySetInnerHTML={{ __html: html }} />;
        }
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

/** Render abstract text with LaTeX support */
function AbstractText({ text }) {
  if (!text) return null;
  const html = renderLatex(text);
  if (html !== text) {
    return <p className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: html }} />;
  }
  return <p className="text-sm leading-relaxed">{text}</p>;
}

export default function PaperPage() {
  const { id } = useParams();
  const navigate = useNavigate();
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
  const summaryEntries = getSummaryEntries(paper.summaries, paper.summary_dates);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-4xl py-6 md:py-10">
      <button onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors" data-testid="back-link">
        <ArrowLeft className="h-4 w-4" />
        Back to Leaderboard
      </button>

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

        {/* Categories */}
        {paper.categories && paper.categories.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mt-3" data-testid="paper-categories">
            <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            {paper.categories.map((cat, i) => (
              <span
                key={cat}
                className={`inline-flex items-center text-[11px] px-2 py-0.5 rounded-md font-mono ${
                  i === 0
                    ? "bg-primary/10 text-primary border border-primary/20 font-medium"
                    : "bg-secondary text-muted-foreground border border-border"
                }`}
                data-testid={`paper-cat-${cat}`}
              >
                {cat}
                {i === 0 && <span className="ml-1 text-[9px] opacity-60">(primary)</span>}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Abstract */}
      {paper.abstract && (
        <div className="mb-8 p-4 bg-secondary/30 rounded-lg border border-border" data-testid="paper-abstract">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Abstract</h3>
          <AbstractText text={paper.abstract} />
        </div>
      )}

      {/* AI Impact Summaries — Tabbed view */}
      {summaryEntries.length > 0 ? (
        <div className="mb-8 p-4 bg-accent/[0.03] rounded-lg border border-accent/20" data-testid="ai-summaries">
          <div className="flex items-center gap-1.5 mb-3">
            <Sparkles className="h-3.5 w-3.5 text-accent" />
            <h3 className="text-xs font-medium text-accent uppercase tracking-wide">AI Impact Assessments</h3>
            <span className="text-[10px] text-muted-foreground ml-1">({summaryEntries.length} models)</span>
          </div>
          <Tabs defaultValue={summaryEntries[0].tabId}>
            <TabsList className="mb-3">
              {summaryEntries.map(e => (
                <TabsTrigger key={e.tabId} value={e.tabId} className="text-xs gap-1.5" data-testid={`summary-tab-${e.provider}`}>
                  <span className={e.color}>{e.label}</span>
                </TabsTrigger>
              ))}
            </TabsList>
            {summaryEntries.map(e => (
              <TabsContent key={e.tabId} value={e.tabId} data-testid={`summary-content-${e.provider}`}>
                <SummaryText text={e.text} />
                {e.date && (
                  <p className="text-[10px] text-muted-foreground mt-3">
                    Generated {new Date(e.date).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
                  </p>
                )}
              </TabsContent>
            ))}
          </Tabs>
        </div>
      ) : paper.impact_summary ? (
        <div className="mb-8 p-4 bg-accent/[0.03] rounded-lg border border-accent/20" data-testid="impact-summary">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              <h3 className="text-xs font-medium text-accent uppercase tracking-wide">AI Impact Assessment</h3>
            </div>
            {paper.summary_model_used && (
              <ModelBadge model={paper.summary_model_used} />
            )}
          </div>
          <SummaryText text={paper.impact_summary} />
          {paper.summary_generated_at && (
            <p className="text-[10px] text-muted-foreground mt-3">
              Generated {new Date(paper.summary_generated_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
            </p>
          )}
        </div>
      ) : null}

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
