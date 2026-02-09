import { useState, useEffect } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  RefreshCw, Swords, Activity, FileText, CheckCircle2, XCircle,
  ChevronDown, ChevronUp, Pause, Play, Clock, Trophy,
} from "lucide-react";
import { ModelBadge } from "@/components/ModelBadge";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

function StatCard({ label, value, icon: Icon }) {
  return (
    <div className="p-4 bg-secondary/30 rounded-lg border border-border">
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="font-mono text-2xl font-bold">{value}</div>
    </div>
  );
}

export function AdminOverview({
  status, progress, usageStats, categories, adminCat, setAdminCat,
  triggerFetch, triggerCompare, togglePause, loading,
  manualMatches, setManualMatches, onRefresh,
}) {
  const [expandedLogs, setExpandedLogs] = useState(new Set());

  // Smart pause: if tournament is paused but global isn't, toggle the tournament status
  const handlePauseResume = async () => {
    if (progress?.tournament_paused && !progress?.global_paused) {
      // Resume the specific tournament
      const tid = encodeURIComponent(`cat=${adminCat}|mode=standard`);
      try {
        await axios.post(`${API}/api/admin/tournaments/${tid}/status`, { status: "active" }, { headers: getAdminHeaders() });
        toast.success(`Tournament ${adminCat} resumed`);
        if (onRefresh) onRefresh();
      } catch { toast.error("Failed to resume tournament"); }
    } else if (!progress?.paused) {
      // Pause the specific tournament
      const tid = encodeURIComponent(`cat=${adminCat}|mode=standard`);
      try {
        await axios.post(`${API}/api/admin/tournaments/${tid}/status`, { status: "paused" }, { headers: getAdminHeaders() });
        toast.success(`Tournament ${adminCat} paused`);
        if (onRefresh) onRefresh();
      } catch { toast.error("Failed to pause tournament"); }
    } else {
      // Global pause is on — toggle it
      togglePause();
    }
  };

  if (!status) return null;

  return (
    <div className="space-y-6" data-testid="admin-overview">
      {categories.length > 1 && (
        <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg w-fit" data-testid="admin-cat-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={adminCat === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => setAdminCat(c.id)}
              className="text-xs h-8"
              data-testid={`admin-cat-${c.id}`}
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Papers" value={status.total_papers} icon={FileText} />
        <StatCard label="Matches" value={status.total_matches} icon={Swords} />
        <StatCard label="Failed" value={status.failed_matches} icon={XCircle} />
        <StatCard label="Unranked" value={status.unranked_papers} icon={Activity} />
      </div>

      {progress && (
        <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="progress-indicator">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">Ranking Progress</h3>
            <Button
              onClick={handlePauseResume}
              variant={progress.paused ? "default" : "outline"}
              size="sm"
              className="gap-1.5 h-8"
              data-testid="pause-resume-button"
            >
              {progress.paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
              {progress.paused ? "Resume" : "Pause"}
            </Button>
          </div>

          {progress.goals_met ? (
            <div className="flex items-center gap-2 text-sm text-green-600 mb-2">
              <CheckCircle2 className="h-4 w-4" />
              Both goals met — system idle
            </div>
          ) : (
            <div className="space-y-2 mb-2">
              <div className="flex items-center gap-1.5 text-xs">
                {progress.goal1?.met
                  ? <><CheckCircle2 className="h-3 w-3 text-green-600" /><span className="text-green-600">{progress.goal1?.label}</span></>
                  : <><Clock className="h-3 w-3 text-amber-500" /><span className="text-muted-foreground">{progress.goal1?.label}</span></>
                }
              </div>
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5">
                  {progress.goal2?.met
                    ? <><CheckCircle2 className="h-3 w-3 text-green-600" /><span className="text-green-600">{progress.goal2?.label}</span></>
                    : <><Clock className="h-3 w-3 text-amber-500" /><span className="text-muted-foreground">{progress.goal2?.label}</span></>
                  }
                </div>
                {!progress.goal2?.met && (
                  <span className="font-mono text-muted-foreground">{progress.goal2?.done}/{progress.goal2?.total}</span>
                )}
              </div>
            </div>
          )}

          {!progress.goals_met && progress.estimated_matches_remaining > 0 && (
            <div className="text-xs text-muted-foreground border-t border-border/50 pt-2 mt-2">
              Est. <span className="font-mono text-foreground font-medium">~{progress.estimated_matches_remaining}</span> matches remaining
              {progress.estimated_minutes > 0 && (
                <span> &middot; ~<span className="font-mono text-foreground font-medium">{progress.estimated_minutes} min</span></span>
              )}
              {progress.paused && (
                <span className="ml-2 text-amber-600 font-medium">
                  {progress.tournament_paused && !progress.global_paused ? "TOURNAMENT PAUSED" : "PAUSED"}
                </span>
              )}
              {!progress.paused && <span className="ml-2 text-accent">Running</span>}
            </div>
          )}

          <div className="text-[10px] text-muted-foreground mt-1.5">
            {progress.total_matches} matches &middot; {progress.papers_with_pdf}/{progress.total_papers} PDFs
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={triggerFetch} disabled={loading.fetch} className="gap-2" data-testid="trigger-fetch">
          <RefreshCw className={`h-4 w-4 ${loading.fetch ? "animate-spin" : ""}`} />
          {loading.fetch ? "Fetching..." : "Fetch Papers"}
        </Button>
        <div className="flex items-center gap-1.5">
          <Input
            type="number" min="1" max="500"
            value={manualMatches}
            onChange={(e) => setManualMatches(Math.min(500, Math.max(1, Number(e.target.value) || 50)))}
            className="w-20 h-10 text-center font-mono text-sm"
            data-testid="manual-matches-input"
          />
          <Button onClick={triggerCompare} disabled={loading.compare} variant="outline" className="gap-2" data-testid="trigger-compare">
            <Swords className={`h-4 w-4 ${loading.compare ? "animate-spin" : ""}`} />
            {loading.compare ? "Starting..." : "Run Matches"}
          </Button>
        </div>
      </div>

      {status.scheduler && (
        <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="scheduler-status">
          <h3 className="text-sm font-medium mb-2">Scheduler Status</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-muted-foreground">
            <div>Activity: <span className="font-mono text-foreground">{status.scheduler.current_activity}</span></div>
            {status.scheduler.last_fetch_at && (
              <div>Last Fetch: <span className="font-mono text-foreground">{new Date(status.scheduler.last_fetch_at).toLocaleString()}</span></div>
            )}
            {status.scheduler.next_fetch_at && (
              <div>Next Fetch: <span className="font-mono text-foreground">{new Date(status.scheduler.next_fetch_at).toLocaleString()}</span></div>
            )}
            <div>Processing: <span className="font-mono text-foreground">{status.scheduler.is_processing ? "Yes" : "No"}</span></div>
            <div>Fetching: <span className="font-mono text-foreground">{status.scheduler.is_fetching ? "Yes" : "No"}</span></div>
          </div>
        </div>
      )}

      {usageStats && (
        <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="usage-stats">
          <h3 className="text-sm font-medium mb-3">Usage Statistics</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
            <div className="text-xs text-muted-foreground">
              <span className="block text-foreground font-mono font-medium">{(usageStats.totals?.input_tokens || 0).toLocaleString()}</span>
              input tokens (est.)
            </div>
            <div className="text-xs text-muted-foreground">
              <span className="block text-foreground font-mono font-medium">{(usageStats.totals?.output_tokens || 0).toLocaleString()}</span>
              output tokens (est.)
            </div>
            <div className="text-xs text-muted-foreground">
              <span className="block text-foreground font-mono font-medium">${usageStats.totals?.total_cost?.toFixed(2) || "0.00"}</span>
              estimated cost
            </div>
            <div className="text-xs text-muted-foreground">
              <span className="block text-foreground font-mono font-medium">{usageStats.storage?.size_mb || 0} MB</span>
              PDF text storage
            </div>
            <div className="text-xs text-muted-foreground">
              <span className="block text-foreground font-mono font-medium">{usageStats.totals?.total_matches || 0}</span>
              API calls
            </div>
          </div>
          {usageStats.models && Object.keys(usageStats.models).length > 0 && (
            <div className="border-t border-border/50 pt-2">
              <div className="text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wide">By model</div>
              <div className="space-y-1.5">
                {Object.entries(usageStats.models).sort((a, b) => b[1].matches - a[1].matches).map(([model, stats]) => (
                  <div key={model} className="flex items-center justify-between text-xs gap-2">
                    <span className="font-mono text-foreground shrink-0">{model.split("/").pop()}</span>
                    <div className="flex items-center gap-3 text-muted-foreground text-[11px]">
                      <span>{stats.matches} calls</span>
                      <span className="font-mono">{stats.input_tokens.toLocaleString()} in</span>
                      <span className="font-mono">{stats.output_tokens.toLocaleString()} out</span>
                      <span className="font-mono text-foreground font-medium">${stats.cost_total?.toFixed(2) || "0.00"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {status.recent_matches?.length > 0 && (
        <div data-testid="recent-matches">
          <h3 className="text-sm font-medium mb-3">Recent Comparisons</h3>
          <div className="space-y-2">
            {status.recent_matches.map((m, i) => {
              const isExpanded = expandedLogs.has(i);
              const toggle = () => setExpandedLogs(prev => {
                const next = new Set(prev);
                next.has(i) ? next.delete(i) : next.add(i);
                return next;
              });
              return (
                <div key={i} className="border border-border rounded-lg overflow-hidden" data-testid={`log-entry-${i}`}>
                  <button
                    onClick={toggle}
                    className="w-full flex items-center gap-2 p-3 text-left text-sm hover:bg-secondary/20 transition-colors"
                    data-testid={`log-toggle-${i}`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                    <span className="font-medium truncate flex-1">{m.winner_title}</span>
                    <span className="text-muted-foreground text-xs shrink-0 mx-1">beat</span>
                    <span className="truncate text-muted-foreground flex-1">{m.paper1_title === m.winner_title ? m.paper2_title : m.paper1_title}</span>
                    <ModelBadge model={m.model_used} />
                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground shrink-0" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                  </button>
                  {isExpanded && (
                    <div className="px-3 pb-3 pt-0 border-t border-border/50 bg-secondary/10">
                      <div className="pt-2 space-y-2">
                        <div className="text-xs">
                          <span className="text-muted-foreground">Winner: </span>
                          <span className="font-medium">{m.winner_title}</span>
                        </div>
                        <div className="text-xs">
                          <span className="text-muted-foreground">Loser: </span>
                          <span>{m.paper1_title === m.winner_title ? m.paper2_title : m.paper1_title}</span>
                        </div>
                        {m.reasoning && (
                          <div className="text-xs mt-2">
                            <span className="text-muted-foreground block mb-1">Reasoning:</span>
                            <p className="text-foreground leading-relaxed whitespace-pre-wrap">{m.reasoning}</p>
                          </div>
                        )}
                        {m.created_at && (
                          <p className="text-[10px] text-muted-foreground/60 font-mono mt-2">{new Date(m.created_at).toLocaleString()}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


