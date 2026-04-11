import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import DOMPurify from "dompurify";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { ModelBadge } from "@/components/ModelBadge";
import {
  ArrowLeft, ExternalLink, XCircle, CheckCircle2, Clock, Sparkles, Tag, Trophy, Share2, Bookmark, Target, Award,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
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
  return <span dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
}

/** Strip JSON ratings block from end of summary and return [cleanText, ratings] */
function extractRatingsFromSummary(text) {
  if (!text) return [text, null];
  // Match ```json { ... } ``` or bare { "score": ... } at end
  const jsonBlockRe = /\n*```json\s*\n?\s*(\{[^}]*"score"[^}]*\})\s*\n?```\s*$/;
  const bareJsonRe = /\n*(\{[^}]*"score"[^}]*\})\s*$/;
  let match = text.match(jsonBlockRe) || text.match(bareJsonRe);
  if (match) {
    try {
      const ratings = JSON.parse(match[1]);
      if (ratings.score >= 1 && ratings.score <= 10) {
        return [text.slice(0, match.index).trimEnd(), ratings];
      }
    } catch {}
  }
  return [text, null];
}

function RatingBadge({ ratings }) {
  if (!ratings) return null;
  const dims = [
    { key: "significance", label: "Significance" },
    { key: "rigor", label: "Rigor" },
    { key: "novelty", label: "Novelty" },
    { key: "clarity", label: "Clarity" },
  ];
  return (
    <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border/30 flex-wrap" data-testid="summary-ratings">
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-muted-foreground">Rating:</span>
        <span className="text-sm font-semibold">{ratings.score}</span>
        <span className="text-[10px] text-muted-foreground">/ 10</span>
      </div>
      <div className="flex gap-1 flex-wrap">
        {dims.map(d => ratings[d.key] ? (
          <span key={d.key} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
            {d.label} {ratings[d.key]}
          </span>
        ) : null)}
      </div>
    </div>
  );
}

function SummaryText({ text, fallbackRatings }) {
  if (!text) return null;
  const [cleanText, inlineRatings] = extractRatingsFromSummary(text);
  const ratings = inlineRatings || fallbackRatings;
  return (
    <>
      <div className="text-sm leading-relaxed space-y-2">
        {cleanText.split("\n").filter(l => l.trim()).map((line, i) => {
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
          return <li key={i} className="ml-4 list-disc" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
        }
        // Regular line with inline formatting + LaTeX
        const html = renderLatex(line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"));
        if (html !== line) {
          return <p key={i} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
        }
        return <p key={i}>{line}</p>;
      })}
      </div>
      <RatingBadge ratings={ratings} />
    </>
  );
}

/** Render abstract text with LaTeX support */
function AbstractText({ text }) {
  if (!text) return null;
  const html = renderLatex(text);
  if (html !== text) {
    return <p className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
  }
  return <p className="text-sm leading-relaxed">{text}</p>;
}

const MATCHES_PER_PAGE = 20;

