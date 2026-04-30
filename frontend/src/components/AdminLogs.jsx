import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { RefreshCw, Search, Filter, Cpu, Globe, Archive, CheckCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

const LLM_CONTEXTS = ["all", "match", "summary", "email_extract"];
const EVENT_TYPES = ["all", "fetch_cycle", "archive_created", "convergence"];
const STATUSES = ["all", "success", "failed"];

function LlmLogsTable({ logs }) {
  if (!logs.length) return <p className="text-center text-xs text-muted-foreground py-8">No LLM logs found</p>;
  return (
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
        {logs.map((log, i) => (
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
              {log.success ? <span className="text-green-600 text-[10px]">OK</span> : <span className="text-red-600 text-[10px] font-medium">FAIL</span>}
            </td>
            <td className="px-3 py-1.5 text-right text-muted-foreground">{log.input_tokens?.toLocaleString() || "—"}</td>
            <td className="px-3 py-1.5 text-right text-muted-foreground">{log.output_tokens?.toLocaleString() || "—"}</td>
            <td className="px-3 py-1.5 text-right text-muted-foreground">{log.thinking_tokens ? log.thinking_tokens.toLocaleString() : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EventLogsTable({ logs }) {
  if (!logs.length) return <p className="text-center text-xs text-muted-foreground py-8">No events found</p>;
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="bg-secondary/50 text-muted-foreground">
          <th className="px-3 py-2 text-left font-medium">Time</th>
          <th className="px-3 py-2 text-left font-medium">Event</th>
          <th className="px-3 py-2 text-left font-medium">Category</th>
          <th className="px-3 py-2 text-left font-medium">Detail</th>
          <th className="px-3 py-2 text-right font-medium">Count</th>
        </tr>
      </thead>
      <tbody>
        {logs.map((log, i) => (
          <tr key={i} className="border-t border-border/50 hover:bg-secondary/20">
            <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{(log.ts || "").replace("T", " ").slice(0, 19)}</td>
            <td className="px-3 py-1.5">
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium inline-flex items-center gap-1 ${
                log.event === "fetch_cycle" ? "bg-green-50 text-green-700" :
                log.event === "archive_created" ? "bg-indigo-50 text-indigo-700" :
                log.event === "convergence" ? "bg-emerald-50 text-emerald-700" :
                "bg-secondary text-muted-foreground"
              }`}>
                {log.event === "fetch_cycle" && <Globe className="h-2.5 w-2.5" />}
                {log.event === "archive_created" && <Archive className="h-2.5 w-2.5" />}
                {log.event === "convergence" && <CheckCircle className="h-2.5 w-2.5" />}
                {log.event}
              </span>
            </td>
            <td className="px-3 py-1.5 text-muted-foreground">{log.category || "—"}</td>
            <td className="px-3 py-1.5 text-muted-foreground max-w-[300px] truncate" title={log.detail}>{log.detail || "—"}</td>
            <td className="px-3 py-1.5 text-right text-muted-foreground">{log.count || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AdminLogs() {
  const [tab, setTab] = useState("llm"); // "llm" | "events" | "errors"
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [context, setContext] = useState("all");
  const [eventType, setEventType] = useState("all");
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (tab === "llm") {
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
      } else if (tab === "events") {
        const filter = { level: "event" };
        if (eventType !== "all") filter.event = eventType;
        const res = await axios.get(`${API}/api/admin/db/system_logs`, {
          headers: getAdminHeaders(),
          params: { sort: JSON.stringify({ ts: -1 }), limit: 200, filter: JSON.stringify(filter) },
        });
        setLogs(res.data.docs || []);
      } else if (tab === "errors") {
        const res = await axios.get(`${API}/api/admin/db/llm_error_logs`, {
          headers: getAdminHeaders(),
          params: { sort: JSON.stringify({ ts: -1 }), limit: 200 },
        });
        setLogs(res.data.docs || []);
      }
    } catch { }
    finally { setLoading(false); }
  }, [tab, context, status, eventType]);

  useEffect(() => { load(); }, [load]);

  const stats = useMemo(() => {
    if (tab !== "llm") return null;
    let totalCalls = 0, totalFailed = 0;
    for (const log of logs) { totalCalls++; if (!log.success) totalFailed++; }
    return { totalCalls, totalFailed };
  }, [logs, tab]);

  const filtered = useMemo(() => {
    if (!search.trim()) return logs;
    const q = search.toLowerCase();
    return logs.filter(l =>
      Object.values(l).some(v => typeof v === "string" && v.toLowerCase().includes(q))
    );
  }, [logs, search]);

  return (
    <div className="space-y-4" data-testid="admin-logs">
      {/* Tab switcher */}
      <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit">
        {[
          { key: "llm", label: "LLM Calls", icon: Cpu },
          { key: "events", label: "Pipeline Events", icon: Globe },
          { key: "errors", label: "Errors", icon: AlertTriangle },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors inline-flex items-center gap-1.5 ${
              tab === t.key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`} data-testid={`logs-tab-${t.key}`}>
            <t.icon className="h-3.5 w-3.5" />{t.label}
          </button>
        ))}
      </div>

      {/* Stats + filters */}
      <div className="flex flex-wrap items-center gap-2">
        {stats && (
          <div className="flex gap-3 text-xs text-muted-foreground mr-4">
            <span>{stats.totalCalls} calls</span>
            <span className="text-red-500">{stats.totalFailed} failed</span>
          </div>
        )}
        <Filter className="h-3.5 w-3.5 text-muted-foreground" />
        {tab === "llm" && (
          <>
            <select value={context} onChange={e => setContext(e.target.value)}
              className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-context-filter">
              {LLM_CONTEXTS.map(c => <option key={c} value={c}>{c === "all" ? "All contexts" : c}</option>)}
            </select>
            <select value={status} onChange={e => setStatus(e.target.value)}
              className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-status-filter">
              {STATUSES.map(s => <option key={s} value={s}>{s === "all" ? "All status" : s}</option>)}
            </select>
          </>
        )}
        {tab === "events" && (
          <select value={eventType} onChange={e => setEventType(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background" data-testid="logs-event-filter">
            {EVENT_TYPES.map(e => <option key={e} value={e}>{e === "all" ? "All events" : e}</option>)}
          </select>
        )}
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

      {/* Table */}
      <div className="border rounded-lg overflow-x-auto" data-testid="logs-table">
        {tab === "llm" && <LlmLogsTable logs={filtered} />}
        {tab === "events" && <EventLogsTable logs={filtered} />}
        {tab === "errors" && (
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-secondary/50 text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Time</th>
                <th className="px-3 py-2 text-left font-medium">Provider</th>
                <th className="px-3 py-2 text-left font-medium">Model</th>
                <th className="px-3 py-2 text-left font-medium">Context</th>
                <th className="px-3 py-2 text-left font-medium">Type</th>
                <th className="px-3 py-2 text-left font-medium">Error</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log, i) => (
                <tr key={i} className="border-t border-border/50 hover:bg-secondary/20">
                  <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{(log.ts || "").replace("T", " ").slice(0, 19)}</td>
                  <td className="px-3 py-1.5">{log.provider}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{log.model}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{log.context || "—"}</td>
                  <td className="px-3 py-1.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      (log.error_type || "").includes("Budget") || (log.error || "").includes("Budget") ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"
                    }`}>{log.error_type || "Error"}</span>
                  </td>
                  <td className="px-3 py-1.5 text-red-600 max-w-[400px] truncate" title={log.error}>{log.error}</td>
                </tr>
              ))}
              {!filtered.length && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">No errors found</td></tr>}
            </tbody>
          </table>
        )}
      </div>
      {loading && <div className="text-center text-xs text-muted-foreground py-4">Loading...</div>}
    </div>
  );
}
