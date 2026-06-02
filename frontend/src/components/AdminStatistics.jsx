import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, BarChart, Bar, ComposedChart, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import ReactECharts from "echarts-for-react";
import {
  FileText, Swords, Coins, Cpu, TrendingUp, BarChart3,
  RefreshCw,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

const CATEGORY_COLORS = [
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#10b981", // emerald
  "#ef4444", // red
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#f97316", // orange
  "#14b8a6", // teal
  "#a855f7", // purple
  "#84cc16", // lime
  "#e11d48", // rose
  "#6366f1", // indigo
  "#0ea5e9", // sky
];

function getColor(cat, index) {
  return CATEGORY_COLORS[index % CATEGORY_COLORS.length];
}

function StatSummaryCard({ label, value, sub, icon: Icon, color }) {
  return (
    <div className="p-4 rounded-lg border border-border bg-card" data-testid={`stat-card-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <div className="flex items-center gap-2 mb-1.5">
        {Icon && <Icon className="h-4 w-4" style={{ color }} />}
        <span className="text-xs text-muted-foreground font-medium">{label}</span>
      </div>
      <div className="font-mono text-2xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function ChartCard({ title, icon: Icon, children, id }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4" data-testid={`chart-${id}`}>
      <div className="flex items-center gap-2 mb-4">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        <h3 className="text-sm font-medium">{title}</h3>
      </div>
      <div className="h-[260px]">
        {children}
      </div>
    </div>
  );
}

function formatTokens(val) {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
  return val;
}

function BackfillBadge({ status }) {
  if (!status) return null;
  const ok = status.reconciled;
  const ts = status.ts ? new Date(status.ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "";
  const title = ok
    ? `Stats reconciled · ${Number(status.daily_matches || 0).toLocaleString()} matches · last rebuild ${ts}`
    : `DRIFT: daily total ${Number(status.daily_matches || 0).toLocaleString()} vs expected ${Number(status.expected_matches || 0).toLocaleString()}${status.failed_chunks ? ` · ${status.failed_chunks} failed chunk(s)` : ""} · last rebuild ${ts}`;
  return (
    <span
      data-testid="backfill-reconcile-badge"
      title={title}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium border ${ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600" : "border-red-500/40 bg-red-500/10 text-red-600"}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500 animate-pulse"}`} />
      {ok ? "Reconciled" : "Drift detected"}
    </span>
  );
}

function formatCost(val) {
  return `$${Number(val).toFixed(2)}`;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function CustomTooltip({ active, payload, label, formatter }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover p-2.5 shadow-lg text-xs">
      <div className="font-medium mb-1.5">{formatDate(label)}</div>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-muted-foreground">{entry.name}</span>
          </div>
          <span className="font-mono font-medium">
            {formatter ? formatter(entry.value) : entry.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AdminStatistics({ categories }) {
  const [timeseries, setTimeseries] = useState(null);
  const [summaryStats, setSummaryStats] = useState(null);
  const [liveMatchStats, setLiveMatchStats] = useState(null);
  const [memoryData, setMemoryData] = useState(null);
  const [backfillStatus, setBackfillStatus] = useState(null);
  const [repairQueueData, setRepairQueueData] = useState(null);
  const [restartEvents, setRestartEvents] = useState([]);
  const [memHours, setMemHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState("cumulative"); // "daily" | "cumulative"
  const [scopeMode, setScopeMode] = useState("system"); // "system" | "category"

  const fetchData = useCallback(async (retryCount = 0, force = false) => {
    const headers = getAdminHeaders();
    const fetchWithRetry = async (url) => {
      try {
        return await axios.get(url, { headers });
      } catch (e) {
        if (retryCount < 2) throw e; // Let Promise.allSettled handle it
        return null;
      }
    };
    try {
      // Single source of truth: the admin2 endpoint returns `timeseries` (daily
      // series + cumulative totals), `stats` (per-model match/summary breakdowns)
      // and `user_registrations` (precomputed) — all reconciled from the same
      // backfill pass. Memory comes from the (cheap, indexed) system-logs endpoint.
      const results = await Promise.allSettled([
        fetchWithRetry(`${API}/api/admin2/stats-overview${force ? "?force=true" : ""}`),
        fetchWithRetry(`${API}/api/admin/system-logs?hours=${memHours}&limit=3000`),
      ]);
      const [tsResult, memResult] = results;

      // Retry once if the critical stats endpoint failed
      if (tsResult.status === "rejected" && retryCount < 2) {
        setTimeout(() => fetchData(retryCount + 1), 1500);
        return;
      }

      if (tsResult.status === "fulfilled" && tsResult.value) {
        const d = tsResult.value.data;
        setTimeseries(d.timeseries);
        setSummaryStats(d.stats?.summaries || null);
        setLiveMatchStats(d.stats || null);
        setBackfillStatus(d.backfill_status || null);
      }
      if (memResult.status === "fulfilled" && memResult.value) {
        const allLogs = memResult.value.data?.logs || [];
        const memLogs = allLogs.filter(l => l.level === "mem" && l.rss_mb);
        const chartData = memLogs.sort((a, b) => a.ts.localeCompare(b.ts)).map(l => ({
          ts: l.ts,
          epoch: new Date(l.ts.endsWith("Z") ? l.ts : l.ts + "Z").getTime(),
          rss: l.rss_mb,
          label: l.label,
          role: l.pod_role || "unknown",
        }));
        // Each role gets its own line
        const roles = [...new Set(chartData.map(d => d.role))];
        for (const d of chartData) {
          d[`rss_${d.role}`] = d.rss;
        }
        // Carry forward last known value per role, except "unknown" which should never extend
        const lastKnown = {};
        for (const d of chartData) {
          for (const r of roles) {
            if (d[`rss_${r}`] !== undefined && d[`rss_${r}`] !== null) {
              lastKnown[r] = d[`rss_${r}`];
            } else if (r === "unknown") {
              d[`rss_${r}`] = null; // Never carry forward legacy data
            } else {
              d[`rss_${r}`] = lastKnown[r] ?? null;
            }
          }
        }
        setMemoryData(chartData);
        // Extract restart events
        const restartEvents = allLogs
          .filter(l => l.label === "Server started" || l.label === "Deploy" || l.label === "Restart" || l.event === "server_started" || l.event === "shutdown_signal" || l.event === "server_shutdown")
          .map(l => ({
            ts: l.ts,
            epoch: new Date(l.ts.endsWith("Z") ? l.ts : l.ts + "Z").getTime(),
            role: l.pod_role || "unknown",
            event: l.event || (l.label === "Server started" ? "server_started" : "unknown"),
            label: l.label,
            signal: l.signal,
            reason: l.reason,
            is_deploy: l.is_deploy,
          }));
        setRestartEvents(restartEvents);
        const queueLogs = allLogs.filter(l => l.level === "repair_queue");
        const queueData = queueLogs.sort((a, b) => a.ts.localeCompare(b.ts)).map(l => ({
          ts: l.ts,
          epoch: new Date(l.ts.endsWith("Z") ? l.ts : l.ts + "Z").getTime(),
          size: l.size ?? 0,
          repaired: l.repaired ?? 0,
        }));
        setRepairQueueData(queueData);
      }
    } catch (err) {
      console.error("Failed to load stats:", err);
      if (retryCount < 2) {
        setTimeout(() => fetchData(retryCount + 1), 1500);
        return;
      }
    } finally {
      setLoading(false);
    }
  }, [memHours]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(), 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const _series = timeseries?.series || [];
  const _allCats = timeseries?.categories || [];
  const _totals = timeseries?.totals || {};
  const _modelStats = timeseries?.models || {};
  const suffix = viewMode === "cumulative" ? "cumulative" : "daily";

  // Stable color map (memoized)
  const catColorMap = useMemo(() => {
    const m = {};
    _allCats.forEach((cat, i) => { m[cat] = getColor(cat, i); });
    return m;
  }, [_allCats]);

  const nonEmptyCats = useMemo(() => {
    const lastDay = _series.length > 0 ? _series[_series.length - 1] : {};
    return _allCats.filter(cat => {
      const papers = lastDay[`papers_cumulative_${cat}`] || 0;
      const matches = lastDay[`matches_cumulative_${cat}`] || 0;
      return papers > 0 || matches > 0;
    });
  }, [_allCats, _series]);

  const MAX_CHART_CATS = 10;
  const chartCats = useMemo(() => {
    if (nonEmptyCats.length <= MAX_CHART_CATS) return nonEmptyCats;
    const lastDay = _series.length > 0 ? _series[_series.length - 1] : {};
    const sorted = [...nonEmptyCats].sort((a, b) =>
      (lastDay[`matches_cumulative_${b}`] || 0) - (lastDay[`matches_cumulative_${a}`] || 0)
    );
    return sorted.slice(0, MAX_CHART_CATS);
  }, [nonEmptyCats, _series]);

  const otherCats = useMemo(() => {
    if (nonEmptyCats.length <= MAX_CHART_CATS) return [];
    const top = new Set(chartCats);
    return nonEmptyCats.filter(c => !top.has(c));
  }, [nonEmptyCats, chartCats]);

  const lastDay = useMemo(() => _series.length > 0 ? _series[_series.length - 1] : {}, [_series]);

  const chartData = useMemo(() => _series.map(entry => {
    const d = { date: entry.date };
    if (scopeMode === "system") {
      d.papers = entry[`papers_${suffix}`] || 0;
      d.matches = entry[`matches_${suffix}`] || 0;
      d.tokens = entry[`tokens_${suffix}`] || 0;
      d.cost = entry[`cost_${suffix}`] || 0;
      d.input_tokens = entry[`input_tokens_daily`] || 0;
      d.output_tokens = entry[`output_tokens_daily`] || 0;
    } else {
      for (const cat of chartCats) {
        d[`papers_${cat}`] = entry[`papers_${suffix}_${cat}`] || 0;
        d[`matches_${cat}`] = entry[`matches_${suffix}_${cat}`] || 0;
        d[`tokens_${cat}`] = entry[`tokens_${suffix}_${cat}`] || 0;
        d[`cost_${cat}`] = entry[`cost_${suffix}_${cat}`] || 0;
      }
      if (otherCats.length > 0) {
        let op = 0, om = 0, ot = 0, oc = 0;
        for (const cat of otherCats) {
          op += entry[`papers_${suffix}_${cat}`] || 0;
          om += entry[`matches_${suffix}_${cat}`] || 0;
          ot += entry[`tokens_${suffix}_${cat}`] || 0;
          oc += entry[`cost_${suffix}_${cat}`] || 0;
        }
        d["papers_Other"] = op;
        d["matches_Other"] = om;
        d["tokens_Other"] = ot;
        d["cost_Other"] = oc;
      }
    }
    return d;
  }), [_series, scopeMode, suffix, chartCats, otherCats]);

  if (loading || !timeseries) {
    return (
      <div className="space-y-4" data-testid="admin-statistics-loading">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-32 bg-secondary/30 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  const series = _series;
  const totals = _totals;
  const modelStats = _modelStats;
  const allCats = _allCats;
  const modelCount = modelStats ? Object.keys(modelStats).length : 0;

  // High-performance ECharts (canvas) renderer for the time-series grid. Canvas
  // rendering stays snappy even with hundreds of days × many stacked categories,
  // unlike SVG. Visual style (colors, stacking, daily=bar / cumulative=area)
  // matches the previous Recharts output.
  const dates = chartData.map((d) => d.date);

  const renderChart = (metric, formatter) => {
    const fmtVal = formatter || ((v) => Number(v || 0).toLocaleString());
    const yFmt = metric === "cost" ? formatCost : (metric === "tokens" ? formatTokens : (v) => v.toLocaleString());
    const isDaily = viewMode === "daily";

    const mkBar = (name, color, key, stack) => ({
      name, type: "bar", stack,
      data: chartData.map((d) => d[key] || 0),
      itemStyle: { color, borderRadius: stack ? 0 : [3, 3, 0, 0] },
      large: true, largeThreshold: 100, barMaxWidth: 40,
    });
    const mkArea = (name, color, key, stack, opacity, width) => ({
      name, type: "line", stack, smooth: true, showSymbol: false, sampling: "lttb",
      data: chartData.map((d) => d[key] || 0),
      lineStyle: { color, width }, itemStyle: { color },
      areaStyle: { color, opacity },
    });

    let series;
    let legendData = null;
    if (scopeMode === "system") {
      const name = metric.charAt(0).toUpperCase() + metric.slice(1);
      series = [isDaily ? mkBar(name, "#3b82f6", metric, null) : mkArea(name, "#3b82f6", metric, null, 0.15, 2)];
    } else {
      series = chartCats.map((cat) => isDaily
        ? mkBar(cat, catColorMap[cat], `${metric}_${cat}`, "a")
        : mkArea(cat, catColorMap[cat], `${metric}_${cat}`, "a", 0.2, 1.5));
      if (otherCats.length > 0) {
        const oName = `Other (${otherCats.length})`;
        series.push(isDaily
          ? mkBar(oName, "#9ca3af", `${metric}_Other`, "a")
          : mkArea(oName, "#9ca3af", `${metric}_Other`, "a", 0.15, 1));
      }
      legendData = series.map((s) => s.name);
    }

    const option = {
      animation: false,
      grid: { top: legendData ? 28 : 10, right: 12, bottom: 24, left: 8, containLabel: true },
      legend: legendData ? { type: "scroll", top: 0, textStyle: { fontSize: 11 }, data: legendData, itemHeight: 8, itemWidth: 12 } : undefined,
      tooltip: {
        trigger: "axis",
        confine: true,
        textStyle: { fontSize: 11 },
        formatter: (params) => {
          if (!params || !params.length) return "";
          const rows = params.filter((p) => p.value).sort((a, b) => b.value - a.value);
          let html = `<b>${formatDate(params[0].axisValue)}</b>`;
          for (const p of rows) {
            html += `<br/>${p.marker}${p.seriesName}: <b>${fmtVal(p.value)}</b>`;
          }
          return html;
        },
      },
      xAxis: {
        type: "category", data: dates, boundaryGap: isDaily,
        axisLabel: { fontSize: 11, formatter: (v) => formatDate(v), hideOverlap: true, color: "#94a3b8" },
        axisLine: { lineStyle: { color: "hsl(var(--border))" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { fontSize: 11, formatter: (v) => yFmt(v), color: "#94a3b8" },
        splitLine: { lineStyle: { color: "hsl(var(--border))", opacity: 0.5, type: "dashed" } },
      },
      series,
    };

    return (
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    );
  };

  // Single source of truth: every aggregate figure comes from the timeseries
  // cumulative totals (daily_stats). The per-model match/summary panels below
  // are produced by the same backfill pass, so their row-sums equal these
  // totals exactly — cards, panel headers, rows, and charts all agree.
  const matchCost = totals.match_cost || 0;
  const summaryCost = totals.summary_cost || 0;
  const combinedCost = matchCost + summaryCost;
  const combinedTokens = totals.tokens || 0;
  const avgMatchesPerPaper = totals.papers > 0 ? totals.matches / totals.papers : 0;
  const avgMatchCostPerPaper = totals.papers > 0 ? matchCost / totals.papers : 0;
  const avgSummaryCostPerPaper = totals.papers > 0 ? summaryCost / totals.papers : 0;
  const avgTotalCostPerPaper = avgMatchCostPerPaper + avgSummaryCostPerPaper;

  return (
    <div className="space-y-6" data-testid="admin-statistics">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatSummaryCard label="Total Papers" value={totals.papers.toLocaleString()} icon={FileText} color="#3b82f6" />
        <StatSummaryCard label="Total Matches" value={totals.matches.toLocaleString()} sub={`${avgMatchesPerPaper.toFixed(1)} per paper`} icon={Swords} color="#8b5cf6" />
        <StatSummaryCard
          label="Total Tokens"
          value={formatTokens(combinedTokens)}
          sub={`${formatTokens(totals.input_tokens || 0)} in / ${formatTokens(totals.output_tokens || 0)} out (matches)`}
          icon={Cpu} color="#10b981"
        />
        <StatSummaryCard
          label="Total Cost"
          value={`$${combinedCost.toFixed(2)}`}
          sub={summaryCost > 0 ? `$${matchCost.toFixed(0)} matches + $${summaryCost.toFixed(0)} summaries` : `${modelCount} models`}
          icon={Coins} color="#f59e0b"
        />
        <StatSummaryCard
          label="Cost / Paper"
          value={`$${avgTotalCostPerPaper.toFixed(2)}`}
          sub={`$${avgMatchCostPerPaper.toFixed(2)} matches + $${avgSummaryCostPerPaper.toFixed(2)} summaries`}
          icon={Coins} color="#ec4899"
        />
      </div>

      {/* Cost per Paper over time */}
      {series.length > 5 && (
        <div className="rounded-lg border border-border bg-card p-4" data-testid="cost-per-paper-chart">
          <h3 className="text-sm font-medium mb-1">Cost / Paper Over Time</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Running average: cumulative cost / cumulative papers at each date</p>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={series.filter(e => (e.papers_cumulative || 0) > 50).map(e => {
                const p = e.papers_cumulative || 1;
                return {
                  date: e.date,
                  total: +((e.cost_cumulative || 0) / p).toFixed(4),
                  matches: +((e.match_cost_cumulative || 0) / p).toFixed(4),
                  summaries: +((e.summary_cost_cumulative || 0) / p).toFixed(4),
                };
              })} margin={{ top: 5, right: 10, left: 5, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                <YAxis tickFormatter={v => `$${v.toFixed(2)}`} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={50} domain={[0, 'auto']} />
                <RechartsTooltip content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  return (
                    <div className="bg-background border border-border rounded-lg p-2 text-xs shadow-md">
                      <p className="font-medium mb-1">{label ? new Date(label + "T00:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"}) : ""}</p>
                      {payload.map(p => (
                        <p key={p.name} style={{ color: p.color }}>{p.name}: ${Number(p.value).toFixed(3)}</p>
                      ))}
                    </div>
                  );
                }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area type="monotone" dataKey="total" stroke="#ec4899" fill="#ec4899" fillOpacity={0.08} strokeWidth={2} name="Total $/paper" isAnimationActive={false} />
                <Area type="monotone" dataKey="matches" stroke="#3b82f6" fill="none" strokeWidth={1.5} strokeDasharray="4 2" name="Match $/paper" isAnimationActive={false} />
                <Area type="monotone" dataKey="summaries" stroke="#10b981" fill="none" strokeWidth={1.5} strokeDasharray="4 2" name="Summary $/paper" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Cost breakdown — Match Costs vs Summary Costs side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Match costs — prefer live stats endpoint over timeseries */}
        {((liveMatchStats?.models && Object.keys(liveMatchStats.models).length > 0) || (modelStats && Object.keys(modelStats).length > 0)) && (() => {
          const mStats = (liveMatchStats?.models && Object.keys(liveMatchStats.models).length > 0) ? liveMatchStats.models : modelStats;
          return (
          <div className="rounded-lg border border-border bg-card p-4" data-testid="match-cost-breakdown">
            <h3 className="text-sm font-medium mb-1">Match Costs</h3>
            <p className="text-[10px] text-muted-foreground mb-3">${matchCost.toFixed(0)} total across {Object.values(mStats).reduce((s,m) => s + (m.matches||0), 0).toLocaleString()} comparisons</p>
            <div className="space-y-1.5">
              {Object.entries(mStats)
                .filter(([, s]) => (s.matches || 0) > 0)
                .sort((a, b) => (b[1].cost_total || 0) - (a[1].cost_total || 0))
                .map(([model, stats], idx) => {
                  const cost = stats.cost_total || 0;
                  const pct = matchCost > 0 ? (cost / matchCost) * 100 : 0;
                  return (
                    <div key={model} className="flex items-center gap-2">
                      <span className="text-[10px] font-mono w-32 shrink-0 truncate" title={model}>{model.split("/").pop()}</span>
                      <div className="flex-1 h-4 bg-secondary/50 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: getColor(model, idx) }} />
                      </div>
                      <span className="text-[10px] font-mono text-muted-foreground shrink-0 w-24 text-right">
                        {(stats.matches || 0).toLocaleString()} &middot; ${cost.toFixed(0)}
                      </span>
                      <span className="text-[10px] font-mono w-8 text-right text-muted-foreground">{pct.toFixed(0)}%</span>
                    </div>
                  );
                })}
            </div>
          </div>
          );
        })()}

        {/* Summary costs */}
        {summaryStats?.models && Object.keys(summaryStats.models).length > 0 && (
          <div className="rounded-lg border border-border bg-card p-4" data-testid="summary-cost-breakdown">
            <h3 className="text-sm font-medium mb-1">Summary Costs</h3>
            <p className="text-[10px] text-muted-foreground mb-3">${summaryCost.toFixed(0)} total across {Object.values(summaryStats.models).reduce((s,m) => s + (m.summaries||0), 0).toLocaleString()} summaries</p>
            <div className="space-y-1.5">
              {Object.entries(summaryStats.models)
                .filter(([, s]) => (s.summaries || 0) > 0)
                .sort((a, b) => (b[1].cost_total || 0) - (a[1].cost_total || 0))
                .map(([mk, stats], idx) => {
                  const cost = stats.cost_total || 0;
                  const pct = summaryCost > 0 ? (cost / summaryCost) * 100 : 0;
                  const label = mk.split(":").slice(1).join(":").replace(/_/g, ".") || mk;
                  return (
                    <div key={mk} className="flex items-center gap-2">
                      <span className="text-[10px] font-mono w-32 shrink-0 truncate" title={mk}>{label}</span>
                      <div className="flex-1 h-4 bg-secondary/50 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: getColor(mk, idx + 10) }} />
                      </div>
                      <span className="text-[10px] font-mono text-muted-foreground shrink-0 w-24 text-right">
                        {(stats.summaries || 0).toLocaleString()} &middot; ${cost.toFixed(0)}
                      </span>
                      <span className="text-[10px] font-mono w-8 text-right text-muted-foreground">{pct.toFixed(0)}%</span>
                    </div>
                  );
                })}
            </div>
          </div>
        )}
      </div>

      {/* Repair Queue History */}
      {repairQueueData && repairQueueData.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4" data-testid="repair-queue-chart">
          <div className="flex items-center gap-2 mb-4">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-medium">Repair Queue Size</h3>
            <span className="text-xs text-muted-foreground">
              Current: {repairQueueData[repairQueueData.length - 1]?.size ?? 0}
            </span>
          </div>
          <div className="h-[140px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={repairQueueData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis
                  dataKey="epoch" type="number" scale="time" domain={["dataMin", "dataMax"]}
                  tickFormatter={(epoch) => {
                    const d = new Date(epoch);
                    const opts = { timeZone: "Europe/Berlin" };
                    return memHours > 24
                      ? d.toLocaleDateString("en-US", { ...opts, month: "short", day: "numeric" }) + " " + d.toLocaleTimeString("en-US", { ...opts, hour: "2-digit", minute: "2-digit", hour12: false })
                      : d.toLocaleTimeString("en-US", { ...opts, hour: "2-digit", minute: "2-digit", hour12: false });
                  }}
                  tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))"
                  tickCount={6}
                />
                <YAxis allowDecimals={false} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={30} />
                <RechartsTooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0]?.payload;
                    return (
                      <div className="rounded-lg border border-border bg-popover p-2 shadow-lg text-xs">
                        <div className="font-medium">{d?.ts ? new Date(d.ts.endsWith("Z") ? d.ts : d.ts + "Z").toLocaleString("en-US", { timeZone: "Europe/Berlin", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " CET" : ""}</div>
                        <div className="font-mono mt-1">Queue: {d?.size} {d?.repaired > 0 && <span className="text-emerald-600">(repaired {d.repaired})</span>}</div>
                      </div>
                    );
                  }}
                />
                <Area type="stepAfter" dataKey="size" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.15} strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Chart controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
          <Button
            variant={viewMode === "cumulative" ? "default" : "ghost"} size="sm" className="h-7 text-xs gap-1"
            onClick={() => setViewMode("cumulative")} data-testid="toggle-cumulative"
          >
            <TrendingUp className="h-3 w-3" /> Cumulative
          </Button>
          <Button
            variant={viewMode === "daily" ? "default" : "ghost"} size="sm" className="h-7 text-xs gap-1"
            onClick={() => setViewMode("daily")} data-testid="toggle-daily"
          >
            <BarChart3 className="h-3 w-3" /> Daily
          </Button>
        </div>
        <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
          <Button
            variant={scopeMode === "system" ? "default" : "ghost"} size="sm" className="h-7 text-xs"
            onClick={() => setScopeMode("system")} data-testid="toggle-system"
          >
            System
          </Button>
          <Button
            variant={scopeMode === "category" ? "default" : "ghost"} size="sm" className="h-7 text-xs"
            onClick={() => setScopeMode("category")} data-testid="toggle-category"
          >
            By Category
          </Button>
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <BackfillBadge status={backfillStatus} />
          {timeseries?.refreshed_at && (
            <span className="text-[10px] text-muted-foreground">
              {new Date(timeseries.refreshed_at).toLocaleString("en-US", {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false})}
            </span>
          )}
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1"
            onClick={() => { setLoading(true); fetchData(0, true); }} data-testid="refresh-charts"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </Button>
        </div>
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Papers" icon={FileText} id="papers">
          {renderChart("papers")}
        </ChartCard>
        <ChartCard title="Matches" icon={Swords} id="matches">
          {renderChart("matches")}
        </ChartCard>
        <ChartCard title="Tokens" icon={Cpu} id="tokens">
          {renderChart("tokens", formatTokens)}
        </ChartCard>
        <ChartCard title="Cost" icon={Coins} id="cost">
          {renderChart("cost", formatCost)}
        </ChartCard>
      </div>

      {/* Per-category daily table */}
      {scopeMode === "category" && (
        <div className="rounded-lg border border-border bg-card p-4 overflow-x-auto" data-testid="category-table">
          <h3 className="text-sm font-medium mb-3">Per-Category Totals</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted-foreground font-medium">Category</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Papers</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Matches</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Tokens</th>
                <th className="text-right py-2 pl-3 text-muted-foreground font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {nonEmptyCats.map(cat => {
                return (
                  <tr key={cat} className="border-b border-border/50">
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: catColorMap[cat] }} />
                        <span className="font-mono">{cat}</span>
                      </div>
                    </td>
                    <td className="text-right py-2 px-3 font-mono">{(lastDay[`papers_cumulative_${cat}`] || 0).toLocaleString()}</td>
                    <td className="text-right py-2 px-3 font-mono">{(lastDay[`matches_cumulative_${cat}`] || 0).toLocaleString()}</td>
                    <td className="text-right py-2 px-3 font-mono">{formatTokens(lastDay[`tokens_cumulative_${cat}`] || 0)}</td>
                    <td className="text-right py-2 pl-3 font-mono">${(lastDay[`cost_cumulative_${cat}`] || 0).toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Memory Usage Over Time */}
      {memoryData && memoryData.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4" data-testid="memory-chart">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-muted-foreground" />
              <h3 className="text-sm font-medium">Memory Usage (RSS)</h3>
              <span className="text-xs text-muted-foreground">
                Current: {Math.round(memoryData[memoryData.length - 1]?.rss)}MB / 4096MB
              </span>
            </div>
            <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md">
              {[6, 12, 24, 72, 168].map(h => (
                <Button
                  key={h}
                  variant={memHours === h ? "default" : "ghost"}
                  size="sm" className="h-6 text-[10px] px-2"
                  onClick={() => setMemHours(h)}
                >
                  {h <= 24 ? `${h}h` : `${h/24}d`}
                </Button>
              ))}
            </div>
          </div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={memoryData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis
                  dataKey="epoch"
                  type="number"
                  scale="time"
                  domain={[Date.now() - memHours * 3600000, Date.now()]}
                  tickFormatter={(epoch) => {
                    const d = new Date(epoch);
                    const opts = { timeZone: "Europe/Berlin" };
                    if (memHours > 24) {
                      return d.toLocaleDateString("en-US", { ...opts, month: "short", day: "numeric" }) + " " +
                             d.toLocaleTimeString("en-US", { ...opts, hour: "2-digit", minute: "2-digit", hour12: false });
                    }
                    return d.toLocaleTimeString("en-US", { ...opts, hour: "2-digit", minute: "2-digit", hour12: false });
                  }}
                  tick={{ fontSize: 10 }}
                  stroke="hsl(var(--muted-foreground))"
                  tickCount={memHours <= 12 ? 6 : memHours <= 24 ? 8 : 6}
                  minTickGap={60}
                />
                <YAxis domain={[0, 4096]} ticks={[0, 1024, 2048, 3072, 4096]} tickFormatter={v => `${v}MB`} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={55} />
                <RechartsTooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0]?.payload;
                    // Find any restart events within 2 minutes of this data point
                    const epoch = d?.epoch || label;
                    const nearbyEvents = restartEvents.filter(e => Math.abs(e.epoch - epoch) < 120000);
                    const eventLabels = {"deploy": "Deploy", "restart": "Restart", "sigterm": "SIGTERM", "oom": "Kill"};
                    const eventColors = {"deploy": "#8b5cf6", "restart": "#6b7280", "sigterm": "#f59e0b", "oom": "#ef4444"};
                    return (
                      <div className="rounded-lg border border-border bg-popover p-2 shadow-lg text-xs">
                        <div className="font-medium">{d?.ts ? new Date(d.ts.endsWith("Z") ? d.ts : d.ts + "Z").toLocaleString("en-US", { timeZone: "Europe/Berlin", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " CET" : ""}</div>
                        <div className="text-muted-foreground mt-0.5">{d?.label}</div>
                        {d?.role && d.role !== "unknown" && <div style={{ color: d.role === "leader" ? "#ef4444" : "#3b82f6" }}>{d.role.charAt(0).toUpperCase() + d.role.slice(1)}</div>}
                        <div className="font-mono mt-1" style={{ color: d?.rss > 1536 ? "#ef4444" : d?.rss > 1024 ? "#f59e0b" : "#10b981" }}>
                          {Math.round(d?.rss)}MB
                        </div>
                        {nearbyEvents.length > 0 && (
                          <div className="mt-1.5 pt-1.5 border-t border-border space-y-0.5">
                            {nearbyEvents.map((evt, i) => {
                              let type = evt.is_deploy || evt.label === "Deploy" ? "deploy" : evt.signal === "SIGTERM" ? "sigterm" : evt.event === "server_shutdown" ? "oom" : "restart";
                              return (
                                <div key={i} style={{ color: eventColors[type] }} className="font-medium">
                                  {eventLabels[type]}{evt.role && evt.role !== "unknown" ? ` (${evt.role})` : ""}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  }}
                />
                {/* Restart markers — labeled at top with event type + role */}
                {(() => {
                  const roleLabels = {"leader": "L", "follower": "F", "unknown": ""};
                  const roleColors = {"leader": "#ef4444", "follower": "#3b82f6", "unknown": "#6b7280"};
                  const eventStyles = {
                    "deploy": { dash: "none", width: 2, color: "#8b5cf6", label: "D" },       // solid purple
                    "restart": { dash: "4 4", width: 1.5, color: "#6b7280", label: "R" },      // dashed grey
                    "sigterm": { dash: "6 4", width: 2.5, color: "#f59e0b", label: "T" },       // dashed amber
                    "oom": { dash: "2 2", width: 2.5, color: "#ef4444", label: "K" },           // dotted red
                  };
                  const markers = [];
                  restartEvents.forEach((d, i) => {
                    let type;
                    if (d.label === "Deploy" || d.is_deploy) type = "deploy";
                    else if (d.event === "shutdown_signal" && d.signal === "SIGTERM") type = "sigterm";
                    else if (d.event === "server_shutdown" && (!d.reason || d.reason === "unknown")) type = "oom";
                    else if (d.event === "server_started" || d.label === "Server started" || d.label === "Restart") type = "restart";
                    else return;
                    const style = eventStyles[type];
                    const podLabel = roleLabels[d.role] || "";
                    markers.push(
                      <ReferenceLine key={`mark-${i}`} x={d.epoch}
                        stroke={style.color}
                        strokeDasharray={style.dash}
                        strokeWidth={style.width}
                        opacity={0.85}
                      />
                    );
                  });
                  return markers;
                })()}
                {/* Danger zone */}
                <Area type="monotone" dataKey={() => 4096} stroke="none" fill="#ef4444" fillOpacity={0.05} />
                {/* Per-role memory lines: leader (red), follower (blue), unknown/legacy (grey) */}
                {(() => {
                  const roleColors = {"leader": "#ef4444", "follower": "#3b82f6", "unknown": "#9ca3af"};
                  const roles = [...new Set(memoryData.map(d => d.role).filter(Boolean))];
                  const sorted = roles.sort((a, b) => a === "unknown" ? -1 : b === "unknown" ? 1 : a === "leader" ? -1 : 1);
                  return sorted.map((role) => (
                    <Area key={role} type="stepAfter" dataKey={`rss_${role}`}
                      stroke={roleColors[role] || "#9ca3af"}
                      fill={roleColors[role] || "#9ca3af"}
                      fillOpacity={role === "unknown" ? 0.03 : 0.05}
                      strokeWidth={role === "unknown" ? 1 : 1.5}
                      dot={false} connectNulls={false} isAnimationActive={false}
                      name={role === "unknown" ? "pre-deploy" : role.charAt(0).toUpperCase() + role.slice(1)} />
                  ));
                })()}
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap items-center gap-4 mt-2 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" /> &lt;1GB Safe</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500" /> 1-1.5GB Warning</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" /> &gt;1.5GB Danger</span>
            <span className="flex items-center gap-1 ml-2 border-l pl-2 border-border"><span className="w-4 border-t-2 border-purple-500" /> <b className="text-purple-500">D</b> Deploy</span>
            <span className="flex items-center gap-1"><span className="w-4 border-t border-dashed border-gray-500" /> <b className="text-gray-500">R</b> Restart</span>
            <span className="flex items-center gap-1"><span className="w-4 border-t-[2.5px] border-dashed border-amber-500" /> <b className="text-amber-500">T</b> SIGTERM</span>
            <span className="flex items-center gap-1"><span className="w-4 border-t-2 border-dotted border-red-500" /> <b className="text-red-500">K</b> Kill</span>
            {(() => {
              const roles = [...new Set(memoryData.map(d => d.role).filter(r => r && r !== "unknown"))];
              if (roles.length === 0) return null;
              const roleColors = {"leader": "#ef4444", "follower": "#3b82f6"};
              const roleDesc = {"leader": "fetch, compare, summarize, archive", "follower": "HTTP, cache, prewarm, analysis"};
              return <>
                <span className="ml-2 border-l pl-2 border-border">Pods:</span>
                {roles.map((role) => (
                  <span key={role} className="flex items-center gap-1" title={roleDesc[role]}>
                    <span className="w-3 h-0.5" style={{ backgroundColor: roleColors[role] }} />
                    {role.charAt(0).toUpperCase() + role.slice(1)} <span className="opacity-50">({roleDesc[role]})</span>
                  </span>
                ))}
              </>;
            })()}
          </div>
        </div>
      )}

    </div>
  );
}
