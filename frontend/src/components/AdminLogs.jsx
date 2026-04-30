import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { RefreshCw, Search, Filter, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

function toCET(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts.includes("Z") ? ts : ts + "Z");
    return d.toLocaleString("sv-SE", { timeZone: "Europe/Berlin" }).replace("T", " ");
  } catch { return ts.slice(0, 19).replace("T", " "); }
}

const SOURCES = [
  { value: "all", label: "All sources" },
  { value: "llm", label: "LLM Calls" },
  { value: "events", label: "Pipeline Events" },
  { value: "errors", label: "Errors" },
];

const STATUSES = [
  { value: "all", label: "All status" },
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
];

const CONTEXTS = [
  { value: "all", label: "All contexts" },
  { value: "match", label: "Match" },
  { value: "summary", label: "Summary" },
  { value: "email_extract", label: "Email extract" },
  { value: "fetch_cycle", label: "Fetch cycle" },
  { value: "archive_created", label: "Archive created" },
  { value: "convergence", label: "Convergence" },
];

function Badge({ children, color = "gray" }) {
  const colors = {
    blue: "bg-blue-50 text-blue-700",
    purple: "bg-purple-50 text-purple-700",
    amber: "bg-amber-50 text-amber-700",
    green: "bg-green-50 text-green-700",
    indigo: "bg-indigo-50 text-indigo-700",
    emerald: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    orange: "bg-orange-50 text-orange-700",
    gray: "bg-secondary text-muted-foreground",
  };
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${colors[color] || colors.gray}`}>{children}</span>;
}

function contextColor(ctx) {
  if (ctx === "match") return "blue";
  if (ctx === "summary" || ctx === "summary_fallback") return "purple";
  if (ctx === "email_extract") return "amber";
  if (ctx === "fetch_cycle") return "green";
  if (ctx === "archive_created") return "indigo";
  if (ctx === "convergence") return "emerald";
  return "gray";
}

function normalizeRow(doc, source) {
  if (source === "llm") {
    return {
      ts: doc.ts,
      source: "llm",
      context: doc.context || "—",
      model: doc.model || doc.provider || "",
      api: null,
      success: doc.success,
      detail: doc.success ? `in=${(doc.input_tokens || 0).toLocaleString()} out=${(doc.output_tokens || 0).toLocaleString()}${doc.thinking_tokens ? ` think=${doc.thinking_tokens.toLocaleString()}` : ""}` : "failed",
      error: null,
    };
  }
  if (source === "events") {
    return {
      ts: doc.ts,
      source: "event",
      context: doc.event || "event",
      model: "",
      api: null,
      success: true,
      detail: `${doc.category ? doc.category + ": " : ""}${doc.detail || ""}${doc.count ? " (" + doc.count + ")" : ""}`,
      error: null,
    };
  }
  if (source === "errors") {
    const isFallback = (doc.context || "").includes("FALLBACK");
    return {
      ts: doc.ts,
      source: "error",
      context: doc.context?.replace("generate_summary", "summary").replace("compare_papers", "match").replace("_FALLBACK", "") || "error",
      model: doc.model || "",
      api: isFallback ? "Anthropic" : "Emergent",
      success: false,
      detail: null,
      error: doc.error || doc.error_type || "Unknown error",
    };
  }
  return { ts: "", source: "?", context: "?", model: "", api: null, success: null, detail: "", error: null };
}

export function AdminLogs() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const [context, setContext] = useState("all");
  const [search, setSearch] = useState("");
  const [expandedRow, setExpandedRow] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getAdminHeaders();
      const fetches = [];

      if (source === "all" || source === "llm") {
        const filter = {};
        if (source === "llm" && status === "success") filter.success = true;
        if (source === "llm" && status === "failed") filter.success = false;
        if (context !== "all" && ["match", "summary", "email_extract"].includes(context)) filter.context = context;
        fetches.push(
          axios.get(`${API}/api/admin/db/llm_usage`, {
            headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 300, filter: JSON.stringify(filter) },
          }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "llm")))
        );
      }

      if (source === "all" || source === "events") {
        const filter = { level: "event" };
        if (context !== "all" && ["fetch_cycle", "archive_created", "convergence"].includes(context)) filter.event = context;
        fetches.push(
          axios.get(`${API}/api/admin/db/system_logs`, {
            headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 100, filter: JSON.stringify(filter) },
          }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "events")))
        );
      }

      if (source === "all" || source === "errors") {
        fetches.push(
          axios.get(`${API}/api/admin/db/llm_error_logs`, {
            headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 200 },
          }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "errors")))
        );
      }

      const results = await Promise.all(fetches);
      const merged = results.flat().sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
      setRows(merged);
    } catch { }
    finally { setLoading(false); }
  }, [source, status, context]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    let result = rows;
    if (status === "success") result = result.filter(r => r.success === true);
    if (status === "failed") result = result.filter(r => r.success === false);
    if (context !== "all") result = result.filter(r => r.context === context || r.context?.startsWith(context));
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(r =>
        (r.context || "").toLowerCase().includes(q) ||
        (r.model || "").toLowerCase().includes(q) ||
        (r.detail || "").toLowerCase().includes(q) ||
        (r.error || "").toLowerCase().includes(q) ||
        (r.api || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [rows, status, context, search]);

  const stats = useMemo(() => {
    let total = filtered.length, success = 0, failed = 0, events = 0, errors = 0;
    for (const r of filtered) {
      if (r.source === "event") events++;
      else if (r.source === "error") errors++;
      else if (r.success) success++;
      else failed++;
    }
    return { total, success, failed, events, errors };
  }, [filtered]);

  return (
    <div className="space-y-4" data-testid="admin-logs">
      {/* Filters row */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="h-3.5 w-3.5 text-muted-foreground" />
        <select value={source} onChange={e => setSource(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-source-filter">
          {SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={context} onChange={e => setContext(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-context-filter">
          {CONTEXTS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-status-filter">
          {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <div className="relative ml-auto w-48">
          <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter..."
            className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background" data-testid="logs-search" />
        </div>
        <Button size="sm" variant="outline" onClick={load} disabled={loading} className="h-8 text-xs gap-1" data-testid="logs-refresh">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>{stats.total} entries</span>
        {stats.success > 0 && <span className="text-green-600">{stats.success} success</span>}
        {stats.failed > 0 && <span className="text-red-500">{stats.failed} failed</span>}
        {stats.events > 0 && <span className="text-indigo-600">{stats.events} events</span>}
        {stats.errors > 0 && <span className="text-red-500">{stats.errors} errors</span>}
      </div>

      {/* Table */}
      <div className="border rounded-lg overflow-x-auto" data-testid="logs-table">
        <table className="w-full text-xs" style={{ minWidth: "700px" }}>
          <thead>
            <tr className="bg-secondary/50 text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium w-[145px]">Time (CET)</th>
              <th className="px-3 py-2 text-left font-medium w-[90px]">Context</th>
              <th className="px-3 py-2 text-left font-medium w-[120px]">Model</th>
              <th className="px-3 py-2 text-center font-medium w-[50px]">Status</th>
              <th className="px-3 py-2 text-left font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 500).map((r, i) => (
              <tr key={i}
                className={`border-t border-border/50 hover:bg-secondary/20 cursor-pointer ${
                  r.source === "error" ? "bg-red-50/20" :
                  r.source === "event" ? "bg-indigo-50/20" :
                  r.success === false ? "bg-amber-50/20" : ""
                }`}
                onClick={() => setExpandedRow(expandedRow === i ? null : i)}
              >
                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{toCET(r.ts)}</td>
                <td className="px-3 py-1.5"><Badge color={contextColor(r.context)}>{r.context}</Badge></td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {r.model && <span className="text-muted-foreground">{r.model}</span>}
                  {r.api && <span className="ml-1"><Badge color={r.api === "Anthropic" ? "orange" : "blue"}>{r.api}</Badge></span>}
                </td>
                <td className="px-3 py-1.5 text-center">
                  {r.source === "event" ? <Badge color="indigo">event</Badge> :
                   r.success ? <span className="text-green-600 text-[10px]">OK</span> :
                   <span className="text-red-600 text-[10px] font-medium">FAIL</span>}
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {r.error ? (
                    <span className="text-red-600 truncate block max-w-[400px]" title={r.error}>
                      {expandedRow === i ? r.error : r.error.slice(0, 80) + (r.error.length > 80 ? "..." : "")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">{r.detail || "—"}</span>
                  )}
                  {expandedRow === i && r.error && r.error.length > 80 && (
                    <ChevronDown className="h-3 w-3 inline ml-1 text-muted-foreground rotate-180" />
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">No logs found</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {filtered.length > 500 && (
        <p className="text-[10px] text-muted-foreground text-center">Showing 500 of {filtered.length} entries</p>
      )}
      {loading && <div className="text-center text-xs text-muted-foreground py-4">Loading...</div>}
    </div>
  );
}
