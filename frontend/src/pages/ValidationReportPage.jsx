import { useState, useEffect } from "react";
import axios from "axios";
import { FileText, CheckCircle, XCircle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const GT_TYPE = {
  "iclr-codegen": "comparative", "iclr-llm": "comparative", "iclr-protein": "comparative",
  "iclr-fairness": "comparative", "iclr-pdes": "comparative", "iclr-molecules": "comparative",
  "iclr-optimization": "comparative", "elife-neuro-100": "comparative", "peerread_acl_2017": "comparative",
  "elife-cancer": "standalone", "elife-microbiology": "standalone", "elife-comp-sys-bio": "standalone",
  "midl-medical-imaging": "standalone", "qeios-social": "standalone", "researchhub-50": "standalone",
};

function Section({ num, title, children }) {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 bg-secondary/10 border-b border-border">
        <h3 className="text-sm font-semibold">{num}. {title}</h3>
      </div>
      <div className="px-4 py-3 text-xs text-muted-foreground space-y-2">{children}</div>
    </div>
  );
}

function Row({ label, value, bold }) {
  return (
    <div className="flex justify-between items-baseline border-b border-border/20 py-0.5">
      <span>{label}</span>
      <span className={`font-mono ${bold ? "font-bold text-foreground" : ""}`}>{value}</span>
    </div>
  );
}