function ComparisonHistory({ matches }) {
  const [showCount, setShowCount] = useState(MATCHES_PER_PAGE);
  const validMatches = useMemo(() => matches.filter(m => !m.failed), [matches]);
  const visible = validMatches.slice(0, showCount);
  const remaining = validMatches.length - showCount;

  return (
    <div data-testid="comparison-logs">
      <h2 className="font-heading text-lg font-medium mb-4">
        Comparison History ({validMatches.length})
      </h2>

      {validMatches.length === 0 ? (
        <p className="text-sm text-muted-foreground">No comparisons yet.</p>
      ) : (
        <div className="space-y-2">
          {visible.map((match) => (
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
          {remaining > 0 && (
            <button
              onClick={() => setShowCount(prev => prev + MATCHES_PER_PAGE)}
              className="w-full py-3 text-sm text-muted-foreground hover:text-foreground border border-border rounded-lg hover:bg-secondary/20 transition-colors"
              data-testid="load-more-matches"
            >
              Show more ({remaining} remaining)
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function PaperPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { bookmarkedIds, toggleBookmark } = useBookmarks();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [paperBadges, setPaperBadges] = useState([]);
  const [activeCategories, setActiveCategories] = useState(new Set());

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
    const fetchBadges = async () => {
      try {
        const res = await axios.get(`${API}/api/badge/paper/${id}/badges`);
        setPaperBadges(res.data.badges || []);
      } catch {}
    };
    const fetchCategories = async () => {
      try {
        const res = await axios.get(`${API}/api/categories`);
        const cats = (res.data.categories || []).map(c => c.id || c.category || c);
        setActiveCategories(new Set(cats));
      } catch {}
    };
    fetchPaper();
    fetchBadges();
    fetchCategories();
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
        <div className="flex items-start gap-2 mb-3">
          <h1 className="font-heading text-xl md:text-2xl font-semibold tracking-tight leading-tight flex-1">
            {paper.title}
          </h1>
          <button onClick={() => toggleBookmark(paper.id)}
            className={`mt-1 p-1 rounded transition-colors ${bookmarkedIds.has(paper.id) ? "text-accent" : "text-muted-foreground/30 hover:text-muted-foreground"}`}
            data-testid="paper-bookmark-btn">
            <Bookmark className="h-5 w-5" fill={bookmarkedIds.has(paper.id) ? "currentColor" : "none"} />
          </button>
        </div>
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

        {/* Categories — clickable links to leaderboards (only if category has a leaderboard) */}
        {paper.categories && paper.categories.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mt-3" data-testid="paper-categories">
            <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            {paper.categories.map((cat, i) => {
              const hasLeaderboard = activeCategories.has(cat);
              const className = `inline-flex items-center text-[11px] px-2 py-0.5 rounded-md font-mono ${
                i === 0
                  ? "bg-primary/10 text-primary border border-primary/20 font-medium"
                  : "bg-secondary text-muted-foreground border border-border"
              } ${hasLeaderboard ? "hover:opacity-80 transition-opacity" : ""}`;
              const content = <>{cat}{i === 0 && <span className="ml-1 text-[9px] opacity-60">(primary)</span>}</>;
              return hasLeaderboard ? (
                <Link key={cat} to={`/?cat=${encodeURIComponent(cat)}`} className={className} data-testid={`paper-cat-${cat}`}>
                  {content}
                </Link>
              ) : (
                <span key={cat} className={className} data-testid={`paper-cat-${cat}`}>
                  {content}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {/* Score Card — E2 Design with integrated badge header */}
      {(() => {
        // Badge tier colors
        const TIER_COLORS = {
          "Gold": { color: "#D4A012", bg: "#FEFCE8" },
          "Silver": { color: "#6B7280", bg: "#F3F4F6" },
          "Bronze": { color: "#CD7F32", bg: "#FFF7ED" },
        };

        // Extract ratings
        let ratings = null;
        if (paper.ai_rating && typeof paper.ai_rating === "object" && paper.ai_rating.score) ratings = paper.ai_rating;
        if (!ratings && paper.ai_ratings_by_model) {
          const byModel = paper.ai_ratings_by_model;
          const preferred = byModel.claude || byModel.anthropic || byModel.gpt || byModel.gemini;
          if (preferred && typeof preferred === "object" && preferred.score) ratings = preferred;
        }
        if (!ratings && summaryEntries.length > 0) {
          const primaryEntry = summaryEntries.find(e => e.provider === "anthropic") || summaryEntries[0];
          if (primaryEntry) { const [, ir] = extractRatingsFromSummary(primaryEntry.text); if (ir) ratings = ir; }
        }
        if (!ratings && paper.ai_rating) ratings = { score: typeof paper.ai_rating === "number" ? paper.ai_rating : parseFloat(paper.ai_rating) || null };

        const dims = [
          { key: "significance", label: "Significance", color: "text-blue-700 bg-blue-50 border-blue-200" },
          { key: "rigor", label: "Rigor", color: "text-emerald-700 bg-emerald-50 border-emerald-200" },
          { key: "novelty", label: "Novelty", color: "text-violet-700 bg-violet-50 border-violet-200" },
          { key: "clarity", label: "Clarity", color: "text-amber-700 bg-amber-50 border-amber-200" },
        ];

        const displayScore = paper.ts_score;
        const displaySigma = paper.ts_sigma;
        const displayScale = 10;
        const displayCi = displaySigma ? Math.round(1.96 * displaySigma * displayScale) : null;
        const rangeMin = paper.category_ts_min || 900;
        const rangeMax = paper.category_ts_max || 2000;
        const paddedMin = Math.floor((rangeMin - 50) / 50) * 50;
        const paddedMax = Math.ceil((rangeMax + 50) / 50) * 50;
        const range = paddedMax - paddedMin || 1;

        return (
          <div className="mb-8 border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden" data-testid="paper-score-card">
            {/* Badge header bar (only if paper has badges) */}
            {paperBadges.length > 0 && paperBadges.map((b, i) => {
              const tc = TIER_COLORS[b.tier] || { color: b.tier_color, bg: "#F9FAFB" };
              return (
                <Link key={i} to={b.badge_url} className="flex items-center justify-between px-4 py-2.5 border-b transition-opacity hover:opacity-80" style={{ backgroundColor: tc.bg, borderBottomColor: `${tc.color}33` }} data-testid={`paper-badge-${i}`}>
                  <div className="flex items-center gap-2">
                    <Award className="h-4 w-4" style={{ color: tc.color }} />
                    <span className="text-sm font-semibold" style={{ color: tc.color }}>
                      {b.tier} · #{b.rank} in {b.category_name} · {b.archive_label}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-sm font-semibold px-3 py-1 rounded-full border" style={{ color: tc.color, borderColor: `${tc.color}44` }}>
                    <Share2 className="h-3.5 w-3.5" /> Share
                  </div>
                </Link>
              );
            })}
            {/* Desktop/Tablet: side-by-side */}
            <div className="hidden md:flex flex-row">
              {/* Tournament Score */}
              <div className="w-[70%] p-6 border-r border-slate-200">
                <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Trophy className="h-3.5 w-3.5" /> Tournament Score
                </div>
                {displayScore ? (
                  <>
                    <div className="flex items-baseline gap-2 mb-3">
                      <span className="text-5xl font-bold tracking-tight text-slate-900">{displayScore}</span>
                      {displayCi && <span className="text-lg text-slate-400">±{displayCi}</span>}
                    </div>
                    <div>
                      <div className="w-full h-2 bg-slate-100 rounded-full relative">
                        <div className="absolute h-full bg-blue-200 rounded-full" style={{
                          left: `${Math.max(0, ((displayScore - displayCi - paddedMin) / range) * 100)}%`,
                          width: `${Math.min(100, (displayCi * 2 / range) * 100)}%`,
                        }} />
                        <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{
                          left: `${((displayScore - paddedMin) / range) * 100}%`,
                        }} />
                      </div>
                      <div className="flex justify-between mt-1 text-[10px] text-slate-400">
                        <span>{paddedMin}</span><span>{paddedMax}</span>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex items-baseline gap-2 mb-3">
                    <span className="text-5xl font-bold tracking-tight text-slate-900">{stats.score || "—"}</span>
                  </div>
                )}
                <div className="grid grid-cols-4 gap-2 mt-4 pt-4 border-t border-slate-100">
                  <div className="text-center p-2.5 bg-slate-50 rounded-lg">
                    <div className="text-xl font-bold text-slate-900">{winRate}%</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">Win Rate</div>
                  </div>
                  <div className="text-center p-2.5 bg-green-50 rounded-lg">
                    <div className="text-xl font-bold text-green-600">{stats.wins}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">Wins</div>
                  </div>
                  <div className="text-center p-2.5 bg-red-50 rounded-lg">
                    <div className="text-xl font-bold text-red-500">{stats.losses}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">Losses</div>
                  </div>
                  <div className="text-center p-2.5 bg-slate-50 rounded-lg">
                    <div className="text-xl font-bold text-slate-900">{stats.comparisons}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">Matches</div>
                  </div>
                </div>
              </div>
              {/* Rating */}
              <div className="w-[30%] p-6 bg-slate-50/50">
                <div className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Target className="h-3.5 w-3.5" /> Rating
                </div>
                <div className="flex items-baseline gap-1 mb-4">
                  <span className="text-4xl font-bold tracking-tight text-slate-700">{ratings?.score || "—"}</span>
                  {ratings?.score && <span className="text-sm text-slate-400">/ 10</span>}
                </div>
                <div className="flex flex-col gap-2.5">
                  {dims.map(d => ratings?.[d.key] ? (
                    <div key={d.key}>
                      <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1">
                        <span>{d.label}</span><span className="font-bold text-slate-700">{ratings[d.key]}</span>
                      </div>
                      <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                        <div className="h-full bg-slate-400 rounded-full" style={{ width: `${ratings[d.key] * 10}%` }} />
                      </div>
                    </div>
                  ) : null)}
                </div>
              </div>
            </div>

            {/* Mobile: stacked */}
            <div className="md:hidden">
              <div className="p-5">
                <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                  <Trophy className="h-3 w-3" /> Tournament Score
                </div>
                {displayScore ? (
                  <>
                    <div className="flex items-baseline gap-1.5 mb-2.5">
                      <span className="text-4xl font-bold tracking-tight text-slate-900">{displayScore}</span>
                      {displayCi && <span className="text-base text-slate-400">±{displayCi}</span>}
                    </div>
                    <div>
                      <div className="w-full h-2 bg-slate-100 rounded-full relative">
                        <div className="absolute h-full bg-blue-200 rounded-full" style={{
                          left: `${Math.max(0, ((displayScore - displayCi - paddedMin) / range) * 100)}%`,
                          width: `${Math.min(100, (displayCi * 2 / range) * 100)}%`,
                        }} />
                        <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{
                          left: `${((displayScore - paddedMin) / range) * 100}%`,
                        }} />
                      </div>
                      <div className="flex justify-between mt-1 text-[10px] text-slate-400">
                        <span>{paddedMin}</span><span>{paddedMax}</span>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex items-baseline gap-1.5 mb-2.5">
                    <span className="text-4xl font-bold tracking-tight text-slate-900">{stats.score || "—"}</span>
                  </div>
                )}
                <div className="grid grid-cols-4 gap-1.5 mt-3 pt-3 border-t border-slate-100">
                  <div className="text-center py-2 bg-slate-50 rounded-lg">
                    <div className="text-lg font-bold text-slate-900">{winRate}%</div>
                    <div className="text-[9px] text-slate-500">Win Rate</div>
                  </div>
                  <div className="text-center py-2 bg-green-50 rounded-lg">
                    <div className="text-lg font-bold text-green-600">{stats.wins}</div>
                    <div className="text-[9px] text-slate-500">Wins</div>
                  </div>
                  <div className="text-center py-2 bg-red-50 rounded-lg">
                    <div className="text-lg font-bold text-red-500">{stats.losses}</div>
                    <div className="text-[9px] text-slate-500">Losses</div>
                  </div>
                  <div className="text-center py-2 bg-slate-50 rounded-lg">
                    <div className="text-lg font-bold text-slate-900">{stats.comparisons}</div>
                    <div className="text-[9px] text-slate-500">Matches</div>
                  </div>
                </div>
              </div>
              {/* Rating - mobile */}
              {ratings?.score && (
                <div className="p-5 pt-0">
                  <div className="border-t border-slate-200 pt-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-1.5">
                        <Target className="h-3 w-3 text-slate-500" />
                        <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">Rating</span>
                      </div>
                      <div className="flex items-baseline gap-0.5">
                        <span className="text-2xl font-bold text-slate-700">{ratings.score}</span>
                        <span className="text-xs text-slate-400">/ 10</span>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
                      {dims.map(d => ratings[d.key] ? (
                        <div key={d.key}>
                          <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1">
                            <span>{d.label}</span><span className="font-bold text-slate-700">{d.value}</span>
                          </div>
                          <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                            <div className="h-full bg-slate-400 rounded-full" style={{ width: `${ratings[d.key] * 10}%` }} />
                          </div>
                        </div>
                      ) : null)}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}

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
                <SummaryText text={e.text} fallbackRatings={e.provider === "anthropic" ? paper.ai_rating : null} />
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
          <SummaryText text={paper.impact_summary} fallbackRatings={paper.ai_rating} />
          {paper.summary_generated_at && (
            <p className="text-[10px] text-muted-foreground mt-3">
              Generated {new Date(paper.summary_generated_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
            </p>
          )}
        </div>
      ) : null}

      {/* Comparison Logs */}
      <ComparisonHistory matches={matches} />
    </div>
  );
}
