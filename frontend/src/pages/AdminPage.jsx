import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Settings, Activity, LogOut, FileText, Save, HelpCircle, FlaskConical, MessageSquare, Users,
  Sliders,
} from "lucide-react";
import { toast } from "sonner";
import { AdminOverview } from "@/components/AdminOverview";
import { AdminExperiment } from "@/components/AdminExperiment";
import { AdminStatistics } from "@/components/AdminStatistics";
import { AdminCategories } from "@/components/AdminCategories";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export default function AdminPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [prompt, setPrompt] = useState(null);
  const [editSettings, setEditSettings] = useState({});
  const [editPrompt, setEditPrompt] = useState({});
  const [loading, setLoading] = useState({ fetch: false, compare: false, settings: false, prompt: false });
  const [activeTab, setActiveTab] = useState("statistics");
  const [progress, setProgress] = useState(null);
  const [usageStats, setUsageStats] = useState(null);
  const [manualMatches, setManualMatches] = useState(null);
  const [summaryPrompt, setSummaryPrompt] = useState(null);
  const [editSummaryPrompt, setEditSummaryPrompt] = useState({});
  const [editPredictionPrompt, setEditPredictionPrompt] = useState({});
  const [categories, setCategories] = useState([]);
  const [adminCat, setAdminCat] = useState("");

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      setAdminCat(res.data.default || "cs.RO");
    }).catch(() => setAdminCat("cs.RO"));
  }, []);

  const fetchLiveData = useCallback(async () => {
    if (!adminCat) return;
    const headers = getAdminHeaders();
    try {
      const [statusRes, progressRes, statsRes] = await Promise.all([
        axios.get(`${API}/api/admin/status`, { headers, params: { category: adminCat } }),
        axios.get(`${API}/api/admin/progress`, { headers, params: { category: adminCat } }),
        axios.get(`${API}/api/admin/stats`, { headers, params: { category: adminCat } }),
      ]);
      setStatus(statusRes.data);
      setProgress(progressRes.data);
      if (manualMatches === null) {
        const est = progressRes.data?.estimated_matches_remaining;
        setManualMatches(est > 0 ? Math.min(est, 100) : 20);
      }
      setUsageStats(statsRes.data);
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        sessionStorage.removeItem("admin_token");
        navigate("/admin");
      }
    }
  }, [navigate, adminCat]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch global settings (only on mount, not on category change)
  const fetchGlobalSettings = useCallback(async () => {
    const headers = getAdminHeaders();
    try {
      const [settingsRes, promptRes, summaryPromptRes, predPromptRes] = await Promise.all([
        axios.get(`${API}/api/admin/settings`, { headers }),
        axios.get(`${API}/api/admin/prompt`, { headers }),
        axios.get(`${API}/api/admin/summary-prompt`, { headers }),
        axios.get(`${API}/api/admin/prediction-prompt`, { headers }),
      ]);
      setSettings(settingsRes.data.settings);
      setEditSettings(settingsRes.data.settings);
      setPrompt(promptRes.data);
      setEditPrompt(promptRes.data);
      setSummaryPrompt(summaryPromptRes.data);
      setEditSummaryPrompt(summaryPromptRes.data);
      setEditPredictionPrompt(predPromptRes.data);
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        sessionStorage.removeItem("admin_token");
        navigate("/admin");
      }
    }
  }, [navigate]);

  const fetchAll = useCallback(async () => {
    await Promise.all([fetchGlobalSettings(), fetchLiveData()]);
  }, [fetchGlobalSettings, fetchLiveData]);

  // Initial load: fetch everything
  useEffect(() => {
    if (!sessionStorage.getItem("admin_token")) { navigate("/admin"); return; }
    fetchGlobalSettings();
  }, [fetchGlobalSettings, navigate]);

  // When category changes, only fetch category-specific data (fast)
  useEffect(() => {
    if (!adminCat || !sessionStorage.getItem("admin_token")) return;
    fetchLiveData();
  }, [adminCat]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll at 15s when tournament is active, 30s when idle/paused (aligns with server cache TTL)
  useEffect(() => {
    const isActive = progress && !progress.paused && !progress.goals_met;
    const interval = setInterval(fetchLiveData, isActive ? 15000 : 30000);
    return () => clearInterval(interval);
  }, [fetchLiveData, progress]);

  const triggerFetch = async () => {
    setLoading(l => ({ ...l, fetch: true }));
    try {
      const res = await axios.post(`${API}/api/admin/fetch`, { category: adminCat }, { headers: getAdminHeaders() });
      if (res.data.status === "already_running") {
        toast.info(`Fetch already running for ${adminCat} (started ${new Date(res.data.started_at).toLocaleTimeString()})`);
        setLoading(l => ({ ...l, fetch: false }));
        return;
      }
      toast.info(`Fetch & generate task started for ${adminCat}. Polling for completion...`);
      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API}/api/admin/fetch-status/${adminCat}`, { headers: getAdminHeaders() });
          const s = statusRes.data;
          if (s.status === "completed") {
            clearInterval(pollInterval);
            toast.success(`Fetch complete: ${s.result?.new_papers || 0} new ${adminCat} papers`);
            setLoading(l => ({ ...l, fetch: false }));
            fetchAll();
          } else if (s.status === "failed") {
            clearInterval(pollInterval);
            toast.error(`Fetch failed: ${s.error}`);
            setLoading(l => ({ ...l, fetch: false }));
          }
        } catch { /* keep polling */ }
      }, 5000);
    } catch (err) {
      toast.error("Fetch failed: " + (err.response?.data?.detail || err.message));
      setLoading(l => ({ ...l, fetch: false }));
    }
  };

  const triggerCompare = async () => {
    setLoading(l => ({ ...l, compare: true }));
    try {
      const res = await axios.post(`${API}/api/admin/compare`, { num_matches: manualMatches, category: adminCat }, { headers: getAdminHeaders() });
      toast.success(`Started ${res.data.num_matches} comparisons for ${adminCat}`);
    } catch (err) { toast.error("Failed: " + (err.response?.data?.detail || err.message)); }
    finally { setLoading(l => ({ ...l, compare: false })); }
  };

  const togglePause = async () => {
    try {
      const res = await axios.post(`${API}/api/admin/toggle-pause`, {}, { headers: getAdminHeaders() });
      toast.success(res.data.paused ? "System paused" : "System resumed");
      fetchAll();
    } catch (err) { toast.error("Failed: " + (err.response?.data?.detail || err.message)); }
  };

  const saveSettings = async () => {
    setLoading(l => ({ ...l, settings: true }));
    try {
      const updates = {};
      for (const key of ["fetch_interval_hours", "max_papers_per_fetch", "parallel_agents", "top_k_focus", "max_new_matches_per_round", "ci_target", "ci_target_general", "calibration_ratio"]) {
        if (editSettings[key] !== settings[key]) {
          updates[key] = Number(editSettings[key]);
        }
      }
      if (editSettings.summary_source && editSettings.summary_source !== settings.summary_source) {
        updates.summary_source = editSettings.summary_source;
      }
      if (editSettings.paused !== settings.paused) updates.paused = editSettings.paused;
      if (editSettings.show_rating_column !== settings.show_rating_column) updates.show_rating_column = editSettings.show_rating_column;
      if (editSettings.show_gap_column !== settings.show_gap_column) updates.show_gap_column = editSettings.show_gap_column;
      if (editSettings.admin_password && editSettings.admin_password !== settings.admin_password) updates.admin_password = editSettings.admin_password;
      if (Object.keys(updates).length === 0) { toast.info("No changes to save"); return; }
      await axios.put(`${API}/api/admin/settings`, updates, { headers: getAdminHeaders() });
      if (updates.admin_password) sessionStorage.setItem("admin_token", updates.admin_password);
      toast.success("Settings saved");
      fetchAll();
    } catch (err) { toast.error("Save failed: " + (err.response?.data?.detail || err.message)); }
    finally { setLoading(l => ({ ...l, settings: false })); }
  };

  const savePrompt = async () => {
    setLoading(l => ({ ...l, prompt: true }));
    try {
      await axios.put(`${API}/api/admin/prompt`, { system_prompt: editPrompt.system_prompt, user_prompt: editPrompt.user_prompt }, { headers: getAdminHeaders() });
      toast.success("Prompt saved");
      fetchAll();
    } catch (err) { toast.error("Save failed"); }
    finally { setLoading(l => ({ ...l, prompt: false })); }
  };

  const logout = () => { sessionStorage.removeItem("admin_token"); navigate("/admin"); };

  const tabs = [
    { key: "statistics", label: "Statistics", icon: Activity },
    { key: "overview", label: "Tournaments", icon: Sliders },
    { key: "settings", label: "Settings", icon: Settings },
    { key: "prompt", label: "Prompt", icon: FileText },
    { key: "experiment", label: "Experiment", icon: FlaskConical },
    { key: "suggestions", label: "Suggestions", icon: MessageSquare },
    { key: "users", label: "Users", icon: Users },
  ];

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-heading text-2xl font-semibold" data-testid="admin-title">Admin Panel</h1>
        <Button variant="ghost" size="sm" onClick={logout} data-testid="logout-button">
          <LogOut className="h-4 w-4 mr-1" /> Sign out
        </Button>
      </div>

      <div className="flex items-center gap-1 mb-6 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="admin-tabs">
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <Button key={t.key} variant={activeTab === t.key ? "default" : "ghost"} size="sm"
              onClick={() => setActiveTab(t.key)} className="gap-1.5 text-xs h-8" data-testid={`tab-${t.key}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </Button>
          );
        })}
      </div>

      {activeTab === "statistics" && (
        <AdminStatistics categories={categories} />
      )}

      {activeTab === "overview" && (
        <AdminOverview
          status={status} progress={progress} usageStats={usageStats}
          categories={categories} adminCat={adminCat} setAdminCat={setAdminCat}
          triggerFetch={triggerFetch}
          loading={loading}
          onRefresh={fetchAll}
        />
      )}

      {activeTab === "settings" && settings && (
        <TooltipProvider delayDuration={200}>
        <div className="space-y-6 max-w-xl" data-testid="admin-settings">
          <AdminCategories onCategoriesChanged={() => {
            axios.get(`${API}/api/categories`).then(res => {
              setCategories(res.data.categories || []);
              // If current adminCat was removed, switch to first available
              const ids = (res.data.categories || []).map(c => c.id);
              if (!ids.includes(adminCat) && ids.length > 0) setAdminCat(ids[0]);
            }).catch(() => {});
          }} />

          <div className="border-t border-border pt-6 space-y-4">
            <h3 className="text-sm font-medium">System Parameters</h3>
            {[
              { key: "fetch_interval_hours", label: "Fetch Interval (hours)", help: "How often to check arXiv for new papers. Default: 24h." },
              { key: "max_papers_per_fetch", label: "Max New Papers Per Fetch", help: "How many new primary-category papers to fetch from arXiv per auto-fetch cycle. Papers are sorted newest-first; duplicates and cross-listings are filtered out." },
              { key: "parallel_agents", label: "Parallel Agents", help: "Concurrent LLM comparisons per batch (1-20).", min: 1, max: 20 },
              { key: "top_k_focus", label: "Top-K Focus", help: "Number of top papers to apply tight CI and cross-matching." },
              { key: "max_new_matches_per_round", label: "Max Matches Per Paper Per Round", help: "Max new matches per paper per round." },
              { key: "ci_target", label: "Top-K CI Target (%)", help: "Tight Wilson CI margin target for top-K papers. Default: 10%", min: 1, max: 30 },
              { key: "ci_target_general", label: "General CI Target (%)", help: "Looser Wilson CI margin target for non-top-K papers. Default: 15%", min: 5, max: 50 },
              { key: "calibration_ratio", label: "Calibration Ratio (%)", help: "% of new-paper matches paired against established (converged) papers for score calibration. 0=all needy-vs-needy, 100=all needy-vs-established. Default: 50%", min: 0, max: 100 },
            ].map(({ key, label, help, min, max, step }) => (
              <div key={key}>
                <div className="flex items-center gap-1.5 mb-1">
                  <Label className="text-xs">{label}</Label>
                  <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                  <TooltipContent side="right"><p className="max-w-52 text-xs">{help}</p></TooltipContent></Tooltip>
                </div>
                <Input
                  type="number" min={min} max={max} step={step}
                  value={editSettings[key] ?? ""}
                  onChange={(e) => {
                    let v = step && step < 1 ? parseFloat(e.target.value) : Number(e.target.value);
                    if (isNaN(v)) v = "";
                    if (v !== "" && min !== undefined && v < min) v = min;
                    if (v !== "" && max !== undefined && v > max) v = max;
                    setEditSettings({ ...editSettings, [key]: v });
                  }}
                  data-testid={`setting-${key}`}
                />
              </div>
            ))}
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Summary Source</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Which model's summary to use for comparisons. round_robin rotates between all 3.</p></TooltipContent></Tooltip>
              </div>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                value={editSettings.summary_source || "round_robin"}
                onChange={(e) => setEditSettings({ ...editSettings, summary_source: e.target.value })}
                data-testid="setting-summary-source"
              >
                <option value="round_robin">Round Robin (all 3)</option>
                <option value="claude">Claude</option>
                <option value="gemini">Gemini</option>
                <option value="gpt">GPT</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <Switch checked={editSettings.paused || false} onCheckedChange={(v) => setEditSettings({ ...editSettings, paused: v })} data-testid="setting-paused" />
              <Label className="text-xs">Paused</Label>
              <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
              <TooltipContent side="right"><p className="max-w-52 text-xs">Stop all automatic processing (comparisons and paper fetching).</p></TooltipContent></Tooltip>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Switch checked={editSettings.show_rating_column !== false} onCheckedChange={(v) => setEditSettings({ ...editSettings, show_rating_column: v })} />
                <Label className="text-xs">Show Rating column</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch checked={editSettings.show_gap_column !== false} onCheckedChange={(v) => setEditSettings({ ...editSettings, show_gap_column: v })} />
                <Label className="text-xs">Show Gap column</Label>
              </div>
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Label className="text-xs">Admin Password</Label>
                <Tooltip><TooltipTrigger asChild><HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" /></TooltipTrigger>
                <TooltipContent side="right"><p className="max-w-52 text-xs">Change the admin panel password.</p></TooltipContent></Tooltip>
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

      {activeTab === "prompt" && prompt && (
        <div className="space-y-8 max-w-2xl" data-testid="admin-prompt">
          <div className="space-y-4">
            <h3 className="text-sm font-medium">Comparison Prompt</h3>
            <p className="text-xs text-muted-foreground">Used when comparing two papers head-to-head.</p>
            <div>
              <Label className="text-xs">System Prompt</Label>
              <Textarea rows={10} value={editPrompt.system_prompt || ""} onChange={(e) => setEditPrompt({ ...editPrompt, system_prompt: e.target.value })} className="font-mono text-xs" data-testid="prompt-system" />
            </div>
            <div>
              <Label className="text-xs">User Prompt Template</Label>
              <Textarea rows={8} value={editPrompt.user_prompt || ""} onChange={(e) => setEditPrompt({ ...editPrompt, user_prompt: e.target.value })} className="font-mono text-xs" data-testid="prompt-user" />
              <p className="text-xs text-muted-foreground mt-1">Variables: {"{paper1_title}"}, {"{paper1_content}"}, {"{paper2_title}"}, {"{paper2_content}"}</p>
            </div>
            <Button onClick={savePrompt} disabled={loading.prompt} className="gap-2" data-testid="save-prompt">
              <Save className="h-4 w-4" />
              {loading.prompt ? "Saving..." : "Save Comparison Prompt"}
            </Button>
          </div>

          <div className="space-y-4 border-t border-border pt-6">
            <h3 className="text-sm font-medium">Impact Summary Prompt</h3>
            <p className="text-xs text-muted-foreground">Used to generate the AI Impact Assessment on paper detail pages.</p>
            <div>
              <Label className="text-xs">System Prompt</Label>
              <Textarea rows={8} value={editSummaryPrompt.system_prompt || ""} onChange={(e) => setEditSummaryPrompt({ ...editSummaryPrompt, system_prompt: e.target.value })} className="font-mono text-xs" data-testid="summary-prompt-system" />
            </div>
            <div>
              <Label className="text-xs">User Prompt Template</Label>
              <Textarea rows={6} value={editSummaryPrompt.user_prompt || ""} onChange={(e) => setEditSummaryPrompt({ ...editSummaryPrompt, user_prompt: e.target.value })} className="font-mono text-xs" data-testid="summary-prompt-user" />
              <p className="text-xs text-muted-foreground mt-1">Variables: {"{title}"}, {"{authors}"}, {"{paper_content}"}, {"{win_rate}"}, {"{num_matches}"}, {"{match_context}"}</p>
            </div>
            <Button onClick={async () => {
              try {
                await axios.put(`${API}/api/admin/summary-prompt`, { system_prompt: editSummaryPrompt.system_prompt, user_prompt: editSummaryPrompt.user_prompt }, { headers: getAdminHeaders() });
                toast.success("Summary prompt saved");
                fetchAll();
              } catch { toast.error("Save failed"); }
            }} className="gap-2" data-testid="save-summary-prompt">
              <Save className="h-4 w-4" />
              Save Summary Prompt
            </Button>
          </div>

          <div className="space-y-4 border-t border-border pt-6">
            <h3 className="text-sm font-medium flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-accent" />
              Prediction Prompt (Surprisingly Popular)
            </h3>
            <p className="text-xs text-muted-foreground">Used for the prediction tournament comparisons.</p>
            <div>
              <Label className="text-xs">System Prompt</Label>
              <Textarea rows={10} value={editPredictionPrompt.system_prompt || ""} onChange={(e) => setEditPredictionPrompt({ ...editPredictionPrompt, system_prompt: e.target.value })} className="font-mono text-xs" />
            </div>
            <div>
              <Label className="text-xs">User Prompt Template</Label>
              <Textarea rows={6} value={editPredictionPrompt.user_prompt || ""} onChange={(e) => setEditPredictionPrompt({ ...editPredictionPrompt, user_prompt: e.target.value })} className="font-mono text-xs" />
              <p className="text-xs text-muted-foreground mt-1">Variables: {"{paper1_title}"}, {"{paper1_content}"}, {"{paper2_title}"}, {"{paper2_content}"}</p>
            </div>
            <Button onClick={async () => {
              try {
                await axios.put(`${API}/api/admin/prediction-prompt`, { system_prompt: editPredictionPrompt.system_prompt, user_prompt: editPredictionPrompt.user_prompt }, { headers: getAdminHeaders() });
                toast.success("Prediction prompt saved");
              } catch { toast.error("Save failed"); }
            }} className="gap-2">
              <Save className="h-4 w-4" />
              Save Prediction Prompt
            </Button>
          </div>

          <div className="space-y-4 border-t border-border pt-6">
            <h3 className="text-sm font-medium">Rating Prompt</h3>
            <p className="text-xs text-muted-foreground">Unified prompt for single-item rating — used by "Generate Ratings" button and validation experiments.</p>
            <RatingPromptViewer />
          </div>
        </div>
      )}

      {activeTab === "experiment" && <AdminExperiment />}

      {activeTab === "suggestions" && <AdminSuggestions />}

      {activeTab === "users" && <AdminUsers />}
    </div>
  );
}

