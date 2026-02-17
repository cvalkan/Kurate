import { useState } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  RefreshCw, Swords, FileText, CheckCircle2, XCircle, Search,
  ChevronDown, Clock, Download, Sparkles, Activity,
} from "lucide-react";
import { ModelBadge } from "@/components/ModelBadge";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

function timeAgo(iso) {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
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

  const checkForNewPapers = async () => {
    setChecking(true);
    try {
      const res = await axios.get(`${API}/api/admin/check-new-papers?category=${adminCat}`, { headers: getAdminHeaders() });
      setFetchableCount(res.data.available || 0);
      toast.success(`${res.data.available || 0} new papers available`);
    } catch {
      toast.error("Failed to check for new papers");
    } finally {
      setChecking(false);
    }
  };

  const fetchAndSummarize = async () => {
    triggerFetch();
    setFetchableCount(null);
  };

  if (!status) return null;

  const scheduler = status.scheduler || {};
  const lastFetch = scheduler.last_fetch_at;
  const nextFetch = scheduler.next_fetch_at;
  const isGenerating = (scheduler.current_activity || "").includes("Generating summaries");

  // Summary stats from progress
  const totalPapers = progress?.total_papers || status.total_papers || 0;
  const papersWithPdf = progress?.papers_with_pdf || 0;
  const summaryInfo = progress?.summary_coverage;

  return (
    <div className="space-y-4" data-testid="admin-overview">
      {categories.length > 1 && (
        <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg overflow-x-auto scrollbar-none" data-testid="admin-cat-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={adminCat === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => { setAdminCat(c.id); setFetchableCount(null); }}
              className="text-xs h-8 shrink-0"
              data-testid={`admin-cat-${c.id}`}
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      {/* Section 1: Paper Ingestion */}
      <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="ingestion-section">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Paper Ingestion
          </h3>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">Auto-fetch</span>
            <Switch
              checked={!progress?.fetch_paused}
              onCheckedChange={toggleAutoFetch}
              data-testid="auto-fetch-toggle"
            />
          </div>
        </div>

        <div className="text-xs text-muted-foreground space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-foreground font-medium">{totalPapers}</span> papers
            {papersWithPdf > 0 && papersWithPdf < totalPapers && (
              <span>· <span className="font-mono">{papersWithPdf}</span> with PDFs</span>
            )}
            {summaryInfo && summaryInfo.with_summaries < totalPapers && (
              <span>· <span className="font-mono">{summaryInfo.with_summaries}</span> with summaries</span>
            )}
            {isGenerating && <span className="text-accent animate-pulse">· generating...</span>}
          </div>
          <div>
            Last fetched <span className="font-mono text-foreground">{timeAgo(lastFetch)}</span>
            {nextFetch && !progress?.fetch_paused && (
              <span> · Next in <span className="font-mono text-foreground">{timeAgo(nextFetch).replace(" ago", "")}</span></span>
            )}
            {progress?.fetch_paused && <span className="text-amber-500 ml-1">(auto-fetch off)</span>}
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
          {fetchableCount !== null && (
            <span className="text-xs font-mono text-accent">{fetchableCount} available</span>
          )}
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
              {progress.global_paused && (
                <span className="text-[10px] px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-medium">System paused</span>
              )}
              <span className="text-[10px] text-muted-foreground">Tournament</span>
              <Switch
                checked={!progress?.compare_paused && !progress?.tournament_paused}
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

          {/* Stats line */}
          <div className="text-xs text-muted-foreground border-t border-border/50 pt-2 mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span><span className="font-mono text-foreground font-medium">{status.total_matches?.toLocaleString()}</span> matches</span>
            {status.failed_matches > 0 && <span><span className="font-mono text-red-500">{status.failed_matches}</span> failed</span>}
            {!progress.goals_met && progress.estimated_matches_remaining > 0 && (
              <span>~<span className="font-mono text-foreground font-medium">{progress.estimated_matches_remaining}</span> remaining</span>
            )}
            <span className="ml-auto">
              {progress.tournament_paused ? (
                <span className="text-amber-600 font-medium">Paused</span>
              ) : progress.compare_paused ? (
                <span className="text-amber-500 font-medium">Matches paused</span>
              ) : progress.global_paused ? (
                <span className="text-amber-600 font-medium">System paused</span>
              ) : progress.goals_met ? (
                <span className="text-green-600">Converged</span>
              ) : (
                <span className="text-accent">Running</span>
              )}
            </span>
          </div>
        </div>
      )}

      {/* Recent matches log (collapsed by default) */}
      {status.recent_matches && status.recent_matches.length > 0 && (
        <details className="group">
          <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
            Recent matches ({status.recent_matches.length})
          </summary>
          <div className="mt-2 space-y-1 max-h-60 overflow-y-auto">
            {status.recent_matches.slice(0, 20).map((m, i) => (
              <div key={m.id || i} className="flex items-center gap-2 text-[11px] text-muted-foreground">
                {m.winner_title ? (
                  <CheckCircle2 className="h-3 w-3 text-green-600 shrink-0" />
                ) : (
                  <XCircle className="h-3 w-3 text-red-500 shrink-0" />
                )}
                <span className="truncate">{m.winner_title || "Failed"}</span>
                {m.created_at && <span className="font-mono text-[10px] shrink-0 ml-auto">{timeAgo(m.created_at)}</span>}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
