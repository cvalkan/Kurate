import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { RefreshCw, Search, Filter } from "lucide-react";
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

const TYPES = [
  { value: "all", label: "All types" },
  { value: "match", label: "Match" },
  { value: "summary", label: "Summary" },
  { value: "email_extract", label: "Email extract" },
  { value: "fetch_cycle", label: "Fetch cycle" },
  { value: "archive_created", label: "Archive" },
  { value: "convergence", label: "Convergence" },
  { value: "error", label: "Errors only" },
];

const STATUSES = [
  { value: "all", label: "All status" },
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
];

const APIS = [
  { value: "all", label: "All APIs" },
  { value: "emergent", label: "Emergent" },
  { value: "anthropic", label: "Anthropic" },
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

function typeColor(ctx) {
  if (ctx === "match") return "blue";
  if (ctx === "summary") return "purple";
  if (ctx === "email_extract") return "amber";
  if (ctx === "fetch_cycle") return "green";
  if (ctx === "archive_created") return "indigo";
  if (ctx === "convergence") return "emerald";
  return "gray";
}

function normalizeRow(doc, source) {
  if (source === "llm") {
    const isFallback = (doc.context || "").includes("fallback");
    return {
      ts: doc.ts,
      type: doc.context || "llm",
      model: doc.model || doc.provider || "",
      api: isFallback ? "Anthropic" : "Emergent",
      success: doc.success,
      detail: doc.success
        ? `in=${(doc.input_tokens || 0).toLocaleString()} out=${(doc.output_tokens || 0).toLocaleString()}${doc.thinking_tokens ? ` think=${doc.thinking_tokens.toLocaleString()}` : ""}`
        : "failed",
      isError: false,
    };
  }
  if (source === "events") {
    return {
      ts: doc.ts,
      type: doc.event || "event",
      model: "",
      api: "",
      success: true,
      detail: `${doc.category ? doc.category + ": " : ""}${doc.detail || ""}${doc.count ? " (" + doc.count + ")" : ""}`,
      isError: false,
    };
  }
  if (source === "errors") {
    const isFallback = (doc.context || "").includes("FALLBACK");
    const type = doc.context?.replace("generate_summary_FALLBACK", "summary").replace("generate_summary", "summary").replace("compare_papers_FALLBACK", "match").replace("compare_papers", "match") || "error";
    return {
      ts: doc.ts,
      type,
      model: doc.model || "",
      api: isFallback ? "Anthropic" : "Emergent",
      success: false,
      detail: doc.error || doc.error_type || "Unknown error",
      isError: true,
    };
  }
  return { ts: "", type: "?", model: "", api: "", success: null, detail: "", isError: false };
}

export function AdminLogs() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const [api, setApi] = useState("all");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getAdminHeaders();
      const fetches = [];

      // Always fetch all sources, filter client-side for simplicity
      fetches.push(
        axios.get(`${API}/api/admin/db/llm_usage`, {
          headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 300 },
        }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "llm"))).catch(() => [])
      );
      fetches.push(
        axios.get(`${API}/api/admin/db/system_logs`, {
          headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 100, filter: JSON.stringify({ level: "event" }) },
        }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "events"))).catch(() => [])
      );
      fetches.push(
        axios.get(`${API}/api/admin/db/llm_error_logs`, {
          headers, params: { sort: JSON.stringify({ ts: -1 }), limit: 200 },
        }).then(r => (r.data.docs || []).map(d => normalizeRow(d, "errors"))).catch(() => [])
      );

      const results = await Promise.all(fetches);
      setRows(results.flat().sort((a, b) => (b.ts || "").localeCompare(a.ts || "")));
    } catch { }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    let result = rows;
    if (type === "error") result = result.filter(r => r.isError || r.success === false);
    else if (type !== "all") result = result.filter(r => r.type === type);
    if (status === "success") result = result.filter(r => r.success === true);
    if (status === "failed") result = result.filter(r => r.success === false);
    if (api === "emergent") result = result.filter(r => r.api === "Emergent");
    if (api === "anthropic") result = result.filter(r => r.api === "Anthropic");
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(r =>
        (r.type || "").toLowerCase().includes(q) ||
        (r.model || "").toLowerCase().includes(q) ||
        (r.detail || "").toLowerCase().includes(q) ||
        (r.api || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [rows, type, status, api, search]);

  const stats = useMemo(() => {
    let total = filtered.length, success = 0, failed = 0, events = 0;
    for (const r of filtered) {
      if (r.success === true && !r.isError) {
        if (["fetch_cycle", "archive_created", "convergence"].includes(r.type)) events++;
        else success++;
      } else failed++;
    }
    return { total, success, failed, events };
  }, [filtered]);

  return (
    <div className="space-y-4" data-testid="admin-logs">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="h-3.5 w-3.5 text-muted-foreground" />
        <select value={type} onChange={e => setType(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-type-filter">
          {TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-status-filter">
          {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={api} onChange={e => setApi(e.target.value)}
          className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-api-filter">
          {APIS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
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
      </div>

      {/* Table */}
      <div className="border rounded-lg overflow-x-auto" data-testid="logs-table">
        <table className="w-full text-xs" style={{ minWidth: "750px" }}>
          <thead>
            <tr className="bg-secondary/50 text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium" style={{ width: "140px" }}>Time (CET)</th>
              <th className="px-3 py-2 text-left font-medium" style={{ width: "80px" }}>Type</th>
              <th className="px-3 py-2 text-left font-medium" style={{ width: "170px" }}>Model / API</th>
              <th className="px-3 py-2 text-center font-medium" style={{ width: "45px" }}>Status</th>
              <th className="px-3 py-2 text-left font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 500).map((r, i) => (
              <tr key={i} className={`border-t border-border/50 hover:bg-secondary/20 ${
                r.isError ? "bg-red-50/20" :
                ["fetch_cycle", "archive_created", "convergence"].includes(r.type) ? "bg-indigo-50/20" :
                r.success === false ? "bg-amber-50/20" : ""
              }`}>
                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{toCET(r.ts)}</td>
                <td className="px-3 py-1.5"><Badge color={typeColor(r.type)}>{r.type}</Badge></td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {r.model && <span className="text-muted-foreground">{r.model}</span>}
                  {r.api && <span className="ml-1"><Badge color={r.api === "Anthropic" ? "orange" : "blue"}>{r.api}</Badge></span>}
                </td>
                <td className="px-3 py-1.5 text-center">
                  {["fetch_cycle", "archive_created", "convergence"].includes(r.type) && r.success
                    ? <Badge color="indigo">event</Badge>
                    : r.success
                    ? <span className="text-green-600 text-[10px]">OK</span>
                    : <span className="text-red-600 text-[10px] font-medium">FAIL</span>}
                </td>
                <td className="px-3 py-1.5">
                  <div className="overflow-x-auto max-w-[500px] scrollbar-none" style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}>
                    <span className={`whitespace-nowrap ${r.isError ? "text-red-600" : "text-muted-foreground"}`}>
                      {r.detail || "—"}
                    </span>
                  </div>
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