function RatingPromptViewer() {
  const [prompt, setPrompt] = useState(null);
  useEffect(() => {
    axios.get(`${API}/api/prompts`).then(r => setPrompt(r.data?.rating)).catch(() => {});
  }, []);
  if (!prompt) return <div className="text-xs text-muted-foreground">Loading...</div>;
  return (
    <div className="space-y-2">
      <div><Label className="text-xs">System Prompt</Label><pre className="text-[10px] font-mono bg-secondary/30 rounded p-2 whitespace-pre-wrap max-h-40 overflow-y-auto">{prompt.system_prompt}</pre></div>
      <div><Label className="text-xs">User Prompt Template</Label><pre className="text-[10px] font-mono bg-secondary/30 rounded p-2 whitespace-pre-wrap">{prompt.user_prompt}</pre></div>
    </div>
  );
}

function AdminSuggestions() {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchSuggestions = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/suggestions`, { headers: getAdminHeaders() });
      setSuggestions(res.data.suggestions || []);
    } catch (err) {
      console.error("Failed to load suggestions:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSuggestions(); }, []);

  const updateStatus = async (id, status) => {
    try {
      await axios.post(`${API}/api/admin/suggestions/${id}/status`, { status }, { headers: getAdminHeaders() });
      toast.success(`Marked as ${status}`);
      fetchSuggestions();
    } catch { toast.error("Failed"); }
  };

  if (loading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/30 rounded-lg animate-pulse" />)}</div>;

  return (
    <div className="space-y-4" data-testid="admin-suggestions">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-lg font-medium">User Suggestions & Feedback</h2>
        <span className="text-xs text-muted-foreground">{suggestions.length} total</span>
      </div>

      {suggestions.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground border border-border rounded-lg">
          <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No suggestions yet.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {suggestions.map(s => (
            <div key={s.suggestion_id} className={`p-4 border rounded-lg ${s.status === "reviewed" ? "border-border/50 bg-secondary/10" : "border-border bg-background"}`} data-testid={`suggestion-${s.suggestion_id}`}>
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${s.type === "field" ? "bg-accent/10 text-accent" : "bg-secondary text-muted-foreground"}`}>
                    {s.type === "field" ? "Field Suggestion" : "Feedback"}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.status === "pending" ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                    {s.status}
                  </span>
                </div>
                {s.status === "pending" && (
                  <Button variant="outline" size="sm" className="h-6 text-[10px]" onClick={() => updateStatus(s.suggestion_id, "reviewed")}>
                    Mark reviewed
                  </Button>
                )}
              </div>
              <p className="text-sm mb-2">{s.text}</p>
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                <span>{s.user_name || s.user_email}</span>
                <span>{new Date(s.created_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchUsers = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/users`, { headers: getAdminHeaders() });
      setUsers(res.data.users || []);
    } catch (err) {
      console.error("Failed to load users:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []);

  const toggleActive = async (userId, currentlyActive) => {
    try {
      await axios.post(`${API}/api/admin/users/${userId}/status`, { active: !currentlyActive }, { headers: getAdminHeaders() });
      toast.success(currentlyActive ? "User deactivated" : "User reactivated");
      fetchUsers();
    } catch { toast.error("Failed"); }
  };

  const getUserStatus = (u) => {
    if (u.active === false) return { label: "Deactivated", cls: "bg-red-50 text-red-700" };
    if (u.email_verified) return { label: "Verified", cls: "bg-green-50 text-green-700" };
    return { label: "Unverified", cls: "bg-amber-50 text-amber-700" };
  };

  if (loading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-secondary/30 rounded-lg animate-pulse" />)}</div>;

  return (
    <div className="space-y-4" data-testid="admin-users">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-lg font-medium">Registered Users</h2>
        <span className="text-xs text-muted-foreground">{users.length} total</span>
      </div>

      {users.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground border border-border rounded-lg">
          <Users className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No registered users yet.</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="grid grid-cols-[1fr_10rem_5rem_5.5rem_6rem_5rem] gap-2 px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border">
            <div>Email</div>
            <div>Name</div>
            <div>Provider</div>
            <div>Status</div>
            <div>Registered</div>
            <div className="text-right">Action</div>
          </div>
          {users.map(u => {
            const status = getUserStatus(u);
            const isActive = u.active !== false;
            return (
              <div key={u.user_id} className={`grid grid-cols-[1fr_10rem_5rem_5.5rem_6rem_5rem] gap-2 px-4 py-2.5 border-b border-border/50 text-sm items-center ${!isActive ? "opacity-50" : ""}`} data-testid={`user-row-${u.user_id}`}>
                <div className="truncate text-xs">{u.email}</div>
                <div className="truncate text-xs text-muted-foreground">{u.name || "\u2014"}</div>
                <div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${u.provider === "google" ? "bg-blue-50 text-blue-700" : "bg-secondary text-muted-foreground"}`}>
                    {u.provider}
                  </span>
                </div>
                <div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${status.cls}`}>
                    {status.label}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground font-mono">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : "\u2014"}
                </div>
                <div className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className={`h-6 text-[10px] px-2 ${isActive ? "text-red-600 hover:text-red-700 hover:bg-red-50" : "text-green-600 hover:text-green-700 hover:bg-green-50"}`}
                    onClick={() => toggleActive(u.user_id, isActive)}
                    data-testid={`user-toggle-${u.user_id}`}
                  >
                    {isActive ? "Deactivate" : "Reactivate"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


