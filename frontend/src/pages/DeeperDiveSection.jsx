import { useState, useEffect } from "react";
import axios from "axios";
import { FlaskConical, Search, ArrowUpDown, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DeeperDiveSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState(null);
  const [filter, setFilter] = useState("all"); // all | recommended | not
  const [catFilter, setCatFilter] = useState("all");
  const [sortBy, setSortBy] = useState("category");

  useEffect(() => {
    axios.get(`${API}/api/validation/deeper-dive/results`).then(r => {
      setData(r.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  // Poll progress if experiment is running
  useEffect(() => {
    if (data?.status === "no_data" || !data) {
      const iv = setInterval(() => {
        axios.get(`${API}/api/validation/deeper-dive/status`).then(r => {
          setProgress(r.data);
          if (!r.data.running && r.data.done > 0) {
            // Experiment finished — reload results
            axios.get(`${API}/api/validation/deeper-dive/results`).then(r2 => {
              setData(r2.data);
              setProgress(null);
            });
          }
        });
      }, 5000);
      return () => clearInterval(iv);
    }
  }, [data]);

  if (loading) {
    return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  }

  // Show progress if running
  if (data?.status === "no_data" && progress?.running) {
    return (
      <div className="text-center py-12">
        <RefreshCw className="h-8 w-8 mx-auto mb-3 animate-spin text-muted-foreground" />
        <p className="text-sm font-medium">Experiment running...</p>
        <p className="text-xs text-muted-foreground mt-1">{progress.done}/{progress.total} papers processed ({progress.errors} errors)</p>
      </div>
    );
  }

  if (data?.status === "no_data") {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FlaskConical className="h-8 w-8 mx-auto mb-3 opacity-30" />
        <p className="text-sm">No experiment data yet. Run the experiment from the admin panel.</p>
      </div>
    );
  }

  const { summary, results } = data;
  const categories = [...new Set(results.map(r => r.category))].sort();

  // Filter results
  let filtered = results.filter(r => r.parse_ok !== false);
  if (filter === "recommended") filtered = filtered.filter(r => r.deeper_dive_recommended);
  if (filter === "not") filtered = filtered.filter(r => !r.deeper_dive_recommended);
  if (catFilter !== "all") filtered = filtered.filter(r => r.category === catFilter);

  // Sort
  if (sortBy === "category") filtered.sort((a, b) => a.category.localeCompare(b.category) || a.title.localeCompare(b.title));
  if (sortBy === "confidence") filtered.sort((a, b) => (a.confidence || "").localeCompare(b.confidence || ""));
  if (sortBy === "length") filtered.sort((a, b) => b.full_text_len - a.full_text_len);

  const recRate = summary.recommend_rate;
  const confDist = summary.confidence_distribution || {};

  return (
    <div className="space-y-6" data-testid="deeper-dive-experiment">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Papers Analyzed" value={summary.parsed} sub={`${summary.errors} parse failures`} />
        <StatCard label="Deeper Dive Recommended" value={`${summary.recommended}/${summary.parsed}`} sub={`${recRate}% recommend rate`} accent />
        <StatCard label="High Confidence" value={confDist.high || 0} sub="Assessment complete" />
        <StatCard label="Medium Confidence" value={confDist.medium || 0} sub="Gaps identified" />
      </div>

      {/* Confidence × Recommendation matrix */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Confidence vs Recommendation</h3>
          <div className="space-y-2 text-xs">
            {[["Recommended + medium", summary.recommended, "text-amber-600"],
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
                {a.count > 1 && <span className="font-mono font-bold">×{a.count}</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Filters + Table */}
      <div>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="dive-filter">
            {[["all", "All"], ["recommended", "Recommended"], ["not", "Not Recommended"]].map(([val, label]) => (
              <button key={val} onClick={() => setFilter(val)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${filter === val ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
                {label} {val === "recommended" ? `(${summary.recommended})` : val === "not" ? `(${summary.not_recommended})` : ""}
              </button>
            ))}
          </div>
          <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
            className="text-[11px] border border-border rounded-lg px-2 py-1.5 bg-background" data-testid="dive-cat-filter">
            <option value="all">All categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <button onClick={() => setSortBy(s => s === "category" ? "length" : s === "length" ? "confidence" : "category")}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground ml-auto">
            <ArrowUpDown className="h-3 w-3" /> Sort: {sortBy}
          </button>
        </div>

        <div className="space-y-2" data-testid="dive-results-list">
          {filtered.map((r, i) => (
            <div key={i} className={`border rounded-lg p-3 text-xs transition-colors ${r.deeper_dive_recommended ? "border-amber-300 bg-amber-50/50" : "border-border"}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="font-mono text-[10px] text-muted-foreground bg-secondary/50 px-1.5 py-0.5 rounded">{r.category}</span>
                    {r.deeper_dive_recommended && <span className="text-[10px] font-medium text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">DEEPER DIVE</span>}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${r.confidence === "high" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                      {r.confidence} confidence
                    </span>
                  </div>
                  <p className="font-medium text-foreground truncate">{r.title}</p>
                  <span className="text-muted-foreground">{(r.full_text_len / 1000).toFixed(0)}k chars</span>
                </div>
              </div>
              {r.deeper_dive_recommended && r.focus_areas?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.focus_areas.map((a, j) => (
                    <span key={j} className="text-[10px] px-1.5 py-0.5 bg-secondary/50 rounded text-muted-foreground">{a}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        {filtered.length === 0 && <p className="text-center text-xs text-muted-foreground py-6">No results match the current filters.</p>}
      </div>

      <p className="text-[10px] text-muted-foreground">Model: {summary.model} · {summary.total} papers sampled across {Object.keys(summary.by_category || {}).length} categories</p>
    </div>
  );
}

function StatCard({ label, value, sub, accent }) {
  return (
    <div className={`border rounded-lg p-3 ${accent ? "border-amber-300 bg-amber-50/50" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground mb-0.5">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}
