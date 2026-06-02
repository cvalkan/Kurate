import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  FileText, Swords, Coins, Cpu, TrendingUp, BarChart3, RefreshCw,
  Database, Users, MemoryStick, ArrowLeft,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

const CAT_COLORS = [
  "#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899",
  "#06b6d4", "#f97316", "#14b8a6", "#a855f7", "#84cc16", "#e11d48",
];
const MODEL_COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ec4899", "#06b6d4", "#f97316", "#a855f7", "#84cc16"];

function fmtTokens(v) {
  v = Number(v) || 0;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v;
}
function fmtCost(v) { return `$${Number(v || 0).toFixed(2)}`; }
function fmtNum(v) { return (Number(v) || 0).toLocaleString(); }
function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function StatCard({ label, value, sub, icon: Icon, color, testid }) {
  return (
    <div className="p-4 rounded-lg border border-border bg-card" data-testid={testid}>
      <div className="flex items-center gap-2 mb-1.5">
        {Icon && <Icon className="h-4 w-4" style={{ color }} />}
        <span className="text-xs text-muted-foreground font-medium">{label}</span>
      </div>
      <div className="font-mono text-2xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function ChartCard({ title, icon: Icon, children, right, testid }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4" data-testid={testid}>
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
        {right}
      </div>
      <div className="h-[260px]">{children}</div>
    </div>
  );
}

