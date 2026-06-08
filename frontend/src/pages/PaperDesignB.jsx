import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import DOMPurify from "dompurify";
import { ArrowLeft, ExternalLink, Clock, Sparkles, Trophy, Share2, Bookmark, Target, Award } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useBookmarks } from "@/contexts/BookmarkContext";
import { useBasePath } from "@/contexts/BasePathContext";
import { LatexTitle } from "@/components/LatexTitle";
import TopNav from "@/components/site/TopNav";
import katex from "katex";

const API = process.env.REACT_APP_BACKEND_URL;
const SUMMARY_LABELS = { anthropic: { label: "Claude", color: "text-orange-600" }, gemini: { label: "Gemini", color: "text-blue-600" }, openai: { label: "GPT", color: "text-green-600" } };

function getSummaryEntries(summaries, summaryDates) {
  if (!summaries || typeof summaries !== "object") return [];
  const KNOWN = new Set(["anthropic", "openai", "gemini"]);
  const entries = Object.entries(summaries).map(([key, val]) => {
    const provider = key.split(":")[0];
    const meta = SUMMARY_LABELS[provider] || { label: provider, color: "text-slate-600" };
    let text = val;
    if (typeof val === "object" && val !== null) { const strs = Object.values(val).filter(v => typeof v === "string" && v.length > 50); text = strs.length ? strs.reduce((a, b) => a.length > b.length ? a : b) : ""; }
    return { key, tabId: provider, provider, text, date: (summaryDates || {})[key] || null, ...meta };
  }).filter(e => typeof e.text === "string" && e.text.length > 50 && KNOWN.has(e.provider));
  const byProvider = {};
  for (const e of entries) { if (!byProvider[e.provider] || e.key > byProvider[e.provider].key) byProvider[e.provider] = e; }
  const deduped = Object.values(byProvider);
  deduped.sort((a, b) => ({ anthropic: 0, openai: 1, gemini: 2 }[a.provider] ?? 9) - ({ anthropic: 0, openai: 1, gemini: 2 }[b.provider] ?? 9));
  return deduped;
}

function extractRatings(text) {
  if (!text) return [text, null];
  const m = text.match(/\n*```json\s*\n?\s*(\{[^}]*"score"[^}]*\})\s*\n?```\s*$/) || text.match(/\n*(\{[^}]*"score"[^}]*\})\s*$/);
  if (m) { try { const r = JSON.parse(m[1]); if (r.score >= 1 && r.score <= 10) return [text.slice(0, m.index).trimEnd(), r]; } catch {} }
  return [text, null];
}

function renderLatex(text) {
  if (!text) return text;
  let r = text.replace(/\$\$(.+?)\$\$/gs, (_, e) => { try { return katex.renderToString(e.trim(), { displayMode: true, throwOnError: false }); } catch { return `$$${e}$$`; } });
  r = r.replace(/\\\[(.+?)\\\]/gs, (_, e) => { try { return katex.renderToString(e.trim(), { displayMode: true, throwOnError: false }); } catch { return `\\[${e}\\]`; } });
  r = r.replace(/\\\((.+?)\\\)/g, (_, e) => { try { return katex.renderToString(e.trim(), { displayMode: false, throwOnError: false }); } catch { return `\\(${e}\\)`; } });
  r = r.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, e) => { try { return katex.renderToString(e.trim(), { displayMode: false, throwOnError: false }); } catch { return `$${e}$`; } });
  return r;
}

