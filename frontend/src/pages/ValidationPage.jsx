import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import {
  FlaskConical, TrendingUp, TrendingDown, Minus, AlertCircle,
  Users, ChevronDown, ChevronRight, BarChart3, GitCompare,
  RotateCcw, Play, Layers,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
function getAdminHeaders() { return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" }; }

// ─── Shared Components ───────────────────────────────────────────────────────

function CorrelationBadge({ value, label }) {
  const abs = Math.abs(value);
  const color = abs >= 0.7 ? "text-green-700" : abs >= 0.4 ? "text-amber-700" : abs >= 0.2 ? "text-orange-700" : "text-muted-foreground";
  const bg = abs >= 0.7 ? "bg-green-50" : abs >= 0.4 ? "bg-amber-50" : abs >= 0.2 ? "bg-orange-50" : "bg-secondary/50";
  return (
    <div className={`p-3 rounded-lg border border-border ${bg}`}>
      <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-xl font-semibold font-mono ${color}`}>{value >= 0 ? "+" : ""}{value.toFixed(3)}</div>
    </div>
  );
}

function RankDelta({ delta }) {
  if (delta === 0) return <span className="text-muted-foreground flex items-center gap-0.5"><Minus className="h-3 w-3" /> 0</span>;
  if (delta > 0) return <span className="text-red-600 flex items-center gap-0.5"><TrendingDown className="h-3 w-3" /> +{delta.toFixed(0)}</span>;
  return <span className="text-green-600 flex items-center gap-0.5"><TrendingUp className="h-3 w-3" /> {delta.toFixed(0)}</span>;
}

function RankingTable({ rows, mode }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? rows : rows.slice(0, 10);
  const isPw = mode === "pairwise";
  return (
    <div className="border border-border/50 rounded overflow-hidden">
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b border-border text-[10px]">
              <th className="text-left px-2 py-1.5 font-medium">Paper</th>
              <th className="text-right px-1.5 py-1.5 font-medium">{isPw ? "H Rank" : "IRT"}</th>
              <th className="text-right px-1.5 py-1.5 font-medium">AI</th>
              <th className="text-right px-1.5 py-1.5 font-medium">&Delta;</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(r => (
              <tr key={r.id} className="border-b border-border/20 hover:bg-secondary/10">
                <td className="px-2 py-1 max-w-[200px] truncate" title={r.title}>{r.title}</td>
                <td className="text-right px-1.5 py-1 font-mono">{isPw ? r.human_rank : r.irt_rank}</td>
                <td className="text-right px-1.5 py-1 font-mono">{r.ai_rank}</td>
                <td className="text-right px-1.5 py-1"><RankDelta delta={r.rank_delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 10 && (
        <button onClick={() => setShowAll(!showAll)} className="w-full py-1.5 text-[10px] text-muted-foreground hover:bg-secondary/20 border-t border-border/50">
          {showAll ? "Show less" : `Show all ${rows.length} papers`}
        </button>
      )}
    </div>
  );
}

function ProgressBar({ status }) {
  if (!status?.tournament_running) return null;
  const { completed_matches, total_matches } = status.tournament_progress || {};
  return (
    <div className="border border-accent/30 rounded p-3 bg-accent/5">
      <div className="flex items-center gap-2 mb-1">
        <div className="h-3 w-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        <span className="text-xs font-medium">Tournament in progress — {completed_matches}/{total_matches}</span>
      </div>
      <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className="h-full bg-accent transition-all" style={{ width: `${(completed_matches / Math.max(total_matches, 1)) * 100}%` }} />
      </div>
    </div>
  );
}

function shortModel(mk) {
  if (!mk) return "?";
  const m = mk.split(":")[1] || mk;
  if (m.includes("gpt-5")) return "GPT-5.2";
  if (m.includes("claude-opus")) return "Claude Opus";
  if (m.includes("gemini-3")) return "Gemini 3 Pro";
  return m.split("-").slice(0, 2).join("-");
}

// ─── Standard Stats (Pairwise + IRT + Agreement) ────────────────────────────

function StandardStats({ datasetId, isAdmin }) {
  const [status, setStatus] = useState(null);
  const [contentMode, setContentMode] = useState("abstract");
  const [modeData, setModeData] = useState({});  // { mode: { pairwise, irt, agreement } }
  const [isRunningTournament, setIsRunningTournament] = useState(false);

  const MODES = [
    { id: "abstract", label: "Abstract" },
    { id: "extract", label: "Extract" },
    { id: "full_pdf", label: "Full PDF" },
    { id: "ai_summary", label: "AI Summary" },
  ];

  const fetchAll = useCallback(async () => {
    try {
      const params = { dataset_id: datasetId };
      const [s, ...modeResults] = await Promise.all([
        axios.get(`${API}/api/validation/status`, { params }),
        ...MODES.flatMap(m => [
          axios.get(`${API}/api/validation/pairwise-results`, { params: { ...params, content_mode: m.id } }).catch(() => ({ data: {} })),
          axios.get(`${API}/api/validation/irt-results`, { params: { ...params, content_mode: m.id } }).catch(() => ({ data: {} })),
          axios.get(`${API}/api/validation/agreement-analysis`, { params: { ...params, content_mode: m.id } }).catch(() => ({ data: {} })),
        ]),
      ]);
      setStatus(s.data);
      const newModeData = {};
      MODES.forEach((m, idx) => {
        const pw = modeResults[idx * 3];
        const ir = modeResults[idx * 3 + 1];
        const ag = modeResults[idx * 3 + 2];
        newModeData[m.id] = {
          pairwise: pw.data.status === "ok" ? pw.data : null,
          irt: ir.data.status === "ok" ? ir.data : null,
          agreement: ag.data.status === "ok" ? ag.data : null,
        };
      });
      setModeData(newModeData);
    } catch (e) { console.error(e); }
  }, [datasetId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    if (!status?.tournament_running && !isRunningTournament) return;
    const iv = setInterval(fetchAll, 5000);
    return () => clearInterval(iv);
  }, [status?.tournament_running, isRunningTournament, fetchAll]);

  const runTournament = async (mode) => {
    setIsRunningTournament(true);
    try {
      await axios.post(`${API}/api/validation/run-tournament`,
        { dataset_id: datasetId, num_matches: 500, parallel: 30, content_mode: mode },
        { headers: getAdminHeaders() });
      fetchAll();
    } catch (e) {
      console.error(e);
      setIsRunningTournament(false);
    }
  };

  const active = modeData[contentMode] || {};
  const activePairwise = active.pairwise;
  const activeIrt = active.irt;
  const activeAgreement = active.agreement;
  const hasActiveData = activePairwise || activeIrt;
  const modeLabels = { extract: "Extract", abstract: "Abstract", full_pdf: "Full PDF", ai_summary: "AI Summary" };
  const modeLabel = modeLabels[contentMode] || contentMode;
  // Only show modes in toggle that have data or are the standard 3
  const visibleModes = MODES.filter(m => m.id !== "ai_summary" || modeData[m.id]?.pairwise || modeData[m.id]?.irt);

  return (
    <div className="space-y-5">
      {/* Status row */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-center">
          {[
            ["Papers", status.papers_imported, `${status.papers_with_full_text} full text`],
            ["AI Matches", status.matches_completed, `${status.coverage_pct}% coverage`],
            ["Extraction", status.matches_with_extraction, `${status.matches_abstract_only} abstract-only`],
            ["Avg/Paper", status.avg_matches_per_paper, `${status.min_matches_per_paper}–${status.max_matches_per_paper}`],
            ["Tournament", status.tournament_running ? "Running" : "Complete", status.tournament_running ? `${status.tournament_progress.completed_matches}/${status.tournament_progress.total_matches}` : ""],
          ].map(([label, val, sub], i) => (
            <div key={i} className="p-2 border border-border/50 rounded text-xs">
              <div className="text-muted-foreground">{label}</div>
              <div className={`font-semibold ${val === "Running" ? "text-accent" : ""}`}>{val}</div>
              {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
            </div>
          ))}
        </div>
      )}

      <ProgressBar status={status} />

      {/* Content mode toggle */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="content-mode-toggle">
          {visibleModes.map(m => (
            <button
              key={m.id}
              onClick={() => setContentMode(m.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                contentMode === m.id
                  ? "bg-accent/10 text-accent"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              data-testid={`mode-${m.id}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && !hasActiveData && contentMode !== "extract" && !status?.tournament_running && (
            <Button size="sm" className="gap-1.5 text-xs" onClick={() => runTournament(contentMode)} disabled={isRunningTournament} data-testid={`run-${contentMode}-btn`}>
              <Play className="h-3 w-3" /> Run {modeLabel} Tournament
            </Button>
          )}
          {!hasActiveData && (
            <span className="text-xs text-muted-foreground italic">No {modeLabel.toLowerCase()} tournament data yet.</span>
          )}
        </div>
      </div>

      {/* Agreement */}
      {activeAgreement && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {[
            ["Expert-Expert", activeAgreement.expert_expert.rate, `${activeAgreement.expert_expert.agree}/${activeAgreement.expert_expert.total}`, activeAgreement.expert_expert.rate >= 70 ? "text-green-600" : "text-red-600"],
            ["AI vs Expert", activeAgreement.ai_expert.rate, `${activeAgreement.ai_expert.agree}/${activeAgreement.ai_expert.total}`, activeAgreement.ai_expert.rate > activeAgreement.expert_expert.rate ? "text-green-600" : "text-amber-600"],
            ["AI vs Expert Majority", activeAgreement.ai_majority.rate, `${activeAgreement.ai_majority.agree}/${activeAgreement.ai_majority.total}`, "text-amber-600"],
          ].map(([label, rate, sub, color], i) => (
            <div key={i} className="p-3 border border-border rounded text-center" data-testid={`agreement-${label.toLowerCase().replace(/[^a-z]/g, "-")}`}>
              <div className="text-[10px] text-muted-foreground">{label} ({modeLabel})</div>
              <div className={`text-xl font-semibold font-mono ${color}`}>{rate}%</div>
              <div className="text-[10px] text-muted-foreground">{sub} pairs</div>
            </div>
          ))}
        </div>
      )}

      {/* Note about non-comparable sets */}
      {activeAgreement && (
        <div className="text-[10px] text-muted-foreground bg-secondary/10 border border-border/50 rounded px-3 py-2 flex items-start gap-1.5" data-testid="non-comparable-note">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>Agreement rates above are based on different sets of matches per content mode and are not directly comparable across Extract, Abstract, and Full PDF. For a fair comparison on the same paper pairs, see the Pairwise section.</span>
        </div>
      )}

      {/* Two experiments side by side */}
      {(activePairwise || activeIrt) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {activePairwise && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium flex items-center gap-1.5">
                  <Users className="h-3 w-3" /> Pairwise BT — {modeLabel}
                </h3>
              </div>
              <div className="p-3 space-y-2">
                <div className="grid grid-cols-3 gap-2">
                  <CorrelationBadge value={activePairwise.correlation.spearman_rho} label="Spearman &rho;" />
                  <CorrelationBadge value={activePairwise.correlation.kendall_tau} label="Kendall &tau;" />
                  <CorrelationBadge value={activePairwise.correlation.pearson_r} label="Pearson r" />
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {activePairwise.papers_analyzed} papers &middot; {activePairwise.human_matches_derived} human pairs &middot; {activePairwise.ai_matches} AI matches
                </div>
                <RankingTable rows={activePairwise.comparison} mode="pairwise" />
              </div>
            </div>
          )}
          {activeIrt && (
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-secondary/10 border-b border-border">
                <h3 className="text-xs font-medium flex items-center gap-1.5">
                  <FlaskConical className="h-3 w-3" /> IRT Score — {modeLabel}
                </h3>
              </div>
              <div className="p-3 space-y-2">
                <div className="grid grid-cols-3 gap-2">
                  <CorrelationBadge value={activeIrt.correlation.irt_score_vs_ai.spearman_rho} label="Spearman &rho;" />
                  <CorrelationBadge value={activeIrt.correlation.irt_score_vs_ai.kendall_tau} label="Kendall &tau;" />
                  <CorrelationBadge value={activeIrt.correlation.irt_score_vs_ai.pearson_r} label="Pearson r" />
                </div>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span>{activeIrt.improvement.distinct_scores_raw}&rarr;{activeIrt.improvement.distinct_scores_irt} distinct scores</span>
                  <span>&middot;</span>
                  <span>&Delta;&rho; = {activeIrt.improvement.delta >= 0 ? "+" : ""}{activeIrt.improvement.delta.toFixed(3)}</span>
                </div>
                <RankingTable rows={activeIrt.comparison} mode="irt" />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Multi-Model Stats ──────────────────────────────────────────────────────

function MultiModelStats({ datasetId, isAdmin }) {
  const [contentMode, setContentMode] = useState(null);
  const [dataByMode, setDataByMode] = useState({});
  const [loading, setLoading] = useState(true);

  const MODES = [
    { id: "abstract", label: "Abstract" },
    { id: "extract", label: "Extract" },
    { id: "full_pdf", label: "Full PDF" },
  ];
  const modeLabels = { extract: "Extract", abstract: "Abstract", full_pdf: "Full PDF" };

  const fetchData = useCallback(async () => {
    try {
      const [ext, abs, pdf] = await Promise.all([
        axios.get(`${API}/api/validation/multimodel-results`, { params: { dataset_id: datasetId, content_mode: "extract" } }).catch(() => ({ data: {} })),
        axios.get(`${API}/api/validation/multimodel-results`, { params: { dataset_id: datasetId, content_mode: "abstract" } }).catch(() => ({ data: {} })),
        axios.get(`${API}/api/validation/multimodel-results`, { params: { dataset_id: datasetId, content_mode: "full_pdf" } }).catch(() => ({ data: {} })),
      ]);
      const result = {};
      if (ext.data.status === "ok") result.extract = ext.data;
      if (abs.data.status === "ok") result.abstract = abs.data;
      if (pdf.data.status === "ok") result.full_pdf = pdf.data;
      setDataByMode(result);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [datasetId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-select the first mode that has data
  useEffect(() => {
    if (loading) return;
    const available = MODES.map(m => m.id).filter(id => dataByMode[id]);
    if (available.length > 0 && (!contentMode || !dataByMode[contentMode])) {
      setContentMode(available[0]);
    } else if (available.length === 0 && !contentMode) {
      setContentMode("extract");
    }
  }, [dataByMode, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const runMultiModel = async () => {
    try {
      await axios.post(`${API}/api/validation/run-multimodel`,
        { dataset_id: datasetId, parallel: 40 },
        { headers: getAdminHeaders() });
    } catch (e) { console.error(e); }
  };

  const data = dataByMode[contentMode] || null;
  const hasAnyData = Object.keys(dataByMode).length > 0;
  const availableModes = MODES.filter(m => dataByMode[m.id]);

  if (loading) return <div className="text-xs text-muted-foreground py-4 text-center">Loading multi-model data...</div>;

  if (!hasAnyData) {
    return (
      <div className="border border-border rounded-lg p-6 text-center space-y-3">
        <Layers className="h-6 w-6 mx-auto text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">No multi-model data yet.</p>
        {isAdmin && (
          <Button size="sm" onClick={runMultiModel} className="gap-1.5" data-testid="run-multimodel-btn">
            <Play className="h-3.5 w-3.5" /> Run Multi-Model Tournament
          </Button>
        )}
      </div>
    );
  }

  const models = data?.models || [];

  return (
    <div className="space-y-5">
      {/* Content mode toggle — only show modes that have data */}
      {availableModes.length > 1 && (
        <div className="flex items-center gap-2">
          <div className="flex gap-1 border border-border rounded-lg p-0.5" data-testid="multimodel-content-mode-toggle">
            {availableModes.map(m => (
              <button
                key={m.id}
                onClick={() => setContentMode(m.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                  contentMode === m.id
                    ? "bg-accent/10 text-accent"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                data-testid={`multimodel-mode-${m.id}`}
              >
                {m.label}
                <span className="ml-1 text-[9px] opacity-50">({dataByMode[m.id].pairs_with_all_models})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {data && (
        <>
          <div className="text-xs text-muted-foreground">
            <strong>{data.pairs_with_all_models}</strong> pairs with all {models.length} model verdicts{availableModes.length <= 1 ? ` (${modeLabels[contentMode] || "Extract"})` : ""}
          </div>

      {/* Inter-model pairwise agreement */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <GitCompare className="h-3 w-3" /> Inter-Model Pairwise Agreement
          </h3>
        </div>
        <div className="p-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
          {Object.entries(data.inter_model_agreement || {}).map(([key, val]) => {
            const [m1, m2] = key.split(" vs ");
            return (
              <div key={key} className="p-3 border border-border rounded text-center" data-testid={`model-agree-${key.replace(/\s/g, "-")}`}>
                <div className="text-[10px] text-muted-foreground mb-1">{shortModel(m1)} vs {shortModel(m2)}</div>
                <div className={`text-lg font-semibold font-mono ${val.rate >= 70 ? "text-green-600" : val.rate >= 55 ? "text-amber-600" : "text-red-600"}`}>{val.rate}%</div>
                <div className="text-[10px] text-muted-foreground">{val.agree}/{val.total} pairs</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Inter-model rank correlation */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <BarChart3 className="h-3 w-3" /> Inter-Model Rank Correlation (BT)
          </h3>
        </div>
        <div className="p-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
          {Object.entries(data.inter_model_correlation || {}).map(([key, val]) => {
            const [m1, m2] = key.split(" vs ");
            return (
              <div key={key} className="p-3 border border-border rounded text-center">
                <div className="text-[10px] text-muted-foreground mb-1">{shortModel(m1)} vs {shortModel(m2)}</div>
                <CorrelationBadge value={val.spearman_rho} label={`Spearman \u03C1 (${val.papers} papers)`} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Majority vote vs expert majority */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-3 py-2 bg-secondary/10 border-b border-border">
          <h3 className="text-xs font-medium flex items-center gap-1.5">
            <Users className="h-3 w-3" /> Majority Vote vs Expert
          </h3>
        </div>
        <div className="p-3 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {/* Per-model vs expert majority */}
            {Object.entries(data.per_model_vs_expert_majority || {}).map(([mk, val]) => (
              <div key={mk} className="p-3 border border-border rounded text-center">
                <div className="text-[10px] text-muted-foreground mb-1">{shortModel(mk)} vs Experts</div>
                <div className={`text-lg font-semibold font-mono ${val.rate >= 70 ? "text-green-600" : "text-amber-600"}`}>{val.rate}%</div>
                <div className="text-[10px] text-muted-foreground">{val.agree}/{val.total}</div>
              </div>
            ))}
            {/* Majority vs expert */}
            <div className="p-3 border-2 border-accent/50 rounded text-center bg-accent/5" data-testid="majority-vs-expert">
              <div className="text-[10px] text-muted-foreground mb-1 font-medium">Majority Vote vs Experts</div>
              <div className={`text-lg font-semibold font-mono ${data.majority_vs_expert_majority.rate >= 70 ? "text-green-600" : "text-amber-600"}`}>
                {data.majority_vs_expert_majority.rate}%
              </div>
              <div className="text-[10px] text-muted-foreground">{data.majority_vs_expert_majority.agree}/{data.majority_vs_expert_majority.total}</div>
            </div>
          </div>

          {/* Majority BT vs Human BT correlation */}
          {data.majority_bt_vs_human_bt && (
            <div className="pt-2 border-t border-border/50">
              <div className="text-[10px] text-muted-foreground mb-2">Majority-Vote BT Ranking vs Human BT Ranking</div>
              <div className="inline-block">
                <CorrelationBadge value={data.majority_bt_vs_human_bt.spearman_rho} label={`Spearman \u03C1 (${data.majority_bt_vs_human_bt.papers} papers)`} />
              </div>
            </div>
          )}
        </div>
      </div>
        </>
      )}
    </div>
  );
}

// ─── Dataset Detail View ────────────────────────────────────────────────────

export function DatasetView({ ds, isAdmin, hideHeader = false }) {
  const [tab, setTab] = useState("standard");
  const hasMultiModel = true; // all datasets can have multi-model data

  const tabs = [
    { id: "standard", label: "Ranking Correlation", icon: BarChart3 },
    ...(hasMultiModel ? [{ id: "multimodel", label: "Multi-Model Analysis", icon: Layers }] : []),
  ];

  return (
    <div className="space-y-4">
      {!hideHeader && (
        <div>
          <h2 className="font-heading text-lg font-semibold" data-testid="dataset-title">{ds.name}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">{ds.description || ds.source}</p>
        </div>
      )}

      {tabs.length > 1 && (
        <div className="flex gap-1 border-b border-border">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-xs font-medium flex items-center gap-1.5 border-b-2 transition-colors ${
                tab === t.id ? "border-accent text-accent" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              data-testid={`tab-${t.id}`}
            >
              <t.icon className="h-3 w-3" /> {t.label}
            </button>
          ))}
        </div>
      )}

      {tab === "standard" && <StandardStats datasetId={ds.dataset_id} isAdmin={isAdmin} />}
      {tab === "multimodel" && <MultiModelStats datasetId={ds.dataset_id} isAdmin={isAdmin} />}
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function ValidationPage() {
  const [datasets, setDatasets] = useState([]);
  const [selected, setSelected] = useState(null);
  const initializedRef = useRef(false);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchDatasets = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/datasets`);
      const ds = r.data.datasets || [];
      setDatasets(ds);
      if (!initializedRef.current && ds.length) {
        setSelected(ds[0].dataset_id);
        initializedRef.current = true;
      }
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchDatasets(); const i = setInterval(fetchDatasets, 15000); return () => clearInterval(i); }, [fetchDatasets]);

  const activeDatasset = datasets.find(d => d.dataset_id === selected);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-6xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <FlaskConical className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="validation-title">Human vs AI Validation</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Does PaperSumo's AI tournament agree with human peer reviewers? Each dataset imports real papers with
          reviewer scores, runs an independent AI tournament, and measures rank correlation.
        </p>
      </div>

      {datasets.length === 0 ? (
        <div className="border border-border rounded-lg p-8 text-center">
          <AlertCircle className="h-8 w-8 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">No validation datasets yet.</p>
        </div>
      ) : (
        <div className="flex gap-5">
          {/* Sidebar */}
          <nav className="w-56 shrink-0 space-y-1" data-testid="dataset-nav">
            {datasets.map(ds => (
              <button
                key={ds.dataset_id}
                onClick={() => setSelected(ds.dataset_id)}
                className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  selected === ds.dataset_id
                    ? "bg-accent/10 text-accent font-medium border border-accent/20"
                    : "text-muted-foreground hover:bg-secondary/30 hover:text-foreground border border-transparent"
                }`}
                data-testid={`nav-${ds.dataset_id}`}
              >
                <div className="font-medium text-xs">{ds.name}</div>
                <div className="text-[10px] mt-0.5 opacity-70">
                  {ds.papers} papers &middot; {ds.matches} matches
                </div>
              </button>
            ))}

            {isAdmin && (
              <div className="pt-3 mt-3 border-t border-border">
                <Button size="sm" variant="ghost" className="w-full text-xs gap-1" onClick={fetchDatasets}>
                  <RotateCcw className="h-3 w-3" /> Refresh
                </Button>
              </div>
            )}
          </nav>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            {activeDatasset ? (
              <DatasetView ds={activeDatasset} isAdmin={isAdmin} />
            ) : (
              <div className="text-sm text-muted-foreground p-4">Select a dataset from the sidebar.</div>
            )}
          </div>
        </div>
      )}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 mt-8 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Methodology</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><strong>Data:</strong> Papers with peer reviews from ICLR OpenReview, PeerRead (ACL 2017), and F1000Research (biomedical). Full text used for section extraction where available.</li>
          <li><strong>Pairwise BT:</strong> Derives head-to-head matches from reviewers who scored multiple papers. Both sides ranked via Bradley-Terry. Implicitly cancels severity bias.</li>
          <li><strong>IRT Score:</strong> Z-scores each reviewer's ratings against their personal mean/std, averages per paper. Explicitly removes severity bias. Produces finer-grained scores.</li>
          <li><strong>Multi-Model:</strong> Each pair is evaluated by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro. Inter-model agreement and majority-vote accuracy are computed.</li>
          <li><strong>Agreement:</strong> Expert-Expert = reviewer pairwise agreement rate. AI-Expert = AI vs individual reviewer. AI-Majority = AI vs reviewer consensus.</li>
        </ul>
      </div>
    </div>
  );
}
