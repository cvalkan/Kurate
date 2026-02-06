import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Settings, RefreshCw, Swords, Activity, LogOut,
  FileText, Bot, CheckCircle2, XCircle, Save, RotateCcw, ChevronDown, ChevronUp, HelpCircle,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

function StatCard({ label, value, sub, icon: Icon }) {
  return (
    <div className="p-4 bg-secondary/30 rounded-lg border border-border">
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="font-mono text-2xl font-bold">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function ModelBadge({ model }) {
  if (!model || !model.provider) return null;
  const colors = {
    openai: "bg-green-50 text-green-700 border-green-200",
    anthropic: "bg-orange-50 text-orange-700 border-orange-200",
    gemini: "bg-blue-50 text-blue-700 border-blue-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border ${colors[model.provider] || "bg-secondary text-muted-foreground border-border"}`}>
      <Bot className="h-2.5 w-2.5" />
      {model.model?.split("-").slice(0, 2).join("-") || model.provider}
    </span>
  );
}

export default function AdminPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [prompt, setPrompt] = useState(null);
  const [editSettings, setEditSettings] = useState({});
  const [editPrompt, setEditPrompt] = useState({});
  const [loading, setLoading] = useState({ fetch: false, compare: false, settings: false, prompt: false });
  const [activeTab, setActiveTab] = useState("overview");
  const [expandedLogs, setExpandedLogs] = useState(new Set());
  const [progress, setProgress] = useState(null);

  const fetchAll = useCallback(async () => {
    const headers = getAdminHeaders();
    try {
      const [statusRes, settingsRes, promptRes, progressRes] = await Promise.all([
        axios.get(`${API}/api/admin/status`, { headers }),
        axios.get(`${API}/api/admin/settings`, { headers }),
        axios.get(`${API}/api/admin/prompt`, { headers }),
        axios.get(`${API}/api/admin/progress`, { headers }),
      ]);
      setStatus(statusRes.data);
      setSettings(settingsRes.data.settings);
      setEditSettings(settingsRes.data.settings);
      setPrompt(promptRes.data);
      setEditPrompt(promptRes.data);
      setProgress(progressRes.data);
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        sessionStorage.removeItem("admin_token");
        navigate("/admin");
      }
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("admin_token")) {
      navigate("/admin");
      return;
    }
    fetchAll();
    const interval = setInterval(fetchAll, 15000);
    return () => clearInterval(interval);
  }, [fetchAll, navigate]);

  const triggerFetch = async () => {
    setLoading((l) => ({ ...l, fetch: true }));
    try {
      const res = await axios.post(`${API}/api/admin/fetch`, {}, { headers: getAdminHeaders() });
      toast.success(`Fetch complete: ${res.data.new_papers || 0} new papers`);
      fetchAll();
    } catch (err) {
      toast.error("Fetch failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setLoading((l) => ({ ...l, fetch: false }));
    }
  };

  const triggerCompare = async () => {
    setLoading((l) => ({ ...l, compare: true }));
    try {
      await axios.post(`${API}/api/admin/compare`, {}, { headers: getAdminHeaders() });
      toast.success("Comparison round started");
    } catch (err) {
      toast.error("Failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setLoading((l) => ({ ...l, compare: false }));
    }
  };

  const saveSettings = async () => {
    setLoading((l) => ({ ...l, settings: true }));
    try {
      const updates = {};
      for (const key of ["fetch_interval_hours", "max_papers_per_fetch", "comparisons_per_round", "top_k_focus", "anchor_comparisons", "min_matches_per_paper"]) {
        if (editSettings[key] !== settings[key]) updates[key] = Number(editSettings[key]);
      }
      if (editSettings.exploration_constant !== settings.exploration_constant)
        updates.exploration_constant = parseFloat(editSettings.exploration_constant);
      if (editSettings.auto_process !== settings.auto_process)
        updates.auto_process = editSettings.auto_process;
      if (editSettings.admin_password && editSettings.admin_password !== settings.admin_password)
        updates.admin_password = editSettings.admin_password;

      if (Object.keys(updates).length === 0) {
        toast.info("No changes to save");
        return;
      }
      await axios.put(`${API}/api/admin/settings`, updates, { headers: getAdminHeaders() });
      if (updates.admin_password) {
        sessionStorage.setItem("admin_token", updates.admin_password);
      }
      toast.success("Settings saved");
      fetchAll();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setLoading((l) => ({ ...l, settings: false }));
    }
  };

  const savePrompt = async () => {
    setLoading((l) => ({ ...l, prompt: true }));
    try {
      await axios.put(`${API}/api/admin/prompt`, {
        system_prompt: editPrompt.system_prompt,
        user_prompt: editPrompt.user_prompt,
      }, { headers: getAdminHeaders() });
      toast.success("Prompt saved");
      fetchAll();
    } catch (err) {
      toast.error("Save failed");
    } finally {
      setLoading((l) => ({ ...l, prompt: false }));
    }
  };

  const resetPrompt = async () => {
    try {
      await axios.delete(`${API}/api/admin/prompt`, { headers: getAdminHeaders() });
      toast.success("Prompt reset to default");
      fetchAll();
    } catch (err) {
      toast.error("Reset failed");
    }
  };

  const logout = () => {
    sessionStorage.removeItem("admin_token");
    navigate("/admin");
  };

  const isProcessing = status?.scheduler?.is_processing || status?.scheduler?.is_fetching;

  const tabs = [
    { key: "overview", label: "Overview", icon: Activity },
    { key: "settings", label: "Settings", icon: Settings },
    { key: "prompt", label: "Prompt", icon: FileText },
  ];

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-heading text-2xl font-semibold" data-testid="admin-title">Admin Panel</h1>
        <Button variant="ghost" size="sm" onClick={logout} data-testid="logout-button">
          <LogOut className="h-4 w-4 mr-1" /> Sign out
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="admin-tabs">
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <Button
              key={t.key}
              variant={activeTab === t.key ? "default" : "ghost"}
              size="sm"
              onClick={() => setActiveTab(t.key)}
              className="gap-1.5 text-xs h-8"
              data-testid={`tab-${t.key}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </Button>
          );
        })}
      </div>

      {/* Overview Tab */}
      {activeTab === "overview" && status && (
        <div className="space-y-6" data-testid="admin-overview">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Papers" value={status.total_papers} icon={FileText} />
            <StatCard label="Matches" value={status.total_matches} icon={Swords} />
            <StatCard label="Failed" value={status.failed_matches} icon={XCircle} />
            <StatCard label="Unranked" value={status.unranked_papers} icon={Activity} />
          </div>

          {/* Progress Indicator */}
          {progress && (
            <div className="p-4 bg-secondary/30 rounded-lg border border-border" data-testid="progress-indicator">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium">Ranking Progress</h3>
                <span className="font-mono text-sm font-bold text-accent">{progress.progress_pct}%</span>
              </div>
              <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden mb-3">
                <div className="h-full bg-accent rounded-full transition-all duration-500" style={{ width: `${progress.progress_pct}%` }} />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-muted-foreground">
                <div>
                  <span className="block text-foreground font-mono font-medium">{progress.papers_at_min_matches}/{progress.total_papers}</span>
                  at min matches ({progress.min_matches_setting})
                </div>
                <div>
                  <span className="block text-foreground font-mono font-medium">{progress.papers_below_min_matches}</span>
                  below minimum
                </div>
                <div>
                  <span className="block text-foreground font-mono font-medium">{progress.papers_converged}</span>
                  converged (CI &le; ±15)
                </div>
                <div>
                  <span className="block text-foreground font-mono font-medium">~{progress.estimated_remaining}</span>
                  matches remaining
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-3">
            <Button onClick={triggerFetch} disabled={loading.fetch || isProcessing} className="gap-2" data-testid="trigger-fetch">
              <RefreshCw className={`h-4 w-4 ${loading.fetch ? "animate-spin" : ""}`} />
              {loading.fetch ? "Fetching..." : "Fetch Papers"}
            </Button>
            <Button onClick={triggerCompare} disabled={loading.compare || isProcessing} variant="outline" className="gap-2" data-testid="trigger-compare">
              <Swords className={`h-4 w-4 ${loading.compare ? "animate-spin" : ""}`} />
              {loading.compare ? "Starting..." : "Run Comparison Round"}
            </Button>
          </div>

          {/* Scheduler Status */}
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
                <div>Processing: <span className="font-mono text-foreground">{isProcessing ? "Yes" : "No"}</span></div>
              </div>
            </div>
          )}

          {/* Recent Matches */}
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
      )}

      {/* Settings Tab */}
      {activeTab === "settings" && settings && (
        <TooltipProvider delayDuration={200}>
        <div className="space-y-6 max-w-lg" data-testid="admin-settings">
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Fetch Interval (hours)</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">How often to check arXiv for new Robotics papers. Default: 24h.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.fetch_interval_hours || ""} onChange={(e) => setEditSettings({ ...editSettings, fetch_interval_hours: e.target.value })} data-testid="setting-fetch-interval" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Max Papers Per Fetch</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Maximum number of papers to retrieve from arXiv per fetch cycle.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.max_papers_per_fetch || ""} onChange={(e) => setEditSettings({ ...editSettings, max_papers_per_fetch: e.target.value })} data-testid="setting-max-papers" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Comparisons Per Round</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Number of pairwise LLM comparisons to run each round. Higher = more API calls but faster ranking convergence.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.comparisons_per_round || ""} onChange={(e) => setEditSettings({ ...editSettings, comparisons_per_round: e.target.value })} data-testid="setting-comparisons" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Top-K Focus</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">The matchmaker focuses comparisons on papers near this rank boundary to keep the top-K rankings accurate.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.top_k_focus || ""} onChange={(e) => setEditSettings({ ...editSettings, top_k_focus: e.target.value })} data-testid="setting-topk" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Exploration Constant (UCB)</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Controls explore vs exploit tradeoff. Higher values = more exploration of uncertain papers. Standard: 1.414.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" step="0.1" value={editSettings.exploration_constant || ""} onChange={(e) => setEditSettings({ ...editSettings, exploration_constant: e.target.value })} data-testid="setting-exploration" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Anchor Comparisons</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Number of existing ranked papers each new paper is compared against for initial calibration.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.anchor_comparisons || ""} onChange={(e) => setEditSettings({ ...editSettings, anchor_comparisons: e.target.value })} data-testid="setting-anchors" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Min Matches Per Paper</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Minimum number of comparisons each paper must have. Papers below this threshold are prioritized by the matchmaker.</p></TooltipContent></Tooltip>
              </div>
              <Input type="number" value={editSettings.min_matches_per_paper || ""} onChange={(e) => setEditSettings({ ...editSettings, min_matches_per_paper: e.target.value })} data-testid="setting-min-matches" />
            </div>
            <div className="flex items-center gap-2">
              <Switch checked={editSettings.auto_process || false} onCheckedChange={(v) => setEditSettings({ ...editSettings, auto_process: v })} data-testid="setting-auto-process" />
              <Label className="text-xs">Auto Process</Label>
              <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
              <TooltipContent side="right"><p className="max-w-52 text-xs">When enabled, automatically runs comparison rounds after each fetch cycle and on schedule.</p></TooltipContent></Tooltip>
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Admin Password</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Change the admin panel password. You will need to re-login after changing.</p></TooltipContent></Tooltip>
              </div>
              <Input type="password" value={editSettings.admin_password || ""} onChange={(e) => setEditSettings({ ...editSettings, admin_password: e.target.value })} data-testid="setting-password" />
            </div>
          </div>
          <Button onClick={saveSettings} disabled={loading.settings} className="gap-2" data-testid="save-settings">
            <Save className="h-4 w-4" />
            {loading.settings ? "Saving..." : "Save Settings"}
          </Button>
        </div>
        </TooltipProvider>
      )}

      {/* Prompt Tab */}
      {activeTab === "prompt" && prompt && (
        <div className="space-y-4 max-w-2xl" data-testid="admin-prompt">
          {prompt.is_custom && (
            <Badge variant="outline" className="text-xs">Custom prompt active</Badge>
          )}
          <div>
            <Label className="text-xs">System Prompt</Label>
            <Textarea
              rows={10}
              value={editPrompt.system_prompt || ""}
              onChange={(e) => setEditPrompt({ ...editPrompt, system_prompt: e.target.value })}
              className="font-mono text-xs"
              data-testid="prompt-system"
            />
          </div>
          <div>
            <Label className="text-xs">User Prompt Template</Label>
            <Textarea
              rows={8}
              value={editPrompt.user_prompt || ""}
              onChange={(e) => setEditPrompt({ ...editPrompt, user_prompt: e.target.value })}
              className="font-mono text-xs"
              data-testid="prompt-user"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Variables: {"{paper1_title}"}, {"{paper1_content}"}, {"{paper2_title}"}, {"{paper2_content}"}
            </p>
          </div>
          <div className="flex gap-2">
            <Button onClick={savePrompt} disabled={loading.prompt} className="gap-2" data-testid="save-prompt">
              <Save className="h-4 w-4" />
              {loading.prompt ? "Saving..." : "Save Prompt"}
            </Button>
            <Button variant="outline" onClick={resetPrompt} className="gap-2" data-testid="reset-prompt">
              <RotateCcw className="h-4 w-4" />
              Reset to Default
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
