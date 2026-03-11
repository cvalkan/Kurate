import { useState, useEffect } from "react";
import axios from "axios";
import { FileText, CheckCircle, XCircle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const GT_TYPE = {
  "iclr-codegen": "comparative", "iclr-llm": "comparative", "iclr-protein": "comparative",
  "iclr-fairness": "comparative", "iclr-pdes": "comparative", "iclr-molecules": "comparative",
  "iclr-optimization": "comparative", "peerread_acl_2017": "comparative",
  "elife-neuro-100": "comparative",
  "elife-cancer": "standalone", "elife-microbiology": "standalone",
  "elife-comp-sys-bio": "standalone",
  "midl-medical-imaging": "standalone", "qeios-social": "standalone", "qeios-physical": "standalone",
  "researchhub-50": "standalone", "researchhub-cancer": "standalone", "researchhub-genetics": "standalone",
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
          <strong>Verdict:</strong> The choice of summarizer is the most impactful decision in the pipeline. Claude dominates — Opus 4.6 Thinking leads, with the thinking budget providing a modest but consistent edge. GPT and Gemini trail significantly, suggesting Claude's reasoning better captures what human reviewers value.
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
          <strong>Verdict:</strong> The judge model barely matters — all models perform within a narrow band. Ensembling (majority vote, round-robin) provides no advantage over the best individual judge. This contrasts sharply with summarizer choice, which has 6x the impact. Invest in better summaries, not better judges.
        </p>
      </Section>

      {/* 3. Summarizer x Judge Matrix */}
      {/* 3. Input Format */}
      <Section num="3" title="Which Input Format Works Best?">
        <p>Pairwise accuracy against human GT. Normalized: same 3 judges (GPT-5.2, Gemini, Opus 4.6), averaged per dataset then across datasets — so no single dataset or judge dominates.</p>
        <div className="space-y-0.5 mt-1">
          {[
            { fmt: "Abs + Summary (Opus 4.6 Thinking)", acc: "77.4%", n: "14 datasets, 8,279 pairs" },
            { fmt: "Abs + Summary (Opus 4.6)", acc: "73.6%", n: "14 datasets, 11,012 pairs" },
            { fmt: "Deep Dive (2-pass)", acc: "72.1%", n: "7 datasets, 3,768 pairs" },
            { fmt: "Abs + Summary (Opus 4.5)", acc: "70.5%", n: "14 datasets, 25,353 pairs" },
            { fmt: "Full PDF", acc: "69.5%", n: "12 datasets, 7,487 pairs" },
            { fmt: "Abstract only", acc: "65.5%", n: "7 datasets, 5,025 pairs" },
          ].map((r, i) => <Row key={r.fmt} label={`${r.fmt} (${r.n})`} value={r.acc} bold={i === 0} />)}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> AI-generated summaries unlock most of the accuracy gains — any summary is far better than raw abstract. Thinking summaries provide the strongest signal. Full PDFs underperform summaries despite having more content, suggesting that irrelevant sections introduce noise that hurts judgment quality.
        </p>
      </Section>

      {/* 4. Multi-Aspect */}
      <Section num="4" title="Does Multi-Aspect Judging Help?">
        <p>5-dimension scoring (novelty, rigor, applications, clarity, significance) vs holistic verdict:</p>
        <div className="space-y-0.5 mt-1">
          <Row label="Holistic (standard)" value={`${ma.baseline?.rate || "?"}%`} bold />
          <Row label="Multi-aspect aggregate (majority of 5 dims)" value={`${ma.aggregate?.rate || "?"}%`} />
          <Row label="Lift" value={`${ma.lift || "?"}pp`} />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Decomposing judgment into sub-dimensions actively hurts accuracy. The AI is better at making a single holistic "which paper has more impact?" decision than aggregating five separate dimension scores. The whole is greater than the sum of its parts.
        </p>
      </Section>

      {/* 5. Consistency */}
      <Section num="5" title="How Consistent Are the Judgments?">
        <p>Same pair shown under different input formats — how often does the verdict flip? (Cross-format flip rate per judge model.)</p>
        <div className="space-y-0.5 mt-1">
          {[
            { name: "Opus 4.6", rate: "8.2%", n: "1,238" },
            { name: "Opus 4.5", rate: "13.4%", n: "20,774" },
            { name: "Gemini 3 Pro", rate: "15.0%", n: "24,017" },
            { name: "GPT-5.2", rate: "15.7%", n: "24,265" },
          ].map((j, i) => <Row key={j.name} label={`${j.name} (${j.n} pairs)`} value={j.rate} bold={i === 0} />)}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Opus 4.5, GPT-5.2, and Gemini 3 Pro are comparable (13-16% flip rate across ~20-24K format-pair comparisons). Opus 4.6 shows 8.2% but on only 1,238 pairs — likely comparing more similar formats, making it <em>not directly comparable</em> to the others. The consistent ~15% flip rate across three well-sampled models means input representation is a first-order variable: changing how you present the paper changes the outcome for roughly 1 in 7 comparisons.
        </p>
      </Section>

      {/* 6. Intransitive Cycles */}
      <Section num="6" title="How Often Do Intransitive Cycles Occur?">
        <p>A beats B, B beats C, C beats A — a violation of transitivity. Cycle rate per judge:</p>
        <div className="space-y-0.5 mt-1">
          {[
            { name: "Opus 4.6", rate: "0.95%" },
            { name: "Opus 4.5", rate: "2.22%" },
            { name: "Gemini 3 Pro", rate: "3.10%" },
            { name: "GPT-5.2", rate: "3.57%" },
          ].map((j, i) => <Row key={j.name} label={j.name} value={j.rate} bold={i === 0} />)}
        </div>
        <p className="text-[10px] mt-1">By paper quality gap:</p>
        <div className="space-y-0.5">
          <Row label="Close-rated papers" value={`${cy.by_gap?.close?.rate || "?"}%`} />
          <Row label="Mid-gap papers" value={`${cy.by_gap?.mid?.rate || "?"}%`} />
          <Row label="Far-rated papers" value={`${cy.by_gap?.far?.rate || "?"}%`} />
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Transitivity violations are rare but real. Opus 4.6 is 4x more transitive than GPT-5.2, producing almost perfectly consistent preference orderings. Cycles concentrate on closely-rated papers where quality differences are genuinely ambiguous — this is expected noise, not a fundamental flaw.
        </p>
      </Section>

      {/* 9. Model Agreement */}
      <Section num="7" title="How Much Do Models Agree?">
        <p>Pairwise agreement on the same 6,477 paper pairs (only pairs where all 4 models voted):</p>
        <div className="space-y-0.5 mt-1">
          {[
            { pair: "Opus 4.6 vs Opus 4.5", agree: "88.2%" },
            { pair: "Opus 4.6 vs Gemini 3 Pro", agree: "85.0%" },
            { pair: "Opus 4.5 vs Gemini 3 Pro", agree: "83.9%" },
            { pair: "Opus 4.5 vs GPT-5.2", agree: "82.7%" },
            { pair: "GPT-5.2 vs Gemini 3 Pro", agree: "82.5%" },
            { pair: "Opus 4.6 vs GPT-5.2", agree: "82.2%" },
          ].map(r => <Row key={r.pair} label={r.pair} value={r.agree} bold={r.agree === "88.2%"} />)}
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> The Claude model family forms a tight cluster (88% agreement), while cross-family pairs show ~82-85% agreement. The overall ~15% disagreement rate mirrors inter-reviewer disagreement at human peer review venues — AI judges are as (dis)agreeable as human reviewers.
        </p>
      </Section>

      {/* 8. Institution Bias */}
      <Section num="8" title="Do LLMs Favor Prestigious Institutions?">
        <p>Controlled same-pair test: 1,891 pairs where one paper is from a prestigious institution (MIT, Stanford, Google, etc.). Same judges, same pairs — only institution metadata varies.</p>
        <p className="mt-1"><em>How often does each pick the prestigious paper?</em></p>
        <div className="space-y-0.5 mt-1">
          <Row label="Human GT (reviewers)" value="78.5%" bold />
          <Row label="Opus 4.6" value="73.8%  (delta: -4.7pp vs humans)" />
          <Row label="Opus 4.5" value="73.5%  (delta: -5.0pp)" />
          <Row label="GPT-5.2" value="73.4%  (delta: -5.1pp)" />
          <Row label="Gemini 3 Pro" value="72.4%  (delta: -6.1pp)" />
        </div>

        <div className="mt-3 p-3 border border-amber-200 rounded-lg bg-amber-50/30">
          <h4 className="text-[11px] font-semibold text-amber-900 mb-1">Is Higher Accuracy Driven by Shared Bias?</h4>
          <p className="text-[10px] text-amber-800/80 mb-2">If a model's accuracy advantage is concentrated in prestige-gap pairs (where matching human bias helps), it suggests bias inflation. If the advantage is uniform across all pair types, it's genuine quality detection.</p>

          <p className="text-[10px] font-medium text-amber-900/70 mt-2 mb-1">BY JUDGE</p>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead><tr className="border-b border-amber-200">
                <th className="text-left py-1 pr-2">Judge</th>
                <th className="text-right py-1 px-1">Prestige-Gap</th>
                <th className="text-right py-1 px-1">No Institution</th>
                <th className="text-right py-1 px-1">Other Inst.</th>
                <th className="text-right py-1 px-1">Gap Advantage</th>
              </tr></thead>
              <tbody>
                {[
                  { name: "GPT-5.2", pg: "78.1%", pgn: 1891, ni: "69.4%", nin: 5200, oi: "73%", oin: 455, gap: "+8.7pp" },
                  { name: "Gemini 3 Pro", pg: "78.4%", pgn: 1891, ni: "71%", nin: 5200, oi: "68.4%", oin: 455, gap: "+7.4pp" },
                  { name: "Opus 4.5", pg: "79.3%", pgn: 1891, ni: "70.8%", nin: 5200, oi: "75.6%", oin: 455, gap: "+8.5pp" },
                  { name: "Opus 4.6", pg: "79.8%", pgn: 1891, ni: "71.7%", nin: 5200, oi: "74.7%", oin: 455, gap: "+8.1pp" },
                ].map(j => (
                  <tr key={j.name} className="border-b border-amber-100">
                    <td className="py-0.5 pr-2">{j.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.pg} <span className="text-muted-foreground">({j.pgn})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.ni} <span className="text-muted-foreground">({j.nin})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.oi} <span className="text-muted-foreground">({j.oin})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono text-amber-700">{j.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[10px] font-medium text-amber-900/70 mt-3 mb-1">BY SUMMARIZER</p>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead><tr className="border-b border-amber-200">
                <th className="text-left py-1 pr-2">Summarizer</th>
                <th className="text-right py-1 px-1">Prestige-Gap</th>
                <th className="text-right py-1 px-1">No Institution</th>
                <th className="text-right py-1 px-1">Other Inst.</th>
                <th className="text-right py-1 px-1">Gap Advantage</th>
              </tr></thead>
              <tbody>
                {[
                  { name: "GPT-5.2", pg: "75.2%", pgn: 979, ni: "69.1%", nin: 1077, oi: "71.4%", oin: 241, gap: "+6.1pp" },
                  { name: "Gemini 3 Pro", pg: "74.5%", pgn: 705, ni: "68.8%", nin: 836, oi: "70.7%", oin: 188, gap: "+5.7pp" },
                  { name: "Opus 4.5", pg: "78.4%", pgn: 6791, ni: "70.7%", nin: 9330, oi: "72%", oin: 1649, gap: "+7.7pp" },
                  { name: "Opus 4.6", pg: "80%", pgn: 2064, ni: "70.7%", nin: 3230, oi: "74.9%", oin: 593, gap: "+9.3pp" },
                  { name: "Opus 4.6 Thinking", pg: "84.9%", pgn: 985, ni: "77.4%", nin: 1201, oi: "79.3%", oin: 242, gap: "+7.5pp" },
                ].map(s => (
                  <tr key={s.name} className="border-b border-amber-100">
                    <td className="py-0.5 pr-2">{s.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.pg} <span className="text-muted-foreground">({s.pgn})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.ni} <span className="text-muted-foreground">({s.nin})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.oi} <span className="text-muted-foreground">({s.oin})</span></td>
                    <td className="text-right py-0.5 px-1 font-mono text-amber-700">{s.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-3 pt-2 border-t border-amber-200 text-[10px] text-amber-900/80 space-y-1.5">
            <p><strong>Judges:</strong> All 4 judges show a similar "Gap Advantage" (~8pp). This means every judge is more accurate on prestige-gap pairs than on no-institution pairs by roughly the same amount. Since this advantage is <em>uniform</em> across judges — not concentrated in the most bias-aligned judge (Opus 4.6) — the accuracy difference between judges is <strong>not driven by prestige bias</strong>. The likely explanation: prestige-gap pairs are inherently easier to judge because the quality gap between a top-lab paper and an unknown-institution paper tends to be larger.</p>
            <p><strong>Summarizers:</strong> More nuance here. Opus 4.6 summaries have the largest Gap Advantage (+9.3pp) — suggesting they encode more institutional cues that make prestige-gap pairs <em>even easier</em> for judges. However, <strong>Opus 4.6 Thinking</strong> (the best summarizer overall at 84.9% on prestige-gap pairs) also leads on no-institution pairs (77.4% vs 68-71% for others). Since its lead is strongest where prestige can't help, its accuracy advantage is primarily <strong>genuine quality detection</strong>, with a small prestige component.</p>
          </div>
        </div>
      </Section>

      {/* 11. Single-Item vs Pairwise */}
      <Section num="9" title="Single-Item Scoring vs Pairwise Tournament">
        <p>Can 1 LLM call per paper match hundreds of pairwise comparisons? Results across {ds.length} datasets:</p>

        <div className="my-2 p-3 border border-blue-200 rounded-lg bg-blue-50/30">
          <h4 className="text-[11px] font-semibold text-blue-900 mb-1">Why Ground Truth Type Matters</h4>
          <p className="text-[10px] text-blue-800/80 mb-1.5">The "GT" column indicates how human reviewers generated the ground truth — this is the single strongest predictor of which AI method wins:</p>
          <div className="text-[10px] text-blue-800/80 space-y-1">
            <p><span className="inline-block text-[8px] px-1 rounded bg-violet-100 text-violet-700 mr-1">comp</span><strong>Comparative GT</strong> (ICLR, PeerRead): Reviewers scored papers on a numeric scale and acceptance decisions were made by committees comparing papers against each other. The ground truth reflects <em>relative</em> quality. Pairwise AI judgments mirror this process.</p>
            <p><span className="inline-block text-[8px] px-1 rounded bg-blue-100 text-blue-700 mr-1">stan</span><strong>Standalone GT</strong> (Qeios, ResearchHub, eLife): Each paper was rated independently — Qeios and ResearchHub by individual reviewers on numeric scales, eLife by editors assigning one of 4 significance tiers (Landmark / Fundamental / Important / Useful). No paper-vs-paper comparison was involved. Single-item AI scoring mirrors this process.</p>
          </div>
          <p className="text-[10px] text-blue-800/80 mt-1.5"><strong>The eLife exception:</strong> All eLife datasets use the same 4-tier editor assessment, but eLife Neuroscience empirically behaves as <em>comparative</em> GT. The diagnostic is the Gap signal (pairwise rank minus standalone rank): on Cancer and Comp &amp; Sys Bio, the Gap signal is near zero (ρ≈0.01, not significant) — the pairwise tournament adds no ranking information beyond what standalone scoring captures. On Neuroscience, the Gap signal is ρ=0.52 (p&lt;0.001, 76% accuracy) — as strong as ICLR. The likely cause: Neuro's ratings cluster heavily at a single tier (51% at tier 3), so the real quality differentiation happens <em>within</em> the dominant tier — which only pairwise comparison can resolve. The formal process is the same, but the effective information structure is comparative.</p>
        </div>
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
          <strong>Verdict:</strong> The ground truth generation process determines which method wins. Pairwise dominates when human reviewers compared papers against each other (ICLR, PeerRead, eLife Neuro). Single-item wins when papers were rated independently (Qeios, ResearchHub, most eLife). The exception: narrow-domain datasets (ResearchHub Cancer, MIDL) where within-topic distinctions require head-to-head comparison even with standalone GT.
        </p>
      </Section>

      {/* 10. SP Signal */}
      <Section num="10" title="The Gap Signal (Pairwise Rank vs Standalone Rank)">
        <p>The gap between pairwise rank and standalone rank (BT - SI) independently predicts quality:</p>
        <div className="overflow-x-auto mt-1">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1 pr-2">Dataset</th>
                <th className="text-right py-1 px-1">SP rho</th>
                <th className="text-right py-1 px-1">SP Accuracy</th>
                <th className="text-center py-1 px-1">Sig?</th>
              </tr>
            </thead>
            <tbody>
              {ds.filter(d => d.sp_analysis).sort((a, b) => (b.sp_analysis?.sp_rho || 0) - (a.sp_analysis?.sp_rho || 0)).map(d => {
                const sp = d.sp_analysis;
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-0.5 pr-2">{d.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{sp.sp_rho != null ? (sp.sp_rho > 0 ? "+" : "") + sp.sp_rho.toFixed(3) : "—"}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{sp.sp_accuracy != null ? sp.sp_accuracy + "%" : "—"}</td>
                    <td className="text-center py-0.5 px-1">{sp.significant ? "***" : "(ns)"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>What high-SP papers share:</strong> 6/7 top "surprisingly competitive" papers across ICLR are practical systems/frameworks — L2MAC, fairret, BioBridge, etc. Single-item scoring systematically undervalues engineering contributions whose strengths only emerge in comparison. The SP signal detects "hidden practical value."
        </p>
        <p className="mt-1">
          <strong>Caveat:</strong> SP measures comparative strength everywhere, but we can only validate it against comparative GT. On standalone-GT datasets the signal is unmeasurable, not necessarily absent.
        </p>
      </Section>

    </div>
  );
}