function SummaryBlock({ text, fallbackRatings }) {
  if (!text) return null;
  const [clean, inlineRatings] = extractRatings(text);
  const ratings = inlineRatings || fallbackRatings;
  return (
    <>
      <div className="text-sm leading-relaxed space-y-2">
        {clean.split("\n").filter(l => l.trim()).map((line, i) => {
          const h = line.match(/^#{1,3}\s+(.+)$/) || line.match(/^\*\*(.+?)\*\*$/);
          if (h) return <h4 key={i} className="hp-sans font-semibold text-sm mt-4 first:mt-0">{h[1].replace(/\*\*/g, "")}</h4>;
          const bullet = line.match(/^[-*]\s+(.+)$/);
          if (bullet) { const html = renderLatex(bullet[1].replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")); return <li key={i} className="ml-4 list-disc" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />; }
          const html = renderLatex(line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"));
          return html !== line ? <p key={i} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} /> : <p key={i}>{line}</p>;
        })}
      </div>
      {ratings && (
        <div className="flex items-center gap-3 mt-4 pt-4 border-t border-slate-100 flex-wrap">
          <div className="flex items-center gap-1"><span className="text-[10px] text-slate-500">Rating:</span><span className="text-sm font-semibold">{ratings.score}</span><span className="text-[10px] text-slate-400">/ 10</span></div>
          {["significance", "rigor", "novelty", "clarity"].map(d => ratings[d] ? <span key={d} className="text-[10px] px-1.5 py-0.5 rounded-sm bg-slate-50 text-slate-600 border border-slate-200">{d.charAt(0).toUpperCase() + d.slice(1)} {ratings[d]}</span> : null)}
        </div>
      )}
    </>
  );
}

export default function PaperDesignB() {
  const { id } = useParams();
  const basePath = useBasePath();
  const { bookmarkedIds, toggleBookmark } = useBookmarks();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAllMatches, setShowAllMatches] = useState(false);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API}/api/papers/${id}`).then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="kurate-homepage"><TopNav /><div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-16"><div className="h-8 w-64 bg-slate-100 rounded-sm animate-pulse" /></div></div>;
  if (!data) return <div className="kurate-homepage"><TopNav /><div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-16 text-center text-slate-400">Paper not found.</div></div>;

  const { paper, matches, stats } = data;
  const winRate = stats.comparisons > 0 ? Math.round((stats.wins / stats.comparisons) * 100) : 0;
  const summaryEntries = getSummaryEntries(paper.summaries, paper.summary_dates);
  const isBookmarked = bookmarkedIds?.has(paper.id);
  const validMatches = matches.filter(m => !m.failed);
  const visibleMatches = showAllMatches ? validMatches : validMatches.slice(0, 10);

  let ratings = null;
  if (paper.ai_ratings_by_model) { const c = paper.ai_ratings_by_model.claude || paper.ai_ratings_by_model.anthropic; if (c?.score) ratings = c; }
  if (!ratings && summaryEntries.length > 0) { const ce = summaryEntries.find(e => e.provider === "anthropic"); if (ce) { const [, ir] = extractRatings(ce.text); if (ir) ratings = ir; } }

  const dims = [
    { key: "significance", label: "Significance" },
    { key: "rigor", label: "Rigor" },
    { key: "novelty", label: "Novelty" },
    { key: "clarity", label: "Clarity" },
  ];

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 pt-8 pb-16">
        <Link to={`${basePath}/leaderboard`} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 mb-6 transition-colors">
          <ArrowLeft className="h-4 w-4" /> Back to Rankings
        </Link>

        {/* Title + meta — always full width above both columns */}
        <h1 className="font-serif text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 leading-tight mb-3">
          <LatexTitle text={paper.title} />
        </h1>
        <p className="text-sm text-slate-600 mb-3">{paper.authors?.join(", ")}</p>
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {paper.published && (
            <span className="inline-flex items-center gap-1 text-xs text-slate-500 px-2 py-0.5 rounded-sm border border-slate-200">
              <Clock className="h-3 w-3" />
              {new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}
            </span>
          )}
          {paper.arxiv_id && (
            <a href={paper.link || `https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline">
              arXiv:{paper.arxiv_id} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
        {paper.categories?.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mb-6">
            {paper.categories.map((cat, i) => (
              <span key={cat} className={`inline-flex items-center px-1.5 py-0.5 rounded-sm border text-[10px] font-medium ${i === 0 ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-slate-50 text-slate-500 border-slate-200"}`}>{cat}</span>
            ))}
          </div>
        )}

        {/* Version toggle */}
        {paper.sibling_versions?.length >= 2 && (
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <div className="inline-flex items-center rounded-sm border border-slate-200 p-0.5" role="tablist" aria-label="Paper versions">
              {[...paper.sibling_versions].sort((a, b) => (a.version || 0) - (b.version || 0)).map(v => {
                const isCurrent = v.paper_id === paper.id || (v.version != null && v.version === paper.current_version);
                const label = `v${v.version}`;
                const title = `Version ${v.version}${v.is_latest ? " (latest)" : " (frozen)"}`;
                return isCurrent ? (
                  <span key={v.paper_id || v.version} className="inline-flex items-center px-2.5 py-1 rounded-sm text-[11px] font-mono font-semibold bg-slate-900 text-white" title={title} aria-current="page">{label}</span>
                ) : (
                  <Link key={v.paper_id || v.version} to={`${basePath}/paper/${v.paper_id}`} className="inline-flex items-center px-2.5 py-1 rounded-sm text-[11px] font-mono text-slate-500 hover:text-slate-900 hover:bg-slate-50 transition-colors" title={title}>{label}</Link>
                );
              })}
            </div>
          </div>
        )}

        {/* Frozen version banner */}
        {paper.is_latest_version === false && (() => {
          const latest = (paper.sibling_versions || []).find(s => s.is_latest);
          return (
            <div className="mb-6 px-4 py-2.5 bg-amber-50 border border-amber-200 rounded-sm flex items-center justify-between gap-3 text-xs text-amber-900">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 shrink-0" />
                <span><strong>Frozen v{paper.current_version || "\u2014"}</strong> — this version was superseded on arXiv. Stats reflect the state at freeze time.</span>
              </span>
              {latest?.paper_id && (
                <Link to={`${basePath}/paper/${latest.paper_id}`} className="shrink-0 font-semibold text-amber-800 underline hover:no-underline">
                  View latest (v{latest.version}) →
                </Link>
              )}
            </div>
          );
        })()}

        {/* Score card component — reused in both mobile and desktop positions */}
        {(() => {
          const displayScore = paper.ts_score || stats.score;
          const displayCi = stats.ci_elo || null;
          const rangeMin = paper.category_ts_min || 900;
          const rangeMax = paper.category_ts_max || 2000;
          const paddedMin = Math.floor((rangeMin - 50) / 50) * 50;
          const paddedMax = Math.ceil((rangeMax + 50) / 50) * 50;
          const range = paddedMax - paddedMin || 1;

          const TIER_COLORS = {
            "Top 3": { color: "#D97706", bg: "#FFFBEB" },
            "Top 5": { color: "#2563EB", bg: "#EFF6FF" },
            "Top 10": { color: "#059669", bg: "#ECFDF5" },
            "Top 20": { color: "#6366F1", bg: "#EEF2FF" },
          };
          const paperBadges = paper.badges || [];

          const ScoreCard = () => (
            <div className="space-y-4">
              {/* Badge banner(s) — between score card and actions */}
              {paperBadges.length > 0 && paperBadges.map((b, i) => {
                const tc = TIER_COLORS[b.tier] || { color: b.tier_color || "#64748B", bg: "#F8FAFC" };
                return (
                  <div key={i} className="flex items-center justify-between px-4 py-2.5 rounded-sm border" style={{ backgroundColor: tc.bg, borderColor: `${tc.color}33` }}>
                    <div className="flex items-center gap-1.5 text-sm">
                      <span className="font-bold" style={{ color: tc.color }}>#{paper.current_rank || b.rank}</span>
                      <span className="text-slate-400">of {paper.total_in_category || "\u2014"}</span>
                      <span className="text-slate-300 mx-0.5">·</span>
                      <span className="flex items-center gap-1 font-semibold" style={{ color: tc.color }}>
                        <Award className="h-3.5 w-3.5" />
                        {b.tier} · {b.archive_label}
                      </span>
                    </div>
                    <Link to={`/share/${paper.id}`} className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-sm border transition-colors hover:opacity-80" style={{ color: tc.color, borderColor: `${tc.color}44` }}>
                      <Share2 className="h-3 w-3" /> Share
                    </Link>
                  </div>
                );
              })}

              {/* Actions */}
              <div className="flex items-center gap-2">
                <button onClick={() => toggleBookmark(paper.id)} className={`flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-sm border text-sm font-medium transition-colors ${isBookmarked ? "bg-blue-50 text-blue-700 border-blue-200" : "text-slate-600 border-slate-200 hover:border-slate-400"}`}>
                  <Bookmark className="h-3.5 w-3.5" fill={isBookmarked ? "currentColor" : "none"} /> {isBookmarked ? "Bookmarked" : "Bookmark"}
                </button>
                <Link to={`/share/${paper.id}`} className="flex-1 inline-flex items-center justify-center gap-1.5 py-2 rounded-sm border border-slate-200 text-sm font-medium text-slate-600 hover:border-slate-400 transition-colors">
                  <Share2 className="h-3.5 w-3.5" /> Share
                </Link>
              </div>

              {/* Tournament Score */}
              <div className="border border-slate-200 rounded-sm p-5">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-900 mb-2 flex items-center gap-1.5">
                  <Trophy className="h-3.5 w-3.5 text-blue-600" /> Tournament Score
                </div>
                <div className="flex items-baseline gap-2 mb-3">
                  <span className="font-serif text-5xl font-medium text-slate-900">{displayScore || "\u2014"}</span>
                  {displayCi && <span className="text-lg text-slate-400">±{displayCi}</span>}
                </div>
                {/* Confidence interval bar */}
                {displayScore && (
                  <div className="mb-4">
                    <div className="w-full h-2 bg-slate-100 rounded-full relative">
                      {displayCi && (
                        <div className="absolute h-full bg-blue-200 rounded-full" style={{
                          left: `${Math.max(0, ((displayScore - displayCi - paddedMin) / range) * 100)}%`,
                          width: `${Math.min(100, (displayCi * 2 / range) * 100)}%`,
                        }} />
                      )}
                      <div className="absolute h-3.5 w-3.5 bg-blue-600 rounded-full top-1/2 -translate-y-1/2 -translate-x-1/2 border-2 border-white shadow-sm" style={{
                        left: `${Math.max(0, Math.min(100, ((displayScore - paddedMin) / range) * 100))}%`,
                      }} />
                    </div>
                    <div className="flex justify-between mt-1 text-[10px] text-slate-400">
                      <span>{paddedMin}</span><span>{paddedMax}</span>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-4 gap-2">
                  <div className="text-center py-2.5 bg-slate-50 rounded-sm"><div className="text-xl font-semibold text-slate-900">{winRate}%</div><div className="text-[9px] text-slate-500">Win Rate</div></div>
                  <div className="text-center py-2.5 bg-slate-50 rounded-sm"><div className="text-xl font-semibold text-emerald-600">{stats.wins}</div><div className="text-[9px] text-slate-500">Wins</div></div>
                  <div className="text-center py-2.5 bg-slate-50 rounded-sm"><div className="text-xl font-semibold text-red-400">{stats.losses}</div><div className="text-[9px] text-slate-500">Losses</div></div>
                  <div className="text-center py-2.5 bg-slate-50 rounded-sm"><div className="text-xl font-semibold text-slate-900">{stats.comparisons}</div><div className="text-[9px] text-slate-500">Matches</div></div>
                </div>
              </div>

              {/* Rating */}
              {ratings?.score && (
                <div className="border border-slate-200 rounded-sm p-5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-900 mb-2 flex items-center gap-1.5">
                    <Target className="h-3.5 w-3.5 text-blue-600" /> Rating
                  </div>
                  <div className="flex items-baseline gap-1 mb-4">
                    <span className="font-serif text-4xl font-medium text-slate-700">{ratings.score}</span>
                    <span className="text-sm text-slate-400">/ 10</span>
                  </div>
                  <div className="space-y-2.5">
                    {dims.map(d => ratings[d.key] ? (
                      <div key={d.key}>
                        <div className="flex justify-between text-[11px] text-slate-500 mb-1"><span>{d.label}</span><span className="font-semibold text-slate-700">{ratings[d.key]}</span></div>
                        <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden"><div className="h-full bg-blue-400 rounded-full" style={{ width: `${ratings[d.key] * 10}%` }} /></div>
                      </div>
                    ) : null)}
                  </div>
                </div>
              )}

              {/* Rank info */}
              {paper.current_rank && (
                <div className="border border-slate-200 rounded-sm p-4 text-center">
                  <span className="text-sm text-slate-500">Ranked </span>
                  <span className="font-serif text-lg font-medium text-blue-600">#{paper.current_rank}</span>
                  <span className="text-sm text-slate-500"> of {paper.total_in_category || "\u2014"}</span>
                  <span className="text-sm text-slate-400"> in {paper.category_name || paper.categories?.[0] || ""}</span>
                </div>
              )}
            </div>
          );

          return (
            <>
              {/* Mobile: score card after header, before abstract (matching original PaperPage order) */}
              <div className="lg:hidden mb-8">
                <ScoreCard />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                {/* LEFT — Content */}
                <div className="lg:col-span-7">
                  {/* Abstract */}
                  {paper.abstract && (
                    <div className="mb-8 border border-slate-200 rounded-sm p-5">
                      <h3 className="hp-sans text-[10px] font-bold uppercase tracking-wider text-slate-900 mb-3">Abstract</h3>
                      <p className="text-sm leading-relaxed text-slate-700" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(renderLatex(paper.abstract)) }} />
                    </div>
                  )}

                  {/* AI Summaries */}
                  {summaryEntries.length > 0 && (
                    <div className="mb-8 border border-slate-200 rounded-sm p-5">
                      <div className="flex items-center gap-1.5 mb-4">
                        <Sparkles className="h-3.5 w-3.5 text-blue-600" />
                        <h3 className="hp-sans text-[10px] font-bold uppercase tracking-wider text-slate-900">AI Impact Assessments</h3>
                        <span className="text-[10px] text-slate-400 ml-1">({summaryEntries.length} models)</span>
                      </div>
                      <Tabs defaultValue={summaryEntries[0].tabId}>
                        <TabsList className="mb-4">
                          {summaryEntries.map(e => <TabsTrigger key={e.tabId} value={e.tabId} className="text-xs gap-1.5"><span className={e.color}>{e.label}</span></TabsTrigger>)}
                        </TabsList>
                        {summaryEntries.map(e => (
                          <TabsContent key={e.tabId} value={e.tabId}>
                            <SummaryBlock text={e.text} fallbackRatings={e.provider === "anthropic" ? ratings : null} />
                            {e.date && <p className="text-[10px] text-slate-400 mt-3">Generated {new Date(e.date).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}</p>}
                          </TabsContent>
                        ))}
                      </Tabs>
                    </div>
                  )}

                  {/* Comparison History */}
                  <div className="border border-slate-200 rounded-sm overflow-hidden">
                    <div className="px-5 py-3 bg-slate-50 border-b border-slate-200">
                      <h3 className="hp-sans text-[10px] font-bold uppercase tracking-wider text-slate-900">Comparison History ({validMatches.length})</h3>
                    </div>
                    {validMatches.length === 0 ? (
                      <div className="py-10 text-center text-sm text-slate-400">No comparisons yet.</div>
                    ) : (
                      <>
                        {visibleMatches.map(m => (
                          <div key={m.id} className="px-5 py-3 border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors">
                            <div className="flex items-center justify-between gap-3">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className={`text-xs font-medium shrink-0 ${m.won ? "text-emerald-600" : "text-red-400"}`}>{m.won ? "Won" : "Lost"}</span>
                                <span className="text-sm text-slate-700 truncate">vs. {m.opponent_title}</span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0 text-xs text-slate-400">
                                <span>{typeof m.model_used === "object" ? m.model_used.model : (m.model_used || "")}</span>
                                {m.created_at && <span className="whitespace-nowrap">{new Date(m.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>}
                              </div>
                            </div>
                            {m.reasoning && <p className="text-xs text-slate-500 leading-relaxed mt-1.5 ml-12">{m.reasoning}</p>}
                          </div>
                        ))}
                        {!showAllMatches && validMatches.length > 10 && (
                          <button onClick={() => setShowAllMatches(true)} className="w-full py-3 text-sm text-slate-500 hover:text-slate-700 border-t border-slate-100 transition-colors">
                            Show all ({validMatches.length - 10} more)
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* RIGHT — Sticky score card (desktop only) */}
                <div className="hidden lg:block lg:col-span-5">
                  <div className="sticky top-20">
                    <ScoreCard />
                  </div>
                </div>
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
}
