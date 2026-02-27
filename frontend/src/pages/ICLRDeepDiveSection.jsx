import { useState, useEffect } from "react";
import axios from "axios";
import { RefreshCw, ChevronDown, ChevronUp, FlaskConical, Sparkles } from "lucide-react";
import { ValidationConvergence } from "@/components/ConvergenceSection";

const API = process.env.REACT_APP_BACKEND_URL;

const STEP_LABELS = {
  step2: "First-pass assessments",
  step3: "Deep-dive assessments",
  step4: "Tournament replay",
};

export default function ICLRDeepDiveSection({ datasetId = "iclr-codegen", label = "ICLR Code Generation" }) {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");
  const [expandedPaper, setExpandedPaper] = useState(null);

  const fetchAll = () => {
    Promise.all([
      axios.get(`${API}/api/validation/deep-dive-pipeline/status?dataset_id=${datasetId}`).then(r => setStatus(r.data)).catch(() => {}),
      axios.get(`${API}/api/validation/deep-dive-pipeline/results?dataset_id=${datasetId}`).then(r => setResults(r.data)).catch(() => {}),
    ]).then(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, [datasetId]);

  const isRunning = status?.running;
  useEffect(() => {
    if (!isRunning) return;
    const iv = setInterval(fetchAll, 8000);
    return () => clearInterval(iv);
  }, [isRunning]);

  if (loading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;

  const papers = results?.papers || [];
  const analysis = results?.analysis;
  const step2Done = results?.step2_done || 0;
  const step3Done = results?.step3_done || 0;
  const replayCount = results?.replay_count || 0;
  const totalPapers = results?.total_papers || 0;

  return (
    <div className="space-y-6" data-testid="iclr-deep-dive">
      {/* Pipeline progress */}
      {isRunning && (
        <div className="flex items-center gap-3 p-3 bg-violet-50 border border-violet-200 rounded-lg">
          <RefreshCw className="h-4 w-4 animate-spin text-violet-600" />
          <div>
            <span className="text-sm text-violet-900 font-medium">
              {STEP_LABELS[status.step] || status.step}... {status.done}/{status.total}
            </span>
            {status.errors > 0 && <span className="text-xs text-red-600 ml-2">({status.errors} errors)</span>}
          </div>
        </div>
      )}

      {/* Step progress cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StepCard label="Papers" value={totalPapers} sub={label} />
        <StepCard
          label="Step 1: First Pass"
          value={`${step2Done}/${totalPapers}`}
          sub={step2Done === totalPapers ? "Complete" : isRunning && status?.step === "step2" ? "In progress..." : "Pending"}
          active={isRunning && status?.step === "step2"}
          done={step2Done === totalPapers}
        />
        <StepCard
          label="Step 2: Deep Dive"
          value={`${step3Done}/${totalPapers}`}
          sub={step3Done === totalPapers ? "Complete" : isRunning && status?.step === "step3" ? "In progress..." : "Pending"}
          active={isRunning && status?.step === "step3"}
          done={step3Done === totalPapers}
        />
        <StepCard
          label="Step 3: Replay"
          value={replayCount}
          sub={isRunning && status?.step === "step4" ? `${status.done}/${status.total} matches` : replayCount > 0 ? "Matches replayed" : "Pending"}
          active={isRunning && status?.step === "step4"}
          done={status?.finished && replayCount > 0}
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border border-border rounded-lg p-0.5 w-fit">
        {[["overview", "Overview"], ["papers", `Papers (${totalPapers})`], ["analysis", "Analysis"]].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${tab === id ? "bg-accent/10 text-accent" : "text-muted-foreground hover:text-foreground"}`}>
            {label}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === "overview" && (
        <div className="space-y-4">
          <div className="border border-border rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-2">Experiment Design</h3>
            <div className="text-xs text-muted-foreground space-y-1.5">
              <p><strong>Dataset:</strong> {label} ({totalPapers} papers)</p>
              <p><strong>Step 1:</strong> Generate first-pass assessment + identify focus areas for each paper</p>
              <p><strong>Step 2:</strong> Generate deep-dive assessment informed by focus areas (standalone, same style as original)</p>
              <p><strong>Step 3:</strong> Replay all existing pairwise matches using deep-dive assessments instead of originals</p>
              <p><strong>Metrics:</strong> Human agreement (ICLR accept/reject tiers), flip rate, paper-level Wilcoxon test, permutation test</p>
            </div>
          </div>

          {/* Analysis results */}
          {analysis && <AnalysisView analysis={analysis} />}

          {!analysis && !isRunning && replayCount === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              <FlaskConical className="h-8 w-8 mx-auto mb-3 opacity-30" />
              <p className="text-sm">No results yet.</p>
            </div>
          )}
        </div>
      )}

      {/* Papers tab */}
      {tab === "papers" && (
        <div className="space-y-2">
          {papers.map((p, i) => {
            const isExpanded = expandedPaper === i;
            return (
              <div key={i} className="border border-border rounded-lg">
                <div className="p-3 text-xs cursor-pointer flex items-start justify-between gap-2" onClick={() => setExpandedPaper(isExpanded ? null : i)}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                      {p.step2_assessment && <span className="text-[10px] px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">FIRST PASS</span>}
                      {p.step3_assessment && <span className="text-[10px] px-1.5 py-0.5 bg-violet-100 text-violet-700 rounded flex items-center gap-0.5"><Sparkles className="h-2.5 w-2.5" />DEEP DIVE</span>}
                      {p.focus_areas?.length > 0 && <span className="text-[10px] text-muted-foreground">{p.focus_areas.length} focus areas</span>}
                    </div>
                    <p className="font-medium text-foreground">{p.title}</p>
                  </div>
                  {(p.step2_assessment || p.step3_assessment) && (
                    isExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" /> : <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                  )}
                </div>
                {isExpanded && (
                  <ExpandedPaper paper={p} />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Analysis tab */}
      {tab === "analysis" && analysis && <AnalysisView analysis={analysis} />}
      {tab === "analysis" && !analysis && (
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-sm">Analysis will appear once the tournament replay completes.</p>
        </div>
      )}
    </div>
  );
}


function ExpandedPaper({ paper }) {
  const [viewTab, setViewTab] = useState(paper.step3_assessment ? "deepdive" : "firstpass");

  return (
    <div className="border-t border-border/50 p-3 space-y-2">
      {paper.focus_areas?.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {paper.focus_areas.map((a, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 bg-amber-50 border border-amber-200 rounded text-amber-900">{a}</span>
          ))}
        </div>
      )}
      <div className="flex gap-1 border border-border rounded-lg p-0.5 w-fit">
        {paper.step2_assessment && (
          <button onClick={() => setViewTab("firstpass")}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${viewTab === "firstpass" ? "bg-blue-100 text-blue-800" : "text-muted-foreground"}`}>
            First Pass
          </button>
        )}
        {paper.step3_assessment && (
          <button onClick={() => setViewTab("deepdive")}
            className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${viewTab === "deepdive" ? "bg-violet-100 text-violet-800" : "text-muted-foreground"}`}>
            Deep Dive
          </button>
        )}
      </div>
      <div className="text-xs leading-relaxed text-foreground/90 max-h-80 overflow-y-auto whitespace-pre-wrap">
        <FormattedText text={viewTab === "deepdive" ? paper.step3_assessment : paper.step2_assessment} />
      </div>
    </div>
  );
}


function AnalysisView({ analysis }) {
  const ha = analysis.human_agreement || {};
  const fd = analysis.flip_direction || {};
  const pl = analysis.paper_level || {};
  const da = analysis.dimension_agreement || {};

  return (
    <div className="space-y-4">
      {/* Headline */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Matches Replayed" value={analysis.total_replays} />
        <StatCard label="Verdict Flip Rate" value={`${analysis.flip_rate}%`} sub={`${analysis.flipped} flipped`} />
        <StatCard
          label="Human Agreement (Original)"
          value={`${ha.original || 0}%`}
          sub={`${ha.pairs_with_gt || 0} pairs with ground truth`}
        />
        <StatCard
          label="Human Agreement (Deep Dive)"
          value={`${ha.deep_dive || 0}%`}
          sub={`${ha.lift > 0 ? "+" : ""}${ha.lift || 0}pp lift`}
          accent={ha.lift > 0}
        />
      </div>

      {/* Flip direction */}
      {(fd.toward_human > 0 || fd.away_from_human > 0) && (
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-2">When Verdicts Flip...</h3>
          <div className="flex gap-8 text-xs">
            <div><span className="text-green-600 font-bold text-lg">{fd.toward_human}</span> <span className="text-muted-foreground">toward human judgment</span></div>
            <div><span className="text-red-500 font-bold text-lg">{fd.away_from_human}</span> <span className="text-muted-foreground">away from human judgment</span></div>
            <div><span className="font-bold text-lg">{fd.net > 0 ? "+" : ""}{fd.net}</span> <span className="text-muted-foreground">net</span></div>
          </div>
        </div>
      )}

      {/* Per-dimension agreement (ACMI-style) */}
      {da && Object.keys(da).length > 1 && (
        <div className="border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Agreement by Rating Dimension</h3>
          <div className="text-xs space-y-2">
            <div className="flex items-center gap-3 text-muted-foreground font-medium">
              <span className="w-28">Dimension</span><span className="w-12 text-right">Pairs</span><span className="w-20 text-right">Original</span><span className="w-20 text-right">Deep Dive</span><span className="w-14 text-right">Lift</span>
            </div>
            {Object.entries(da).sort((a, b) => b[1].lift - a[1].lift).map(([dim, s]) => (
              <div key={dim} className="flex items-center gap-3">
                <span className="w-28 font-medium capitalize">{dim}</span>
                <span className="w-12 text-right font-mono text-muted-foreground">{s.pairs}</span>
                <span className="w-20 text-right font-mono">{s.original_agreement}%</span>
                <span className="w-20 text-right font-mono font-medium">{s.deep_dive_agreement}%</span>
                <span className={`w-14 text-right font-mono font-bold ${s.lift > 0 ? "text-green-600" : s.lift < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                  {s.lift > 0 ? "+" : ""}{s.lift}pp
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Paper-level tests */}
      {pl.n_papers > 0 && (
        <div className="border-2 border-violet-200 rounded-lg p-4 bg-violet-50/30">
          <h3 className="text-sm font-semibold mb-1">Paper-Level Analysis (N={pl.n_papers})</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Unit of analysis = paper. Compares original vs deep-dive win rates.</p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <MiniCard label="Mean WR Shift" value={`${(pl.mean_wr_shift || 0) > 0 ? "+" : ""}${pl.mean_wr_shift ?? "—"}pp`} positive={pl.mean_wr_shift > 0} />
            <MiniCard label="Median WR Shift" value={`${(pl.median_wr_shift || 0) > 0 ? "+" : ""}${pl.median_wr_shift ?? "—"}pp`} />
            <MiniCard label="Shifted Up" value={pl.positive_shifts ?? 0} positive />
            <MiniCard label="Shifted Down" value={pl.negative_shifts ?? 0} negative />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
            {pl.wilcoxon && (
              <div className="bg-background border border-border rounded-lg p-3 text-xs space-y-1">
                <h4 className="font-semibold">Wilcoxon Signed-Rank</h4>
                {pl.wilcoxon.p_value != null ? (<>
                  <div className="flex justify-between"><span className="text-muted-foreground">W+ / W-</span><span className="font-mono">{pl.wilcoxon.w_plus} / {pl.wilcoxon.w_minus}</span></div>
                  <div className="flex justify-between font-medium">
                    <span>p = {pl.wilcoxon.p_value}</span>
                    <span className={pl.wilcoxon.significant ? "text-green-600" : "text-muted-foreground"}>{pl.wilcoxon.significant ? "Significant" : "Not significant"}</span>
                  </div>
                </>) : <p className="text-muted-foreground italic">{pl.wilcoxon.note || "Insufficient data"}</p>}
              </div>
            )}
            {pl.permutation_test && (
              <div className="bg-background border border-border rounded-lg p-3 text-xs space-y-1">
                <h4 className="font-semibold">Permutation Test (10k permutations)</h4>
                <div className="flex justify-between"><span className="text-muted-foreground">Observed mean</span><span className="font-mono">{pl.permutation_test.observed_mean}pp</span></div>
                <div className="flex justify-between font-medium">
                  <span>p = {pl.permutation_test.p_value}</span>
                  <span className={pl.permutation_test.significant ? "text-green-600" : "text-muted-foreground"}>{pl.permutation_test.significant ? "Significant" : "Not significant"}</span>
                </div>
              </div>
            )}
          </div>

          {/* Per-paper table */}
          {pl.paper_details?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-2">Per-Paper Win Rate (Original → Deep Dive)</h4>
              <div className="space-y-1 text-[11px] max-h-64 overflow-y-auto">
                {pl.paper_details.map((p, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className={`font-mono w-14 text-right font-medium ${p.diff > 0 ? "text-green-600" : p.diff < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                      {p.diff > 0 ? "+" : ""}{p.diff}pp
                    </span>
                    <span className="font-mono text-muted-foreground w-24">{p.orig_wr}% → {p.dd_wr}%</span>
                    <span className="font-mono text-muted-foreground w-10">n={p.matches}</span>
                    <span className={`text-[10px] px-1 rounded ${p.decision?.includes("Accept") || p.decision?.includes("accept") ? "bg-green-100 text-green-700" : p.decision?.includes("eject") ? "bg-red-100 text-red-600" : "bg-secondary/50 text-muted-foreground"}`}>
                      {p.decision || "?"}
                    </span>
                    <span className="truncate">{p.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function FormattedText({ text }) {
  if (!text) return null;
  return (
    <div className="space-y-1">
      {text.split("\n").map((line, i) => {
        if (line.match(/^#{1,3}\s/)) return <p key={i} className="font-semibold text-foreground mt-2">{line.replace(/^#+\s*/, "").replace(/\*\*/g, "")}</p>;
        if (line.match(/^\*\*.*\*\*$/)) return <p key={i} className="font-semibold text-foreground mt-2">{line.replace(/\*\*/g, "")}</p>;
        const html = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        return <p key={i} dangerouslySetInnerHTML={{ __html: html }} />;
      })}
    </div>
  );
}

function StepCard({ label, value, sub, active, done }) {
  return (
    <div className={`border rounded-lg p-3 ${active ? "border-violet-300 bg-violet-50/50" : done ? "border-green-300 bg-green-50/30" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground mb-0.5 flex items-center gap-1">
        {active && <RefreshCw className="h-3 w-3 animate-spin text-violet-500" />}
        {label}
      </p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function StatCard({ label, value, sub, accent }) {
  return (
    <div className={`border rounded-lg p-3 ${accent ? "border-green-300 bg-green-50/30" : "border-border"}`}>
      <p className="text-[10px] text-muted-foreground mb-0.5">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function MiniCard({ label, value, positive, negative }) {
  return (
    <div className="bg-background border border-border rounded-lg p-2.5 text-center">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={`text-lg font-bold font-mono ${positive ? "text-green-600" : negative ? "text-red-500" : ""}`}>{value}</p>
    </div>
  );
}
