import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  RefreshCw, Swords, FileText, CheckCircle2, XCircle, Search,
  Clock, Download, Activity,
} from "lucide-react";
import { ModelBadge } from "@/components/ModelBadge";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

function timeAgo(iso) {
  if (!iso) return "unknown";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function StatCard({ label, value, icon: Icon }) {
  return (
    <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid={`stat-${label.toLowerCase()}`}>
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="font-mono text-2xl font-bold">{typeof value === "number" ? value.toLocaleString() : value}</div>
    </div>
  );
}

export function AdminOverview({
  status, progress, usageStats, categories, adminCat, setAdminCat,
  triggerFetch, loading, onRefresh,
}) {
  const [checking, setChecking] = useState(false);
  const [fetchableCount, setFetchableCount] = useState(null);

  const tid = encodeURIComponent(`cat=${adminCat}|mode=standard`);

  const toggleAutoFetch = async () => {
    try {
      const res = await axios.post(`${API}/api/admin/tournaments/${tid}/toggle-fetch`, {}, { headers: getAdminHeaders() });
      toast.success(res.data.fetch_paused ? "Auto-fetch OFF" : "Auto-fetch ON");
      if (onRefresh) onRefresh();
    } catch { toast.error("Failed to toggle auto-fetch"); }
  };

  const toggleTournament = async () => {
    try {
      const res = await axios.post(`${API}/api/admin/tournaments/${tid}/toggle-compare`, {}, { headers: getAdminHeaders() });
      toast.success(res.data.compare_paused ? "Tournament OFF" : "Tournament ON");
      if (onRefresh) onRefresh();
    } catch { toast.error("Failed to toggle tournament"); }
  };

  const checkForNewPapers = useCallback(async (silent = false) => {
    setChecking(true);
    try {
      const res = await axios.get(`${API}/api/admin/check-new-papers?category=${adminCat}`, { headers: getAdminHeaders() });
      setFetchableCount(res.data.available || 0);
    } catch {
      if (!silent) toast.error("Failed to check for new papers");
    } finally {
      setChecking(false);
    }
  }, [adminCat]);

  // Auto-check fetchable count on category switch (silent — don't toast on failure)
  useEffect(() => {
    setFetchableCount(null);
    checkForNewPapers(true);
  }, [adminCat, checkForNewPapers]);

  const fetchAndSummarize = async () => {
    triggerFetch();
    setFetchableCount(null);
  };

  if (!status) return (
    <div className="space-y-4 animate-pulse" data-testid="admin-overview-loading">
      <div className="h-8 bg-secondary/30 rounded-lg" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1,2,3,4].map(i => <div key={i} className="h-20 bg-secondary/30 rounded-lg" />)}
      </div>
    </div>
  );

  const scheduler = status.scheduler || {};
  const lastFetch = scheduler.last_fetch_at;
  const activity = scheduler.current_activity || "";

  const totalPapers = progress?.total_papers || status.total_papers || 0;
  const totalPapersInDb = progress?.papers_with_pdf || totalPapers;
  const papersWithPdf = progress?.papers_with_pdf || 0;
  const summariesCount = progress?.summary_coverage?.with_summaries || 0;

  // Only show activity indicators when there's actual work remaining AND system is active
  const systemActive = !progress?.global_paused;
  const isDownloading = systemActive && papersWithPdf < totalPapers && (activity.includes("downloading") || activity.includes("Fetching"));
  const isGenerating = systemActive && summariesCount < papersWithPdf && activity.includes("Generating summaries");

  return (
    <div className="space-y-4" data-testid="admin-overview">
      {categories.length > 1 && (
        <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg overflow-x-auto scrollbar-none" data-testid="admin-cat-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={adminCat === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => setAdminCat(c.id)}
              className="text-xs h-8 shrink-0"
              data-testid={`admin-cat-${c.id}`}
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Papers (Leaderboard)" value={totalPapers} icon={FileText} />
        <StatCard label="Matches" value={status.total_matches} icon={Swords} />
        <StatCard label="Failed" value={status.failed_matches} icon={XCircle} />
        <StatCard label="Unranked" value={status.unranked_papers} icon={Activity} />
      </div>

      {/* Section 1: Paper Ingestion */}
      <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="ingestion-section">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Paper Ingestion
          </h3>
          <div className="flex items-center gap-2">
            {progress?.global_paused ? (
              <span className="text-[10px] px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-medium">System paused</span>
            ) : (
              <span className="text-[10px] px-2 py-0.5 rounded bg-green-50 text-green-700 font-medium">System running</span>
            )}
            <span className="text-[10px] text-muted-foreground">Auto-fetch</span>
            <Switch
              checked={!progress?.fetch_paused}
              onCheckedChange={toggleAutoFetch}
              data-testid="auto-fetch-toggle"
            />
          </div>
        </div>

        {/* Pipeline status */}
        <div className="text-xs text-muted-foreground space-y-1.5">
          <div className="flex items-center gap-1.5" data-testid="fetchable-count">
            {fetchableCount !== null ? (
              <span>
                <span className="font-mono text-foreground font-medium text-base">{fetchableCount}</span> new papers available
              </span>
            ) : checking ? (
              <span className="animate-pulse">Checking for new papers...</span>
            ) : (
              <span>Checking...</span>
            )}
          </div>
          <div data-testid="downloaded-count">
            <span className="font-mono text-foreground font-medium">{papersWithPdf}</span>/<span className="font-mono">{totalPapers}</span> downloaded
            {isDownloading && <span className="text-accent animate-pulse ml-1">downloading...</span>}
          </div>
          <div data-testid="summarized-count">
            <span className="font-mono text-foreground font-medium">{summariesCount}</span>/<span className="font-mono">{papersWithPdf}</span> summarized
            {isGenerating && <span className="text-accent animate-pulse ml-1">generating...</span>}
          </div>
          <div className="pt-0.5">
            Last fetched <span className="font-mono text-foreground">{timeAgo(lastFetch)}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 mt-3">
          <Button
            onClick={checkForNewPapers}
            disabled={checking}
            variant="outline"
            size="sm"
            className="gap-1.5 text-xs h-8"
            data-testid="check-new-papers-btn"
          >
            <Search className={`h-3.5 w-3.5 ${checking ? "animate-spin" : ""}`} />
            {checking ? "Checking..." : "Check for new papers"}
          </Button>
          <Button
            onClick={fetchAndSummarize}
            disabled={loading.fetch}
            size="sm"
            className="gap-1.5 text-xs h-8"
            data-testid="fetch-and-summarize-btn"
          >
            <Download className={`h-3.5 w-3.5 ${loading.fetch ? "animate-spin" : ""}`} />
            {loading.fetch ? "Fetching..." : "Fetch & generate summaries"}
          </Button>
        </div>
      </div>

      {/* Section 2: Tournament Progress */}
      {progress && (
        <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="tournament-section">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium flex items-center gap-1.5">
              <Swords className="h-3.5 w-3.5" />
              Tournament
            </h3>
            <div className="flex items-center gap-2">
              {progress.global_paused ? (
                <span className="text-[10px] px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-medium">System paused</span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 rounded bg-green-50 text-green-700 font-medium">System running</span>
              )}
              <span className="text-[10px] text-muted-foreground">Tournament</span>
              <Switch
                checked={!progress?.compare_paused}
                onCheckedChange={toggleTournament}
                data-testid="tournament-toggle"
              />
            </div>
          </div>

          {/* Convergence goals */}
          {progress.goals_met ? (
            <div className="flex items-center gap-2 text-xs text-green-600 mb-2">
              <CheckCircle2 className="h-3.5 w-3.5" />
              All convergence goals met
            </div>
          ) : (
            <div className="space-y-1.5 mb-2">
              {["goal1", "goal2", "goal3"].map(g => {
                const goal = progress[g];
                if (!goal) return null;
                return (
                  <div key={g} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      {goal.met
                        ? <CheckCircle2 className="h-3 w-3 text-green-600" />
                        : <Clock className="h-3 w-3 text-amber-500" />
                      }
                      <span className={goal.met ? "text-green-600" : "text-muted-foreground"}>{goal.label}</span>
                    </div>
                    {!goal.met && (
                      <span className="font-mono text-muted-foreground">
                        {goal.median_margin != null && (
                          <span className={goal.median_margin <= (progress.goal2?.label?.match(/\d+/)?.[0] || 12) ? "text-green-600" : "text-amber-500"}>
                            median={goal.median_margin}%
                          </span>
                        )}
                        {goal.median_margin != null && goal.done != null && " · "}
                        {goal.done != null && goal.total != null && `${goal.done}/${goal.total}`}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Remaining estimate + status */}
          <div className="text-xs text-muted-foreground border-t border-border/50 pt-2 mt-2 flex items-center justify-between">
            <span>
              {!progress.goals_met && progress.estimated_matches_remaining > 0 && (
                <>~<span className="font-mono text-foreground font-medium">{progress.estimated_matches_remaining}</span> matches remaining</>
              )}
            </span>
            <span>
              {progress.goals_met ? (
                <span className="text-green-600 font-medium">Converged</span>
              ) : !progress.compare_paused && !progress.global_paused ? (
                <span className="text-accent font-medium">Running</span>
              ) : null}
            </span>
          </div>
        </div>
      )}

      {/* Usage Statistics */}
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
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">By Model</div>
              <div className="space-y-1">
                {Object.entries(usageStats.models).sort((a, b) => (b[1].cost_total || 0) - (a[1].cost_total || 0)).map(([model, stats]) => (
                  <div key={model} className="flex items-center justify-between text-xs">
                    <span className="font-mono text-muted-foreground">{model.split("/").pop()}</span>
                    <div className="flex items-center gap-4 text-muted-foreground font-mono text-[11px]">
                      <span>{stats.matches} calls</span>
                      <span>{(stats.input_tokens || 0).toLocaleString()} in</span>
                      <span>{(stats.output_tokens || 0).toLocaleString()} out</span>
                      <span className="text-foreground font-medium">${(stats.cost_total || 0).toFixed(2)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Recent Comparisons */}
      {status.recent_matches && status.recent_matches.length > 0 && (
        <div data-testid="recent-comparisons">
          <h3 className="text-sm font-medium mb-3">Recent Comparisons</h3>
          <div className="space-y-2">
            {status.recent_matches.slice(0, 10).map((m, i) => (
              <div key={m.id || i} className="p-3 bg-secondary/30 rounded-lg border border-border flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                <span className="text-sm truncate flex-1 font-medium">{m.winner_title || "Unknown"}</span>
                <span className="text-xs text-muted-foreground shrink-0">beat</span>
                <span className="text-sm truncate flex-1 text-muted-foreground">{m.loser_title || "Unknown"}</span>
                {m.model_used && <ModelBadge model={m.model_used} />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
