import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { FlaskConical, ArrowUpDown, RefreshCw, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DeeperDiveSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [catFilter, setCatFilter] = useState("all");
  const [sortBy, setSortBy] = useState("category");
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [replay, setReplay] = useState(null);
  const [replayStatus, setReplayStatus] = useState(null);
  const [tab, setTab] = useState("papers"); // "papers" | "replay"

  const fetchResults = () => {
    axios.get(`${API}/api/validation/deeper-dive/results`).then(r => {
      setData(r.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  const fetchReplay = () => {
    axios.get(`${API}/api/validation/deeper-dive/replay/results`).then(r => setReplay(r.data)).catch(() => {});
    axios.get(`${API}/api/validation/deeper-dive/replay/status`).then(r => setReplayStatus(r.data)).catch(() => {});
  };

  useEffect(() => { fetchResults(); fetchReplay(); }, []);

  // Auto-refresh while anything is running
  const isRunning = data?.enhance_progress?.running || data?.experiment_progress?.running || data?.status === "no_data" || replayStatus?.running;
  useEffect(() => {
    if (!isRunning) return;
    const iv = setInterval(() => { fetchResults(); fetchReplay(); }, 8000);
    return () => clearInterval(iv);
  }, [isRunning]);

  if (loading) {
    return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  }

  if (data?.status === "no_data") {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <RefreshCw className="h-8 w-8 mx-auto mb-3 animate-spin opacity-30" />
        <p className="text-sm">Experiment running... checking for results</p>
      </div>
    );
  }

  const { summary, results, enhance_progress, experiment_progress } = data;
  const categories = [...new Set(results.map(r => r.category))].sort();
  const enhancing = enhance_progress?.running;
  const enhanceDone = enhance_progress?.done || 0;
  const enhanceTotal = enhance_progress?.total || 0;
  const experimenting = experiment_progress?.running;
  const expDone = experiment_progress?.done || 0;
  const expTotal = experiment_progress?.total || 0;
  const expErrors = experiment_progress?.errors || 0;

  // Filter
  let filtered = results.filter(r => r.parse_ok !== false);
  if (filter === "recommended") filtered = filtered.filter(r => r.deeper_dive_recommended);
  if (filter === "not") filtered = filtered.filter(r => !r.deeper_dive_recommended);
  if (catFilter !== "all") filtered = filtered.filter(r => r.category === catFilter);

  // Sort
  if (sortBy === "category") filtered.sort((a, b) => a.category.localeCompare(b.category) || a.title.localeCompare(b.title));
  if (sortBy === "confidence") filtered.sort((a, b) => (a.confidence || "").localeCompare(b.confidence || ""));
  if (sortBy === "length") filtered.sort((a, b) => b.full_text_len - a.full_text_len);
  if (sortBy === "enhanced") filtered.sort((a, b) => (b.enhanced_assessment ? 1 : 0) - (a.enhanced_assessment ? 1 : 0));

  const recRate = summary.recommend_rate;
  const confDist = summary.confidence_distribution || {};
  const enhancedCount = results.filter(r => r.enhanced_assessment).length;
  const recommendedCount = summary.recommended || 0;

  return (
    <div className="space-y-6" data-testid="deeper-dive-experiment">
      {/* Progress banners */}
      {experimenting && (
        <div className="flex items-center gap-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <RefreshCw className="h-4 w-4 animate-spin text-blue-600" />
          <span className="text-sm text-blue-900">Analyzing papers... {expDone}/{expTotal} ({expErrors} errors)</span>
        </div>
      )}
      {enhancing && (
        <div className="flex items-center gap-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <RefreshCw className="h-4 w-4 animate-spin text-amber-600" />
          <span className="text-sm text-amber-900">Generating enhanced assessments... {enhanceDone}/{enhanceTotal}</span>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Papers Analyzed" value={summary.parsed} sub={`${summary.errors} failures`} />
        <StatCard label="Deeper Dive" value={`${recommendedCount}/${summary.parsed}`} sub={`${recRate}% rate`} accent />
        <StatCard label="High Confidence" value={confDist.high || 0} sub="Complete" />
        <StatCard label="Medium Confidence" value={confDist.medium || 0} sub="Gaps found" />
        <StatCard label="Enhanced" value={`${enhancedCount}/${recommendedCount}`} sub={enhancing ? "In progress..." : enhancedCount > 0 ? "Revised" : "Not started"} enhanced={enhancedCount > 0} />
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border border-border rounded-lg p-0.5 w-fit" data-testid="dive-tab-switcher">
        <button onClick={() => setTab("papers")}
          className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${tab === "papers" ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
          Paper Analysis ({summary.parsed})
        </button>
        <button onClick={() => setTab("replay")}
          className={`px-3 py-1.5 text-xs font-medium rounded transition-colors flex items-center gap-1.5 ${tab === "replay" ? "bg-violet-100 text-violet-800" : "text-muted-foreground hover:text-foreground"}`}>
          Match Replay {replayStatus?.running && <RefreshCw className="h-3 w-3 animate-spin" />}
          {replay?.status === "ok" && ` (${replay.analysis?.total_replays || 0})`}
        </button>
      </div>

      {tab === "papers" && (<>
      {/* Two-column: confidence matrix + category bars */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Confidence vs Recommendation</h3>
          <div className="space-y-2 text-xs">
            {[["Recommended + medium", recommendedCount, "text-amber-600"],
              ["Not recommended + high", summary.not_recommended, "text-green-600"]].map(([label, val, cls]) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-muted-foreground">{label}</span>
                <span className={`font-mono font-medium ${cls}`}>{val}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">By Category</h3>
          <div className="space-y-1.5 text-xs">
            {Object.entries(summary.by_category || {}).sort((a, b) => (b[1].recommended / b[1].total) - (a[1].recommended / a[1].total)).map(([cat, s]) => (
              <div key={cat} className="flex items-center gap-2">
                <span className="font-mono text-muted-foreground w-28 shrink-0">{cat}</span>
                <div className="flex-1 bg-secondary/30 rounded-full h-4 overflow-hidden">
                  <div className="h-full bg-amber-500/70 rounded-full transition-all" style={{ width: `${(s.recommended / s.total) * 100}%` }} />
                </div>
                <span className="font-mono w-12 text-right">{s.recommended}/{s.total}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Top focus areas */}
      {summary.top_focus_areas?.length > 0 && (
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Top Focus Areas (Recommended Papers)</h3>
          <div className="flex flex-wrap gap-1.5">
            {summary.top_focus_areas.slice(0, 15).map((a, i) => (
              <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-50 border border-amber-200 rounded text-[10px] text-amber-900">
                {a.area.length > 60 ? a.area.slice(0, 57) + "..." : a.area}
                {a.count > 1 && <span className="font-mono font-bold">x{a.count}</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="dive-filter">
          {[["all", "All"], ["recommended", "Recommended"], ["not", "Not Recommended"]].map(([val, label]) => (
            <button key={val} onClick={() => setFilter(val)}
              className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${filter === val ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
              {label} {val === "recommended" ? `(${recommendedCount})` : val === "not" ? `(${summary.not_recommended})` : ""}
            </button>
          ))}
        </div>
        <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
          className="text-[11px] border border-border rounded-lg px-2 py-1.5 bg-background" data-testid="dive-cat-filter">
          <option value="all">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <button onClick={() => setSortBy(s => s === "category" ? "enhanced" : s === "enhanced" ? "length" : "category")}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground ml-auto">
          <ArrowUpDown className="h-3 w-3" /> Sort: {sortBy}
        </button>
      </div>

      {/* Results list */}
      <div className="space-y-2" data-testid="dive-results-list">
        {filtered.map((r, i) => {
          const globalIdx = results.indexOf(r);
          const isExpanded = expandedIdx === globalIdx;
          const hasEnhanced = !!r.enhanced_assessment;
          const hasOriginal = !!r.original_assessment;

          return (
            <div key={globalIdx} className={`border rounded-lg transition-colors ${r.deeper_dive_recommended ? "border-amber-300 bg-amber-50/50" : "border-border"}`}>
              {/* Header row */}
              <div className="p-3 text-xs cursor-pointer" onClick={() => setExpandedIdx(isExpanded ? null : globalIdx)}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="font-mono text-[10px] text-muted-foreground bg-secondary/50 px-1.5 py-0.5 rounded">{r.category}</span>
                      {r.deeper_dive_recommended && <span className="text-[10px] font-medium text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">DEEPER DIVE</span>}
                      {hasEnhanced && <span className="text-[10px] font-medium text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded flex items-center gap-0.5"><Sparkles className="h-2.5 w-2.5" />ENHANCED</span>}
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${r.confidence === "high" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                        {r.confidence} confidence
                      </span>
                    </div>
                    <p className="font-medium text-foreground">{r.title}</p>
                    <span className="text-muted-foreground">{(r.full_text_len / 1000).toFixed(0)}k chars</span>
                    {r.deeper_dive_recommended && r.focus_areas?.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {r.focus_areas.map((a, j) => (
                          <span key={j} className="text-[10px] px-1.5 py-0.5 bg-secondary/50 rounded text-muted-foreground">{a}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 mt-1">
                    {(hasOriginal || hasEnhanced) ? (
                      isExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : null}
                  </div>
                </div>
              </div>

              {/* Expanded: show assessments */}
              {isExpanded && (hasOriginal || hasEnhanced) && (
                <div className="border-t border-border/50 p-3">
                  <AssessmentComparison original={r.original_assessment} enhanced={r.enhanced_assessment} />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {filtered.length === 0 && <p className="text-center text-xs text-muted-foreground py-6">No results match filters.</p>}
      </>)}

      {tab === "replay" && (
        <ReplaySection replay={replay} status={replayStatus} />
      )}

      <p className="text-[10px] text-muted-foreground">
        Model: {summary.model} · {summary.total} papers across {Object.keys(summary.by_category || {}).length} categories
        {enhancedCount > 0 && ` · ${enhancedCount} enhanced assessments`}
      </p>
    </div>
  );
}

/** Match Replay experiment results */
function ReplaySection({ replay, status }) {
  const isRunning = status?.running;
  const done = status?.done || 0;
  const total = status?.total || 0;
  const errors = status?.errors || 0;
  const strata = status?.strata || {};
  const a = replay?.analysis;
  const hasResults = replay?.status === "ok" && a;

  if (!isRunning && !hasResults) return null;

  return (
    <div className="border-t border-border pt-6 mt-6 space-y-4" data-testid="replay-section">
      <div>
        <h2 className="text-base font-semibold">Match Replay Experiment</h2>
        <p className="text-[11px] text-muted-foreground">
          Do enhanced assessments change match outcomes beyond random LLM variance?
        </p>
      </div>

      {/* Progress banner */}
      {isRunning && (
        <div className="flex items-center gap-3 p-3 bg-violet-50 border border-violet-200 rounded-lg">
          <RefreshCw className="h-4 w-4 animate-spin text-violet-600" />
          <div>
            <span className="text-sm text-violet-900 font-medium">Replaying matches... {done}/{total}</span>
            {errors > 0 && <span className="text-xs text-red-600 ml-2">({errors} errors)</span>}
            {Object.keys(strata).length > 0 && (
              <span className="text-[10px] text-violet-700 ml-2">
                ({Object.entries(strata).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")})
              </span>
            )}
          </div>
        </div>
      )}

      {hasResults && (
        <>
          {/* Headline cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Replays" value={a.total_replays} sub={`${a.control_count} control + ${a.treatment_count} treatment`} />
            <StatCard
              label="Control Flip Rate"
              value={`${a.flip_rates.control}%`}
              sub={`${a.flip_rates.control_flips} flips (stochasticity)`}
            />
            <StatCard
              label="Treatment Flip Rate"
              value={`${a.flip_rates.treatment}%`}
              sub={`${a.flip_rates.treatment_flips} flips (enhanced)`}
              accent={a.flip_rates.net_effect > 0}
            />
            <StatCard
              label="Net Effect"
              value={`${a.flip_rates.net_effect > 0 ? "+" : ""}${a.flip_rates.net_effect}pp`}
              sub={a.mcnemar?.significant ? `p=${a.mcnemar.p_value} (significant)` : `p=${a.mcnemar?.p_value || "—"} (not sig.)`}
              accent={a.mcnemar?.significant}
            />
          </div>

          {/* McNemar contingency */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="border border-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">McNemar's Test (Paired Outcomes)</h3>
              <div className="text-xs space-y-1.5">
                <div className="flex justify-between"><span className="text-muted-foreground">Paired matches</span><span className="font-mono">{a.mcnemar?.pairs}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Both flipped</span><span className="font-mono">{a.mcnemar?.both_flip}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Only control flipped</span><span className="font-mono">{a.mcnemar?.only_control}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Only treatment flipped</span><span className="font-mono">{a.mcnemar?.only_treatment}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Neither flipped</span><span className="font-mono">{a.mcnemar?.neither}</span></div>
                <div className="border-t border-border pt-1.5 flex justify-between font-medium">
                  <span>Chi² = {a.mcnemar?.chi2}, p = {a.mcnemar?.p_value}</span>
                  <span className={a.mcnemar?.significant ? "text-green-600" : "text-muted-foreground"}>
                    {a.mcnemar?.significant ? "Significant" : "Not significant"}
                  </span>
                </div>
              </div>
            </div>

            {/* By stratum */}
            <div className="border border-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Flip Rate by Stratum</h3>
              <div className="text-xs space-y-2">
                {Object.entries(a.by_stratum || {}).map(([stratum, s]) => (
                  <div key={stratum}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-muted-foreground capitalize">{stratum.replace(/_/g, " ")}</span>
                      <span className="font-mono">
                        C: {s.control.rate}% ({s.control.flips}/{s.control.total})
                        {" · "}
                        T: {s.treatment.rate}% ({s.treatment.flips}/{s.treatment.total})
                      </span>
                    </div>
                    <div className="flex gap-1 h-3">
                      <div className="bg-secondary/50 rounded-full overflow-hidden flex-1" title="Control">
                        <div className="h-full bg-gray-400 rounded-full" style={{ width: `${s.control.rate}%` }} />
                      </div>
                      <div className="bg-violet-100 rounded-full overflow-hidden flex-1" title="Treatment">
                        <div className="h-full bg-violet-500 rounded-full" style={{ width: `${s.treatment.rate}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Per-paper rank shifts */}
          {a.paper_shifts?.length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Paper Rank Shifts (Treatment vs Original)</h3>
              <p className="text-[10px] text-muted-foreground mb-2">Papers most affected by enhanced assessments — positive = gained wins, negative = lost wins</p>
              <div className="space-y-1 text-xs">
                {a.paper_shifts.map((p, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className={`font-mono w-10 text-right font-medium ${p.net_shift > 0 ? "text-green-600" : p.net_shift < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                      {p.net_shift > 0 ? "+" : ""}{p.net_shift}
                    </span>
                    <span className="text-muted-foreground w-6 text-right">{p.wins_gained > 0 && `+${p.wins_gained}`}</span>
                    <span className="text-muted-foreground w-6 text-right">{p.wins_lost > 0 && `-${p.wins_lost}`}</span>
                    <span className="truncate">{p.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Per-category */}
          {Object.keys(a.by_category || {}).length > 0 && (
            <div className="border border-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">By Category</h3>
              <div className="text-xs space-y-1">
                {Object.entries(a.by_category).map(([cat, s]) => (
                  <div key={cat} className="flex items-center justify-between">
                    <span className="font-mono text-muted-foreground">{cat}</span>
                    <span className="font-mono">
                      Control: {s.control.flips}/{s.control.total}
                      {" · "}
                      Treatment: {s.treatment.flips}/{s.treatment.total}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Side-by-side or tabbed view of original vs enhanced assessment */
function AssessmentComparison({ original, enhanced }) {
  const [tab, setTab] = useState(enhanced ? "enhanced" : "original");

  if (!original && !enhanced) return null;

  return (
    <div className="space-y-2">
      <div className="flex gap-1 border border-border rounded-lg p-0.5 w-fit">
        {original && (
          <button onClick={() => setTab("original")}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${tab === "original" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
            Original Assessment
          </button>
        )}
        {enhanced && (
          <button onClick={() => setTab("enhanced")}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${tab === "enhanced" ? "bg-blue-100 text-blue-800" : "text-muted-foreground hover:text-foreground"}`}>
            Enhanced Assessment
          </button>
        )}
      </div>
      <div className="text-xs leading-relaxed text-foreground/90 max-h-96 overflow-y-auto whitespace-pre-wrap">
        {tab === "original" && original && <FormattedAssessment text={original} />}
        {tab === "enhanced" && enhanced && <FormattedAssessment text={enhanced} />}
      </div>
    </div>
  );
}

/** Render markdown-like assessment text with bold and headers */
function FormattedAssessment({ text }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (line.startsWith("### ") || line.startsWith("## ") || line.startsWith("# ")) {
          const clean = line.replace(/^#+\s*/, "").replace(/\*\*/g, "");
          return <p key={i} className="font-semibold text-foreground mt-2">{clean}</p>;
        }
        if (line.match(/^\*\*.*\*\*$/)) {
          return <p key={i} className="font-semibold text-foreground mt-2">{line.replace(/\*\*/g, "")}</p>;
        }
        const html = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        return <p key={i} dangerouslySetInnerHTML={{ __html: html }} />;
      })}
    </div>
  );
}

function StatCard({ label, value, sub, accent, enhanced }) {
  return (
    <div className={`border rounded-lg p-3 ${accent ? "border-amber-300 bg-amber-50/50" : enhanced ? "border-blue-300 bg-blue-50/50" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground mb-0.5">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}
