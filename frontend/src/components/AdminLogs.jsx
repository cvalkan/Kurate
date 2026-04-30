import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { RefreshCw, Search, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

const CONTEXTS = ["all", "match", "summary", "email_extract"];
const STATUSES = ["all", "success", "failed"];

export function AdminLogs() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [context, setContext] = useState("all");
  const [status, setStatus] = useState("all");
  const [days, setDays] = useState(3);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/admin/db/llm_usage`, {
        headers: getAdminHeaders(),
        params: {
          sort: JSON.stringify({ ts: -1 }),
          limit: 500,
          filter: JSON.stringify({
            ...(context !== "all" ? { context } : {}),
            ...(status === "success" ? { success: true } : status === "failed" ? { success: false } : {}),
          }),
        },
      });
      setLogs(res.data.docs || []);
    } catch { }
    finally { setLoading(false); }
  }, [context, status]);

  useEffect(() => { load(); }, [load]);

  // Aggregate stats for the header
  const stats = useMemo(() => {
    const byContext = {};
    const byModel = {};
    let totalCalls = 0, totalFailed = 0;
    for (const log of logs) {
      totalCalls++;
      if (!log.success) totalFailed++;
      byContext[log.context] = (byContext[log.context] || 0) + 1;
      byModel[log.model] = (byModel[log.model] || 0) + 1;
    }
    return { totalCalls, totalFailed, byContext, byModel };
  }, [logs]);

  const filtered = useMemo(() => {
    if (!search.trim()) return logs;
    const q = search.toLowerCase();
    return logs.filter(l =>
      (l.context || "").toLowerCase().includes(q) ||
      (l.model || "").toLowerCase().includes(q) ||
      (l.provider || "").toLowerCase().includes(q)
    );
  }, [logs, search]);

  return (
    <div className="space-y-4" data-testid="admin-logs">
      {/* Stats row */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>{stats.totalCalls} calls loaded</span>
        <span className="text-red-500">{stats.totalFailed} failed</span>
        {Object.entries(stats.byContext).map(([k, v]) => (
          <span key={k}>{k}: {v}</span>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5">
          <Filter className="h-3.5 w-3.5 text-muted-foreground" />
          <select value={context} onChange={e => setContext(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-context-filter">
            {CONTEXTS.map(c => <option key={c} value={c}>{c === "all" ? "All contexts" : c}</option>)}
          </select>
          <select value={status} onChange={e => setStatus(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-status-filter">
            {STATUSES.map(s => <option key={s} value={s}>{s === "all" ? "All status" : s}</option>)}
          </select>
        </div>
        <div className="relative ml-auto w-48">
          <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter by model..."
            className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background" data-testid="logs-search" />
        </div>
        <Button size="sm" variant="outline" onClick={load} disabled={loading} className="h-8 text-xs gap-1"
          data-testid="logs-refresh">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {/* Table */}
      <div className="border rounded-lg overflow-x-auto" data-testid="logs-table">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-secondary/50 text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Time</th>
              <th className="px-3 py-2 text-left font-medium">Context</th>
              <th className="px-3 py-2 text-left font-medium">Model</th>
              <th className="px-3 py-2 text-center font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Input</th>
              <th className="px-3 py-2 text-right font-medium">Output</th>
              <th className="px-3 py-2 text-right font-medium">Thinking</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((log, i) => (
              <tr key={i} className={`border-t border-border/50 ${!log.success ? "bg-red-50/30" : ""} hover:bg-secondary/20`}>
                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{(log.ts || "").replace("T", " ").slice(0, 19)}</td>
                <td className="px-3 py-1.5">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    log.context === "match" ? "bg-blue-50 text-blue-700" :
                    log.context === "summary" ? "bg-purple-50 text-purple-700" :
                    log.context === "email_extract" ? "bg-amber-50 text-amber-700" :
                    "bg-secondary text-muted-foreground"
                  }`}>{log.context}</span>
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{log.model || log.provider}</td>
                <td className="px-3 py-1.5 text-center">
                  {log.success
                    ? <span className="text-green-600 text-[10px]">OK</span>
                    : <span className="text-red-600 text-[10px] font-medium">FAIL</span>
                  }
                </td>
                <td className="px-3 py-1.5 text-right text-muted-foreground">{log.input_tokens?.toLocaleString() || "—"}</td>
                <td className="px-3 py-1.5 text-right text-muted-foreground">{log.output_tokens?.toLocaleString() || "—"}</td>
                <td className="px-3 py-1.5 text-right text-muted-foreground">{log.thinking_tokens ? log.thinking_tokens.toLocaleString() : "—"}</td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">No logs found</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {loading && <div className="text-center text-xs text-muted-foreground py-4">Loading...</div>}
    </div>
  );
}