function Toggle({ options, value, onChange, testidPrefix }) {
  return (
    <div className="inline-flex rounded-md border border-border overflow-hidden">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          data-testid={`${testidPrefix}-${o.value}`}
          className={`px-2.5 py-1 text-xs font-medium transition-colors ${
            value === o.value ? "bg-primary text-primary-foreground" : "bg-transparent text-muted-foreground hover:bg-secondary/50"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function CostPanel({ title, models, totalCost, testid }) {
  const max = Math.max(...models.map((m) => m.cost), 1);
  return (
    <div className="rounded-lg border border-border bg-card p-4" data-testid={testid}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{fmtCost(totalCost)}</span>
      </div>
      <div className="space-y-3">
        {models.length === 0 && <div className="text-xs text-muted-foreground">No data</div>}
        {models.map((m, i) => (
          <div key={m.name} data-testid={`${testid}-row-${i}`}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="font-mono truncate max-w-[55%]" title={m.name}>{m.name}</span>
              <span className="text-muted-foreground">
                {fmtNum(m.count)} · <span className="font-mono">{fmtCost(m.cost)}</span> · {m.pct}%
              </span>
            </div>
            <div className="h-2 rounded-full bg-secondary/50 overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${(m.cost / max) * 100}%`, backgroundColor: MODEL_COLORS[i % MODEL_COLORS.length] }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Admin2StatsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [memory, setMemory] = useState(null);
  const [memHours, setMemHours] = useState(24);
  const [viewMode, setViewMode] = useState("cumulative"); // cumulative | daily
  const [scopeMode, setScopeMode] = useState("system"); // system | category

  const fetchData = useCallback(async (force = false) => {
    try {
      if (!sessionStorage.getItem("admin_token")) { navigate("/admin"); return; }
      const url = `${API}/api/admin2/stats-overview${force ? "?force=true" : ""}`;
      const res = await axios.get(url, { headers: getAdminHeaders() });
      setData(res.data);
    } catch (e) {
      if (e?.response?.status === 401 || e?.response?.status === 403) navigate("/admin");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [navigate]);

  const fetchMemory = useCallback(async (hours) => {
    try {
      const res = await axios.get(`${API}/api/admin2/memory?hours=${hours}`, { headers: getAdminHeaders() });
      const points = (res.data?.points || []).map((p) => ({
        epoch: new Date(p.ts.endsWith("Z") ? p.ts : p.ts + "Z").getTime(),
        rss: p.rss_mb,
        role: p.pod_role || "unknown",
      }));
      const roles = [...new Set(points.map((p) => p.role))];
      for (const p of points) p[`rss_${p.role}`] = p.rss;
      const lastKnown = {};
      for (const p of points) {
        for (const r of roles) {
          if (p[`rss_${r}`] != null) lastKnown[r] = p[`rss_${r}`];
          else p[`rss_${r}`] = r === "unknown" ? null : (lastKnown[r] ?? null);
        }
      }
      setMemory({ points, roles });
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { fetchMemory(memHours); }, [memHours, fetchMemory]);

  const handleRefresh = () => { setRefreshing(true); fetchData(true); fetchMemory(memHours); };

  const series = data?.series || [];
  const allCats = data?.categories || [];
  const summary = data?.summary || {};
  const suffix = viewMode === "cumulative" ? "cumulative" : "daily";

  const catColorMap = useMemo(() => {
    const m = {};
    allCats.forEach((c, i) => { m[c] = CAT_COLORS[i % CAT_COLORS.length]; });
    return m;
  }, [allCats]);

  const lastDay = useMemo(() => (series.length ? series[series.length - 1] : {}), [series]);

  const nonEmptyCats = useMemo(() => allCats.filter((c) =>
    (lastDay[`papers_cumulative_${c}`] || 0) > 0 || (lastDay[`matches_cumulative_${c}`] || 0) > 0
  ), [allCats, lastDay]);

  const MAX = 10;
  const chartCats = useMemo(() => {
    if (nonEmptyCats.length <= MAX) return nonEmptyCats;
    return [...nonEmptyCats].sort((a, b) =>
      (lastDay[`matches_cumulative_${b}`] || 0) - (lastDay[`matches_cumulative_${a}`] || 0)
    ).slice(0, MAX);
  }, [nonEmptyCats, lastDay]);

  const otherCats = useMemo(() => {
    if (nonEmptyCats.length <= MAX) return [];
    const top = new Set(chartCats);
    return nonEmptyCats.filter((c) => !top.has(c));
  }, [nonEmptyCats, chartCats]);

  const chartData = useMemo(() => series.map((e) => {
    const d = { date: e.date };
    if (scopeMode === "system") {
      d.papers = e[`papers_${suffix}`] || 0;
      d.matches = e[`matches_${suffix}`] || 0;
      d.tokens = e[`tokens_${suffix}`] || 0;
      d.cost = e[`cost_${suffix}`] || 0;
    } else {
      for (const c of chartCats) {
        d[`papers_${c}`] = e[`papers_${suffix}_${c}`] || 0;
        d[`matches_${c}`] = e[`matches_${suffix}_${c}`] || 0;
        d[`tokens_${c}`] = e[`tokens_${suffix}_${c}`] || 0;
        d[`cost_${c}`] = e[`cost_${suffix}_${c}`] || 0;
      }
      if (otherCats.length) {
        let op = 0, om = 0, ot = 0, oc = 0;
        for (const c of otherCats) {
          op += e[`papers_${suffix}_${c}`] || 0;
          om += e[`matches_${suffix}_${c}`] || 0;
          ot += e[`tokens_${suffix}_${c}`] || 0;
          oc += e[`cost_${suffix}_${c}`] || 0;
        }
        d.papers_Other = op; d.matches_Other = om; d.tokens_Other = ot; d.cost_Other = oc;
      }
    }
    return d;
  }), [series, scopeMode, suffix, chartCats, otherCats]);

  const costPerPaper = useMemo(() => series.map((e) => {
    const p = e.papers_cumulative || 0;
    return {
      date: e.date,
      total: p ? (e.cost_cumulative || 0) / p : 0,
      match: p ? (e.match_cost_cumulative || 0) / p : 0,
      summary: p ? (e.summary_cost_cumulative || 0) / p : 0,
    };
  }), [series]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-4" data-testid="admin2-loading">
        {[...Array(4)].map((_, i) => <div key={i} className="h-32 bg-secondary/30 rounded-lg animate-pulse" />)}
      </div>
    );
  }

  const ChartType = viewMode === "daily" ? BarChart : AreaChart;

  const renderMetric = (metric, fmt) => (
    <ResponsiveContainer width="100%" height="100%">
      <ChartType data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
        <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
        <YAxis tickFormatter={metric === "cost" ? fmtCost : metric === "tokens" ? fmtTokens : undefined} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={55} />
        <RTooltip formatter={(v) => (fmt ? fmt(v) : fmtNum(v))} labelFormatter={fmtDate} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
        {scopeMode === "category" && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {scopeMode === "system" ? (
          viewMode === "daily"
            ? <Bar dataKey={metric} fill="#3b82f6" radius={[3, 3, 0, 0]} />
            : <Area type="monotone" dataKey={metric} stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} strokeWidth={2} />
        ) : (
          <>
            {chartCats.map((c) => viewMode === "daily"
              ? <Bar key={c} dataKey={`${metric}_${c}`} stackId="a" fill={catColorMap[c]} name={c} />
              : <Area key={c} type="monotone" dataKey={`${metric}_${c}`} stackId="a" stroke={catColorMap[c]} fill={catColorMap[c]} fillOpacity={0.2} strokeWidth={1.5} name={c} />)}
            {otherCats.length > 0 && (viewMode === "daily"
              ? <Bar key="Other" dataKey={`${metric}_Other`} stackId="a" fill="#9ca3af" name={`Other (${otherCats.length})`} />
              : <Area key="Other" type="monotone" dataKey={`${metric}_Other`} stackId="a" stroke="#9ca3af" fill="#9ca3af" fillOpacity={0.15} strokeWidth={1} name={`Other (${otherCats.length})`} />)}
          </>
        )}
      </ChartType>
    </ResponsiveContainer>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6" data-testid="admin2-stats-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Database className="h-5 w-5 text-primary" /> Statistics v2
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Scalable analytics · reads pre-aggregated data only
            {data?.refreshed_at && <> · updated {new Date(data.refreshed_at).toLocaleTimeString()}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate("/admin/dashboard")} data-testid="admin2-back-btn">
            <ArrowLeft className="h-4 w-4 mr-1" /> Dashboard
          </Button>
          <Button size="sm" onClick={handleRefresh} disabled={refreshing} data-testid="admin2-refresh-btn">
            <RefreshCw className={`h-4 w-4 mr-1 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </div>

      {data?.backfilling && !data?.data_complete && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 px-4 py-2 text-xs text-amber-800 dark:text-amber-200" data-testid="admin2-backfill-banner">
          Building statistics in the background… numbers will fill in shortly. Refresh in ~1 minute.
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="admin2-summary-cards">
        <StatCard testid="admin2-card-papers" label="Total Papers" value={fmtNum(summary.total_papers)} icon={FileText} color="#3b82f6" />
        <StatCard testid="admin2-card-matches" label="Total Matches" value={fmtNum(summary.total_matches)} sub={`${summary.avg_matches_per_paper} / paper`} icon={Swords} color="#f59e0b" />
        <StatCard testid="admin2-card-tokens" label="Total Tokens" value={fmtTokens(summary.total_tokens)} sub={`${fmtTokens(summary.input_tokens)} in / ${fmtTokens(summary.output_tokens)} out`} icon={Cpu} color="#10b981" />
        <StatCard testid="admin2-card-cost" label="Total Cost" value={fmtCost(summary.total_cost)} sub={`${fmtCost(summary.match_cost)} match / ${fmtCost(summary.summary_cost)} summary`} icon={Coins} color="#ef4444" />
        <StatCard testid="admin2-card-cost-per-paper" label="Cost / Paper" value={fmtCost(summary.cost_per_paper)} sub={`${fmtCost(summary.match_cost_per_paper)} + ${fmtCost(summary.summary_cost_per_paper)}`} icon={TrendingUp} color="#8b5cf6" />
      </div>

      {/* Cost per paper over time */}
      <ChartCard title="Cost per Paper Over Time" icon={TrendingUp} testid="admin2-chart-cost-per-paper">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={costPerPaper} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
            <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
            <YAxis tickFormatter={(v) => `$${Number(v).toFixed(2)}`} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={55} />
            <RTooltip formatter={(v) => `$${Number(v).toFixed(3)}`} labelFormatter={fmtDate} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="total" name="Total $/paper" stroke="#ef4444" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="match" name="Match $/paper" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="summary" name="Summary $/paper" stroke="#10b981" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      {/* Cost panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <CostPanel testid="admin2-match-costs" title="Match Costs by Model" models={data?.match_models || []} totalCost={summary.match_cost} />
        <CostPanel testid="admin2-summary-costs" title="Summary Costs by Model" models={data?.summary_models || []} totalCost={summary.summary_cost} />
      </div>

      {/* Timeseries grid */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <BarChart3 className="h-4 w-4" /> Time Series
        </h2>
        <div className="flex items-center gap-2">
          <Toggle testidPrefix="admin2-view" options={[{ label: "Cumulative", value: "cumulative" }, { label: "Daily", value: "daily" }]} value={viewMode} onChange={setViewMode} />
          <Toggle testidPrefix="admin2-scope" options={[{ label: "System", value: "system" }, { label: "By Category", value: "category" }]} value={scopeMode} onChange={setScopeMode} />
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Papers" icon={FileText} testid="admin2-ts-papers">{renderMetric("papers", fmtNum)}</ChartCard>
        <ChartCard title="Matches" icon={Swords} testid="admin2-ts-matches">{renderMetric("matches", fmtNum)}</ChartCard>
        <ChartCard title="Tokens" icon={Cpu} testid="admin2-ts-tokens">{renderMetric("tokens", fmtTokens)}</ChartCard>
        <ChartCard title="Cost" icon={Coins} testid="admin2-ts-cost">{renderMetric("cost", fmtCost)}</ChartCard>
      </div>

      {/* Per-category totals table */}
      {scopeMode === "category" && nonEmptyCats.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 overflow-x-auto" data-testid="admin2-category-table">
          <h3 className="text-sm font-medium mb-3">Per-Category Totals</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground text-left border-b border-border">
                <th className="py-1.5 pr-4">Category</th>
                <th className="py-1.5 pr-4 text-right">Papers</th>
                <th className="py-1.5 pr-4 text-right">Matches</th>
                <th className="py-1.5 pr-4 text-right">Tokens</th>
                <th className="py-1.5 text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {[...nonEmptyCats].sort((a, b) => (lastDay[`matches_cumulative_${b}`] || 0) - (lastDay[`matches_cumulative_${a}`] || 0)).map((c, i) => (
                <tr key={c} className="border-b border-border/50" data-testid={`admin2-cat-row-${i}`}>
                  <td className="py-1.5 pr-4 font-mono flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: catColorMap[c] }} /> {c}
                  </td>
                  <td className="py-1.5 pr-4 text-right font-mono">{fmtNum(lastDay[`papers_cumulative_${c}`])}</td>
                  <td className="py-1.5 pr-4 text-right font-mono">{fmtNum(lastDay[`matches_cumulative_${c}`])}</td>
                  <td className="py-1.5 pr-4 text-right font-mono">{fmtTokens(lastDay[`tokens_cumulative_${c}`])}</td>
                  <td className="py-1.5 text-right font-mono">{fmtCost(lastDay[`cost_cumulative_${c}`])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Memory + User registrations */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard
          title="Memory Usage (RSS)"
          icon={MemoryStick}
          testid="admin2-chart-memory"
          right={
            <Toggle
              testidPrefix="admin2-mem"
              options={[{ label: "6h", value: 6 }, { label: "12h", value: 12 }, { label: "24h", value: 24 }, { label: "3d", value: 72 }, { label: "7d", value: 168 }]}
              value={memHours}
              onChange={setMemHours}
            />
          }
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={memory?.points || []} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
              <XAxis dataKey="epoch" type="number" domain={["dataMin", "dataMax"]} scale="time" tickFormatter={(t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis tickFormatter={(v) => `${v}MB`} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={55} />
              <RTooltip formatter={(v) => `${v} MB`} labelFormatter={(t) => new Date(t).toLocaleString()} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {(memory?.roles || []).map((r, i) => (
                <Line key={r} type="monotone" dataKey={`rss_${r}`} name={r} stroke={MODEL_COLORS[i % MODEL_COLORS.length]} strokeWidth={1.5} dot={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="User Registrations" icon={Users} testid="admin2-chart-registrations">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data?.user_registrations || []} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
              <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={45} allowDecimals={false} />
              <RTooltip formatter={(v) => fmtNum(v)} labelFormatter={fmtDate} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Area type="monotone" dataKey="cumulative" name="Users" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.15} strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}