export default function ValidationReportPage() {
  const [experiments, setExperiments] = useState(null);
  const [siData, setSiData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/api/validation/single-item-scoring/results`, { timeout: 30000 }).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/consistency-analysis`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/cycle-analysis-all`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/extended-thinking/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/multi-aspect/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/judge-comparison/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/summarizer-ab/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/model-correlation-analysis/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/institution-bias/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/institution-bias-samepair/results`).then(r => r.data).catch(() => null),
      axios.get(`${API}/api/validation/assessor-evaluator/results`).then(r => r.data).catch(() => null),
    ]).then(([si, consistency, cycles, thinking, multiAspect, judges, summarizer, correlation, bias, biasSP, ae]) => {
      setSiData(si);
      setExperiments({ consistency, cycles, thinking, multiAspect, judges, summarizer, correlation, bias, biasSP, ae });
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-12">Loading all experiment data...</div>;

  const ex = experiments || {};
  const ds = siData?.datasets || [];

  // Pre-extract key numbers
  const summ = ex.summarizer?.pooled || {};
  const thk = ex.thinking || {};
  const jc = ex.judges || {};
  const ma = ex.multiAspect || {};
  const cs = ex.consistency?.verdict_stability || {};
  const cy = ex.cycles?.pooled_all || {};
  const mc = ex.correlation?.pooled || [];
  const ib = ex.bias?.pooled || {};
  const ibsp = ex.biasSP?.pooled || {};
  const ae = ex.ae?.pooled || {};

  return (
    <div className="space-y-4" data-testid="validation-report-full">
      <div className="border border-border rounded-lg p-4">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-1">
          <FileText className="h-5 w-5" /> Complete Validation Report
        </h2>
        <p className="text-[11px] text-muted-foreground">
          All experiments and findings from PaperSumo's AI judge validation, condensed. Covers {ds.length} single-item datasets,
          {" "}{ex.summarizer?.pooled_datasets || "12+"} pairwise datasets, and 11 distinct experiments.
        </p>
      </div>

      {/* 1. Best Summarizer */}
      <Section num="1" title="Which Summarizer Model is Best?">
        <p>Abstract + AI summary fed to pairwise judges. Pooled accuracy across 12 datasets (1,521 common pairs):</p>
        <div className="space-y-0.5 mt-1">
          {["Opus 4.6 Thinking", "Opus 4.6", "Opus 4.5", "GPT-5.2", "Gemini 3 Pro"].map(name => {
            const v = summ[name] || {};
            return <Row key={name} label={name} value={`${v.accuracy || "?"}% acc, rho=${v.avg_rho || "?"}`} bold={name === "Opus 4.6 Thinking"} />;
          })}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Opus 4.6 Thinking is the best summarizer (82.3%), followed by Opus 4.6 (81.2%). Claude models dominate; GPT and Gemini trail by ~8-10pp. Upgrading from Opus 4.5 to 4.6 gives +5pp; adding extended thinking gives another +1pp.
        </p>
      </Section>

      {/* 2. Best Judge */}
      <Section num="2" title="Which Judge Model is Best?">
        <p>Same content shown to different judges. Accuracy on {jc.judges?.[0]?.total_pairs || "?"} shared pairs:</p>
        <div className="space-y-0.5 mt-1">
          {(jc.judges || []).sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0)).map((j, i) => (
            <Row key={i} label={j.label || j.name || "?"} value={`${j.accuracy}% (rho=${j.avg_rho?.toFixed(3) || "?"})`} bold={i === 0} />
          ))}
          {jc.round_robin && <Row label="Round-Robin (rotating)" value={`${jc.round_robin.accuracy}% (rho=${jc.round_robin.avg_rho?.toFixed(3) || "?"})`} />}
          {jc.majority_vote && <Row label="Majority Vote (3 judges)" value={`${jc.majority_vote.accuracy}% (rho=${jc.majority_vote.avg_rho?.toFixed(3) || "?"})`} />}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> All judge models perform within ~1.2pp of each other (72-75%). No clear winner. Majority vote and round-robin don't outperform the best single judge. The judge model matters far less than the summarizer model (+6pp between summarizers vs ~1pp between judges).
        </p>
      </Section>

      {/* 3. Summarizer x Judge Matrix */}
      <Section num="3" title="Summarizer x Judge: Best Combination?">
        <p>Full interaction matrix (pooled). Excluding Opus 4.6 non-thinking as summarizer. Top combos:</p>
        <div className="space-y-0.5 mt-1">
          {Object.entries(ae)
            .filter(([key]) => !key.startsWith("Opus 4.6|") || key.startsWith("Opus 4.6 Thinking"))
            .sort((a, b) => (b[1].accuracy || 0) - (a[1].accuracy || 0))
            .slice(0, 7)
            .map(([key, val]) => (
              <Row key={key} label={key} value={`${val.accuracy}% (${val.total} pairs)`} bold={key.includes("Thinking") && key.includes("GPT")} />
          ))}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Opus 4.6 Thinking + GPT-5.2 judge = 85% — the best combo. Cross-model diversity (Claude summarizer + GPT judge) outperforms same-model (Claude + Claude). Opus 4.5 summaries are ~5-7pp behind regardless of judge.
        </p>
      </Section>

      {/* 5. Input Format */}
      <Section num="4" title="Which Input Format Works Best?">
        <p>Verdict stability by format (lower flip rate = more consistent):</p>
        <div className="space-y-0.5 mt-1">
          {[
            { fmt: "AI Summary only", flip: "10.1%" },
            { fmt: "Abstract + Summary (Opus 4.6)", flip: "12.8%" },
            { fmt: "Deep Dive (2-pass)", flip: "14.4%" },
            { fmt: "Abstract + Summary (Opus 4.5)", flip: "14.3%" },
            { fmt: "Full PDF", flip: "16.8%" },
            { fmt: "Extract (scraped text)", flip: "18.2%" },
            { fmt: "Abstract only", flip: "18.6%" },
          ].map(r => <Row key={r.fmt} label={r.fmt} value={`flip rate ${r.flip}`} bold={r.fmt.includes("AI Summary")} />)}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> "Abstract + AI Summary" is the sweet spot — higher accuracy than abstract-only, more consistent than full PDF. Full PDF adds noise (irrelevant sections confuse the judge). AI summary condenses the paper into a judgment-friendly format.
        </p>
      </Section>

      {/* 6. Multi-Aspect */}
      <Section num="5" title="Does Multi-Aspect Judging Help?">
        <p>5-dimension scoring (novelty, rigor, applications, clarity, significance) vs holistic verdict:</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Holistic (standard)" value={`${ma.baseline?.rate || "?"}%`} bold />
          <Row label="Multi-aspect aggregate (majority of 5 dims)" value={`${ma.aggregate?.rate || "?"}%`} />
          <Row label="Lift" value={`${ma.lift || "?"}pp`} />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Multi-aspect is <em>worse</em> (-5.3pp). Breaking the judgment into sub-dimensions loses the holistic signal. The AI is better at making a single comparative judgment than aggregating 5 separate ones.
        </p>
      </Section>

      {/* 7. Consistency */}
      <Section num="6" title="How Consistent Are the Judgments?">
        <p>Same pair shown under different conditions — how often does the verdict flip?</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Cross-model flip rate (same format, different judge)" value="~14-16%" />
          <Row label="Cross-format flip rate (same judge, different input)" value="~13-18%" />
          <Row label="Most stable judge" value="Opus 4.6 (8.2% cross-format flips)" bold />
          <Row label="Least stable" value="GPT-5.2 (15.7% cross-format flips)" />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> ~15% of verdicts flip when conditions change. Opus 4.6 is the most consistent judge. Format changes cause as many flips as model changes — reinforcing that input quality is the primary variable.
        </p>
      </Section>

      {/* 8. Intransitive Cycles */}
      <Section num="7" title="How Often Do Intransitive Cycles Occur?">
        <p>A beats B, B beats C, C beats A — a violation of transitivity:</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Overall cycle rate" value={`${cy.rate || "?"}% of triples`} />
          <Row label="Close-rated papers" value={`${cy.by_gap?.close?.rate || "?"}%`} />
          <Row label="Far-rated papers" value={`${cy.by_gap?.far?.rate || "?"}%`} />
          <Row label="Most transitive judge" value="Opus 4.6 (0.88%)" bold />
          <Row label="Least transitive" value="GPT-5.2 (4.22%)" />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> 3.4% cycle rate overall — low but nonzero. Cycles are 2x more common for closely-rated papers (expected — harder to distinguish). Opus 4.6 is 5x more transitive than GPT-5.2.
        </p>
      </Section>

      {/* 9. Model Agreement */}
      <Section num="8" title="How Much Do Models Agree?">
        <p>Pairwise agreement rates on the same paper pairs:</p>
        <div className="space-y-0.5 mt-1">
          {(Array.isArray(mc) ? mc : []).slice(0, 6).map((p, i) => (
            <Row key={i} label={`${p.judge1} vs ${p.judge2}`} value={`${p.agreement}% (${p.same_pairs} pairs)`} bold={p.agreement > 89} />
          ))}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Models agree ~83-90% of the time. Claude models (4.5/4.6) agree most with each other. The ~15% disagreement rate is comparable to inter-reviewer disagreement at real conferences.
        </p>
      </Section>

      {/* 10. Institution Bias */}
      <Section num="9" title="Do LLMs Favor Prestigious Institutions?">
        <p>Does the AI judge favor papers from top institutions (MIT, Stanford, Google, etc.)?</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Cross-institution accuracy" value={`${ib.cross_institution?.accuracy || "?"}%`} />
          <Row label="Same-institution accuracy" value={`${ib.same_institution?.accuracy || "?"}%`} />
          <Row label="No-institution accuracy" value={`${ib.no_institution?.accuracy || "?"}%`} />
        </div>
        <p className="text-[10px] mt-1">Controlled same-pair test:</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Cross-institution (controlled)" value={`${ibsp.cross_institution?.accuracy || "?"}%`} />
          <Row label="Prestige gap" value={`${ibsp.prestige_gap?.bias_pp != null ? ibsp.prestige_gap.bias_pp + "pp" : "minimal"}`} />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Prestigious papers win more often, but mostly because they ARE better (by GT). The controlled same-pair test shows minimal bias — the AI judges papers on content, not institution name.
        </p>
      </Section>

      {/* 11. Single-Item vs Pairwise */}
      <Section num="10" title="Single-Item Scoring vs Pairwise Tournament">
        <p>Can 1 LLM call per paper match hundreds of pairwise comparisons? Results across {ds.length} datasets:</p>
        <div className="overflow-x-auto mt-1">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1 pr-2">Dataset</th>
                <th className="text-center py-1 px-1">GT</th>
                <th className="text-right py-1 px-1">SI Acc</th>
                <th className="text-right py-1 px-1">PW Acc</th>
                <th className="text-right py-1 px-1">SI rho</th>
                <th className="text-right py-1 px-1">PW rho</th>
                <th className="text-center py-1 px-1">Winner</th>
              </tr>
            </thead>
            <tbody>
              {ds.sort((a, b) => {
                const ga = GT_TYPE[a.dataset_id] === "comparative" ? 0 : 1;
                const gb = GT_TYPE[b.dataset_id] === "comparative" ? 0 : 1;
                return ga - gb;
              }).map(d => {
                const pw = d.methods_comparison?.[0] || {};
                const si = d.methods_comparison?.find(m => m.method === "Overall Score") || {};
                const pwWins = (pw.accuracy || 0) > (si.accuracy || 0);
                const gt = GT_TYPE[d.dataset_id] || "?";
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-0.5 pr-2">{d.name}</td>
                    <td className="text-center py-0.5 px-1">
                      <span className={`text-[8px] px-1 rounded ${gt === "comparative" ? "bg-violet-100 text-violet-700" : "bg-blue-100 text-blue-700"}`}>{gt.slice(0, 4)}</span>
                    </td>
                    <td className={`text-right py-0.5 px-1 font-mono ${!pwWins ? "font-bold" : ""}`}>{si.accuracy}%</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${pwWins ? "font-bold" : ""}`}>{pw.accuracy}%</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${(si.spearman_rho || 0) > (pw.spearman_rho || 0) ? "font-bold" : ""}`}>{si.spearman_rho?.toFixed(3) || "—"}</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${(pw.spearman_rho || 0) > (si.spearman_rho || 0) ? "font-bold" : ""}`}>{pw.spearman_rho?.toFixed(3) || "—"}</td>
                    <td className="text-center py-0.5 px-1">
                      <span className={`text-[9px] font-semibold ${pwWins ? "text-violet-700" : "text-emerald-700"}`}>{pwWins ? "PW" : "SI"}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Pairwise wins on all comparative-GT datasets (ICLR, eLife Neuro, PeerRead) at 67-89% vs 65-77%. Single-item wins on all standalone-GT datasets (Qeios, RH-50, eLife Cancer) at 74-78% vs 64-74%. The optimal method mirrors the GT generation process. Controlled experiment (same model for both) confirms this is domain-dependent, not a model artifact.
        </p>
      </Section>

      {/* 12. SP Signal */}
      <Section num="11" title="The 'Surprisingly Popular' Signal">
        <p>The gap between pairwise rank and standalone rank (BT - SI) independently predicts quality:</p>
        <div className="space-y-0.5 mt-1">
          {ds.filter(d => d.sp_analysis).sort((a, b) => (b.sp_analysis?.sp_rho || 0) - (a.sp_analysis?.sp_rho || 0)).map(d => {
            const sp = d.sp_analysis;
            return (
              <Row key={d.dataset_id} label={d.name}
                value={`rho=${sp.sp_rho != null ? (sp.sp_rho > 0 ? "+" : "") + sp.sp_rho.toFixed(3) : "?"} ${sp.significant ? `BT right ${sp.bt_right_pct}%` : `SI right ${sp.si_right_pct}%`} ${sp.significant ? "***" : "(ns)"}`}
                bold={sp.significant} />
            );
          })}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>What high-SP papers share:</strong> 6/7 top "surprisingly competitive" papers across ICLR are practical systems/frameworks — L2MAC, fairret, BioBridge, etc. Single-item scoring systematically undervalues engineering contributions whose strengths only emerge in comparison. The SP signal detects "hidden practical value."
        </p>
        <p className="mt-1">
          <strong>Caveat:</strong> SP measures comparative strength everywhere, but we can only validate it against comparative GT. On standalone-GT datasets the signal is unmeasurable, not necessarily absent.
        </p>
      </Section>

      {/* 13. Practical Recommendations */}
      <Section num="12" title="Practical Recommendations">
        <div className="space-y-2">
          <div className="border border-border/50 rounded p-2">
            <div className="font-semibold text-foreground text-[11px]">Screening (cost-efficient)</div>
            <p>Single-item scoring: 1 LLM call per paper. Use Opus 4.6 Thinking. Works best for standalone-quality assessment.</p>
          </div>
          <div className="border border-border/50 rounded p-2">
            <div className="font-semibold text-foreground text-[11px]">Competitive ranking (maximum accuracy)</div>
            <p>Pairwise tournament with Opus 4.6 Thinking summaries + round-robin judges. Abstract + AI summary as input format. ~10 matches/paper for convergence.</p>
          </div>
          <div className="border border-border/50 rounded p-2">
            <div className="font-semibold text-foreground text-[11px]">Two-stage pipeline (best of both)</div>
            <p>Single-item to screen top 20%, then pairwise among those. Use SP signal to flag "surprisingly competitive" papers that standalone scoring would miss.</p>
          </div>
          <div className="border border-border/50 rounded p-2">
            <div className="font-semibold text-foreground text-[11px]">What NOT to do</div>
            <p>Don't use multi-aspect judging (-5pp). Don't use full PDF as input (more noise, worse consistency). Don't expect majority vote to beat individual judges.</p>
          </div>
        </div>
      </Section>
    </div>
  );
}
