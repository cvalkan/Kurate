import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, Legend,
} from "recharts";
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
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState("cumulative"); // "daily" | "cumulative"
  const [scopeMode, setScopeMode] = useState("system"); // "system" | "category"

  const fetchTimeseries = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/admin/timeseries`, { headers: getAdminHeaders() });
      setTimeseries(res.data);
    } catch (err) {
      console.error("Failed to load timeseries:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTimeseries(); }, [fetchTimeseries]);

  if (loading || !timeseries) {
    return (
      <div className="space-y-4" data-testid="admin-statistics-loading">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-32 bg-secondary/30 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  const { series, totals, models: modelStats } = timeseries;
  const allCats = timeseries.categories || [];
  const suffix = viewMode === "cumulative" ? "cumulative" : "daily";
  const modelCount = modelStats ? Object.keys(modelStats).length : 0;

  // Build stable color map for categories
  const catColorMap = {};
  allCats.forEach((cat, i) => { catColorMap[cat] = getColor(cat, i); });

  // Filter out empty categories (0 papers AND 0 matches in the dataset)
  const lastDay = series.length > 0 ? series[series.length - 1] : {};
  const nonEmptyCats = allCats.filter(cat => {
    const papers = lastDay[`papers_cumulative_${cat}`] || 0;
    const matches = lastDay[`matches_cumulative_${cat}`] || 0;
    return papers > 0 || matches > 0;
  });

  // Build chart data based on scope
  const chartData = series.map(entry => {
    const d = { date: entry.date };
    if (scopeMode === "system") {
      d.papers = entry[`papers_${suffix}`] || 0;
      d.matches = entry[`matches_${suffix}`] || 0;
      d.tokens = entry[`tokens_${suffix}`] || 0;
      d.cost = entry[`cost_${suffix}`] || 0;
      d.input_tokens = entry[`input_tokens_daily`] || 0;
      d.output_tokens = entry[`output_tokens_daily`] || 0;
    } else {
      // Per-category breakdown
      for (const cat of allCats) {
        d[`papers_${cat}`] = entry[`papers_${suffix}_${cat}`] || 0;
        d[`matches_${cat}`] = entry[`matches_${suffix}_${cat}`] || 0;
        d[`tokens_${cat}`] = entry[`tokens_${suffix}_${cat}`] || 0;
        d[`cost_${cat}`] = entry[`cost_${suffix}_${cat}`] || 0;
      }
    }
    return d;
  });

  const ChartType = viewMode === "daily" ? BarChart : AreaChart;
  const DataElement = viewMode === "daily" ? Bar : Area;

  const renderChart = (metric, formatter) => {
    if (scopeMode === "system") {
      return (
        <ResponsiveContainer width="100%" height="100%">
          <ChartType data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
            <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
            <YAxis tickFormatter={metric === "cost" ? formatCost : (metric === "tokens" ? formatTokens : undefined)} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={55} />
            <RechartsTooltip content={<CustomTooltip formatter={formatter} />} />
            {viewMode === "daily" ? (
              <Bar dataKey={metric} fill="#3b82f6" radius={[3, 3, 0, 0]} name={metric.charAt(0).toUpperCase() + metric.slice(1)} />
            ) : (
              <Area type="monotone" dataKey={metric} stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} strokeWidth={2} name={metric.charAt(0).toUpperCase() + metric.slice(1)} />
            )}
          </ChartType>
        </ResponsiveContainer>
      );
    }

    // Per-category stacked
    return (
      <ResponsiveContainer width="100%" height="100%">
        <ChartType data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
          <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
          <YAxis tickFormatter={metric === "cost" ? formatCost : (metric === "tokens" ? formatTokens : undefined)} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" width={55} />
          <RechartsTooltip content={<CustomTooltip formatter={formatter} />} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {allCats.map((cat) =>
            viewMode === "daily" ? (
              <Bar key={cat} dataKey={`${metric}_${cat}`} stackId="a" fill={getColor(cat)} name={cat} />
            ) : (
              <Area key={cat} type="monotone" dataKey={`${metric}_${cat}`} stackId="a" stroke={getColor(cat)} fill={getColor(cat)} fillOpacity={0.2} strokeWidth={1.5} name={cat} />
            )
          )}
        </ChartType>
      </ResponsiveContainer>
    );
  };

  return (
    <div className="space-y-6" data-testid="admin-statistics">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatSummaryCard label="Total Papers" value={totals.papers.toLocaleString()} icon={FileText} color="#3b82f6" />
        <StatSummaryCard label="Total Matches" value={totals.matches.toLocaleString()} icon={Swords} color="#8b5cf6" />
        <StatSummaryCard
          label="Total Tokens"
          value={formatTokens(totals.tokens)}
          sub={`${formatTokens(totals.input_tokens || 0)} in / ${formatTokens(totals.output_tokens || 0)} out`}
          icon={Cpu} color="#10b981"
        />
        <StatSummaryCard
          label="Total Cost"
          value={`$${totals.cost.toFixed(2)}`}
          sub={modelCount > 0 ? `${modelCount} models` : null}
          icon={Coins} color="#f59e0b"
        />
      </div>

      {/* Model breakdown */}
      {modelStats && modelCount > 0 && (
        <div className="rounded-lg border border-border bg-card p-4" data-testid="model-breakdown">
          <h3 className="text-sm font-medium mb-3">Cost by Model</h3>
          <div className="space-y-2">
            {Object.entries(modelStats)
              .sort((a, b) => (b[1].cost_total || 0) - (a[1].cost_total || 0))
              .map(([model, stats]) => {
                const pct = totals.cost > 0 ? ((stats.cost_total || 0) / totals.cost) * 100 : 0;
                return (
                  <div key={model} className="flex items-center gap-3">
                    <span className="text-xs font-mono w-36 shrink-0 truncate">{model.split("/").pop()}</span>
                    <div className="flex-1 h-5 bg-secondary/50 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: getColor(model) || "#3b82f6" }}
                      />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                      <span className="font-mono">{stats.matches} calls</span>
                      <span className="font-mono font-medium text-foreground">${(stats.cost_total || 0).toFixed(2)}</span>
                      <span className="w-10 text-right">{pct.toFixed(0)}%</span>
                    </div>
                  </div>
                );
              })}
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
        <Button variant="ghost" size="sm" className="h-7 text-xs gap-1 ml-auto"
          onClick={() => { setLoading(true); fetchTimeseries(); }} data-testid="refresh-charts"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </Button>
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
              {allCats.map(cat => {
                const lastDay = series[series.length - 1] || {};
                return (
                  <tr key={cat} className="border-b border-border/50">
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: getColor(cat) }} />
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
    </div>
  );
}
