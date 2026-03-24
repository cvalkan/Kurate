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
  const [summaryStats, setSummaryStats] = useState(null);
  const [memoryData, setMemoryData] = useState(null);
  const [memHours, setMemHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState("cumulative"); // "daily" | "cumulative"
  const [scopeMode, setScopeMode] = useState("system"); // "system" | "category"

  const fetchData = useCallback(async () => {
    try {
      const [tsRes, statsRes, memRes] = await Promise.all([
        axios.get(`${API}/api/admin/timeseries`, { headers: getAdminHeaders() }),
        axios.get(`${API}/api/admin/stats`, { headers: getAdminHeaders() }),
        axios.get(`${API}/api/admin/system-logs?hours=${memHours}`, { headers: getAdminHeaders() }),
      ]);
      setTimeseries(tsRes.data);
      setSummaryStats(statsRes.data.summaries || null);
      // Process memory logs into chart data
      const logs = (memRes.data?.logs || []).filter(l => l.level === "mem" && l.rss_mb);
      const chartData = logs.sort((a, b) => a.ts.localeCompare(b.ts)).map(l => ({
        ts: l.ts,
        epoch: new Date(l.ts.endsWith("Z") ? l.ts : l.ts + "Z").getTime(),
        rss: l.rss_mb,
        label: l.label,
      }));
      setMemoryData(chartData);
    } catch (err) {
      console.error("Failed to load stats:", err);
    } finally {
      setLoading(false);
    }
  }, [memHours]);

  useEffect(() => { fetchData(); }, [fetchData]);

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
          {nonEmptyCats.map((cat) =>
            viewMode === "daily" ? (
              <Bar key={cat} dataKey={`${metric}_${cat}`} stackId="a" fill={catColorMap[cat]} name={cat} />
            ) : (
              <Area key={cat} type="monotone" dataKey={`${metric}_${cat}`} stackId="a" stroke={catColorMap[cat]} fill={catColorMap[cat]} fillOpacity={0.2} strokeWidth={1.5} name={cat} />
            )
          )}
        </ChartType>
      </ResponsiveContainer>
    );
  };

  const summaryCost = totals.summary_cost || 0;
  const matchCost = totals.match_cost || totals.cost;
  const combinedCost = totals.cost;  // Already includes summaries from timeseries
  const combinedTokens = totals.tokens;  // Already includes summaries from timeseries

  // Merge match model stats with summary model stats for unified view
  const mergedModelStats = { ...modelStats };
  if (summaryStats?.models) {
    for (const [mk, ss] of Object.entries(summaryStats.models)) {
      // Map summary model key (e.g. "anthropic:claude-opus-4-6") to match model key (e.g. "anthropic/claude-opus-4-6")
      const provider = mk.split(":")[0];
      const model = mk.split(":").slice(1).join(":").replace(/_/g, ".");
      const matchKey = `${provider}/${model}`;
      // Find by exact model name first, then by matchKey
      const existingKey = Object.keys(mergedModelStats).find(k => k === matchKey)
        || Object.keys(mergedModelStats).find(k => k.includes(model));
      if (existingKey) {
        mergedModelStats[existingKey] = {
          ...mergedModelStats[existingKey],
          summary_cost: (mergedModelStats[existingKey].summary_cost || 0) + (ss.cost_total || 0),
          summary_count: (mergedModelStats[existingKey].summary_count || 0) + (ss.summaries || 0),
          summary_tokens: (mergedModelStats[existingKey].summary_tokens || 0) + (ss.input_tokens || 0) + (ss.output_tokens || 0),
        };
      } else {
        // New model with summaries but no match history yet — create entry
        mergedModelStats[matchKey] = {
          matches: 0, input_tokens: 0, output_tokens: 0, cost_total: 0,
          summary_cost: ss.cost_total || 0,
          summary_count: ss.summaries || 0,
          summary_tokens: (ss.input_tokens || 0) + (ss.output_tokens || 0),
        };
      }
    }
  }

  return (
    <div className="space-y-6" data-testid="admin-statistics">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatSummaryCard label="Total Papers" value={totals.papers.toLocaleString()} icon={FileText} color="#3b82f6" />
        <StatSummaryCard label="Total Matches" value={totals.matches.toLocaleString()} icon={Swords} color="#8b5cf6" />
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
      </div>

      {/* Model breakdown — combined match + summary costs */}
      {mergedModelStats && Object.keys(mergedModelStats).length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4" data-testid="model-breakdown">
          <h3 className="text-sm font-medium mb-3">Cost by Model</h3>
          <div className="space-y-2">
            {Object.entries(mergedModelStats)
              .sort((a, b) => ((b[1].cost_total || 0) + (b[1].summary_cost || 0)) - ((a[1].cost_total || 0) + (a[1].summary_cost || 0)))
              .map(([model, stats], idx) => {
                const matchCost = stats.cost_total || 0;
                const sumCost = stats.summary_cost || 0;
                const totalModelCost = matchCost + sumCost;
                const pct = combinedCost > 0 ? (totalModelCost / combinedCost) * 100 : 0;
                return (
                  <div key={model} className="flex items-center gap-3">
                    <span className="text-xs font-mono w-36 shrink-0 truncate">{model.split("/").pop()}</span>
                    <div className="flex-1 h-5 bg-secondary/50 rounded-full overflow-hidden flex">
                      <div
                        className="h-full transition-all"
                        style={{ width: `${combinedCost > 0 ? (matchCost / combinedCost) * 100 : 0}%`, backgroundColor: getColor(model, idx) }}
                      />
                      {sumCost > 0 && (
                        <div
                          className="h-full transition-all opacity-50"
                          style={{ width: `${combinedCost > 0 ? (sumCost / combinedCost) * 100 : 0}%`, backgroundColor: getColor(model, idx) }}
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                      <span className="font-mono">{stats.matches} calls{stats.summary_count ? ` + ${stats.summary_count} sums` : ""}</span>
                      <span className="font-mono font-medium text-foreground">${totalModelCost.toFixed(2)}</span>
                      <span className="w-10 text-right">{pct.toFixed(0)}%</span>
                    </div>
                  </div>
                );
              })}
          </div>
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
                Current: {memoryData[memoryData.length - 1]?.rss}MB / 2048MB
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
                  domain={["dataMin", "dataMax"]}
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
                  tickCount={memHours <= 12 ? 8 : memHours <= 24 ? 10 : 8}
                />
                <YAxis domain={[0, 2048]} ticks={[0, 512, 1024, 1536, 2048]} tickFormatter={v => `${v}MB`} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={55} />
                <RechartsTooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0]?.payload;
                    return (
                      <div className="rounded-lg border border-border bg-popover p-2 shadow-lg text-xs">
                        <div className="font-medium">{d?.ts ? new Date(d.ts.endsWith("Z") ? d.ts : d.ts + "Z").toLocaleString("en-US", { timeZone: "Europe/Berlin", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " CET" : ""}</div>
                        <div className="text-muted-foreground mt-0.5">{d?.label}</div>
                        <div className="font-mono mt-1" style={{ color: d?.rss > 1536 ? "#ef4444" : d?.rss > 1024 ? "#f59e0b" : "#10b981" }}>
                          {d?.rss}MB
                        </div>
                      </div>
                    );
                  }}
                />
                {/* Danger zone */}
                <Area type="monotone" dataKey={() => 2048} stroke="none" fill="#ef4444" fillOpacity={0.05} />
                <Area type="stepAfter" dataKey="rss" stroke="#ef4444" fill="url(#memGrad)" strokeWidth={1.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" /> &lt;1GB Safe</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500" /> 1-1.5GB Warning</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" /> &gt;1.5GB Danger (2GB limit)</span>
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
          onClick={() => { setLoading(true); fetchData(); }} data-testid="refresh-charts"
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
    </div>
  );
}
