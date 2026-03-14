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
  "neurips-cv": "comparative",
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

function DataTable({ headers, rows, boldIdx }) {
  return (
    <div className="overflow-x-auto mt-1">
      <table className="w-full text-[10px]" style={{ tableLayout: "fixed" }}>
        <colgroup>
          <col />
          {headers.slice(1).map((_, i) => (
            <col key={i} style={{ width: `${Math.max(80, 100 / headers.length)}px` }} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-b border-border">
            {headers.map((h, i) => (
              <th key={i} className={`py-1 px-1 ${i === 0 ? "text-left pr-2" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, ri) => (
            <tr key={ri} className="border-b border-border/20">
              {cells.map((cell, ci) => (
                <td key={ci} className={`py-0.5 px-1 ${ci === 0 ? "text-left pr-2" : "text-right font-mono"} ${
                  (boldIdx !== undefined ? ri === boldIdx : ri === 0) && ci > 0 ? "font-bold text-foreground" : ""
                }`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
      axios.get(`${API}/api/validation/human-ai-benchmark?gt_type=comp`, { timeout: 90000 }).then(r => r.data).catch(() => null),
    ]).then(([si, consistency, cycles, thinking, multiAspect, judges, summarizer, correlation, bias, biasSP, ae, benchmark]) => {
      setSiData(si);
      setExperiments({ consistency, cycles, thinking, multiAspect, judges, summarizer, correlation, bias, biasSP, ae, benchmark });
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-xs text-muted-foreground text-center py-12">Loading all experiment data...</div>;

  const ex = experiments || {};
  const ds = siData?.datasets || [];

  const summ = ex.summarizer?.pooled || {};
  const jc = ex.judges || {};
  const ma = ex.multiAspect || {};
  const cy = ex.cycles?.pooled_all || {};

  return (
    <div className="space-y-4" data-testid="validation-report-full">
      <div className="border border-border rounded-lg p-4">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-1">
          <FileText className="h-5 w-5" /> Complete Validation Report
        </h2>
        <p className="text-[11px] text-muted-foreground">
          All experiments and findings from Kurate.org's AI judge validation, condensed. Covers {ds.length} single-item datasets,
          {" "}{ex.summarizer?.pooled_datasets || "12+"} pairwise datasets, and 11 distinct experiments.
        </p>
      </div>

      {/* 1. AI vs Human Benchmark */}
      {(() => {
        const bm = ex.benchmark?.pooled;
        if (!bm) return null;
        const pw = bm.pairwise || {};
        const cf = bm.tie_impact?.coin_flip || {};
        const ts = bm.tie_stats || {};
        const bt = bm.bt_correlation || {};
        return (
          <Section num="1" title="Can AI Match Human Reviewers?">
            <p>Pairwise concordance benchmark across {ex.benchmark?.n_datasets || "9"} comparative GT datasets ({ex.benchmark?.total_controlled_pairs?.toLocaleString()} controlled pairs, {ex.benchmark?.total_papers} papers). AI uses Opus 4.6 Thinking summaries with round-robin judges.</p>
            <DataTable
              headers={["Metric", "AI vs. Human", "Human vs. Human", "AI vs. Majority", "Human vs. Majority (LOO)", "AI vs. Committee", "Human vs. Committee"]}
              rows={[
                ["Ties excluded", `${pw.ai_human?.rate}%`, `${pw.human_human?.rate}%`, `${pw.ai_committee?.rate}%`, `${pw.human_committee_loo?.rate}%`,
                  bm.tier_accuracy?.ai_total > 0 ? `${bm.tier_accuracy.ai_rate}%` : "\u2014",
                  bm.tier_accuracy?.hh_total > 0 ? `${bm.tier_accuracy.hh_rate}%` : "\u2014"],
                ["Ties = coin flip", `${cf.ai_human}%`, `${cf.human_human}%`, `${cf.ai_committee}%`, `${cf.human_committee_loo}%`, "\u2014", "\u2014"],
                [`Spearman \u03C1`, bt.vs_avg_rating_rho?.toFixed(3), bt.avg_expert_vs_loo_avg?.spearman_rho?.toFixed(3), bt.committee?.spearman_rho?.toFixed(3), bt.avg_expert_vs_loo?.spearman_rho?.toFixed(3) ?? "\u2014", "\u2014", "\u2014"],
              ]}
              boldIdx={1}
            />
            <p className="text-[9px] text-muted-foreground mt-1">
              <strong>Majority</strong> = virtual majority vote from reviewer score-derived pairwise preferences (our construction).{" "}
              <strong>Committee</strong> = actual ICLR program committee tier decisions.{" "}
              Known biases: (1) tie exclusion inflates Human vs. Human (double filter); (2) LOO majority ties are skipped; (3) Human vs. Committee is circular (same reviewers influenced the decision).
            </p>
            <div className="mt-2 space-y-1.5 text-[10px] text-muted-foreground border-t border-border/30 pt-2">
              <p>
                <strong>Key finding:</strong> Under fair comparison (coin flip), AI-Human ({cf.ai_human}%) and Human-Human ({cf.human_human}%) are within <strong>{Math.abs(cf.ai_human - cf.human_human).toFixed(1)} percentage points</strong>.
                The apparent {(pw.human_human?.rate - pw.ai_human?.rate).toFixed(1)}pp Human advantage under tie exclusion is a <strong>selection bias</strong>: Human-Human requires <em>both</em> experts to have clear preferences (double filter), selecting for easier comparisons.
              </p>
              <p>
                <strong>Inter-rater concordance:</strong> AI-Human ({(bm.ai_h_concordance * 100).toFixed(1)}%) slightly <strong>exceeds</strong> Human-Human ({(ts.concordance_rate * 100).toFixed(1)}%), meaning AI agrees with each individual expert more often than experts agree with each other.
                The {(ts.tie_fraction * 100).toFixed(0)}% tie fraction shows human reviewers often cannot distinguish paper quality — AI provides verdicts on these pairs too, making it a <strong>strictly more complete</strong> signal source.
              </p>
              <p>
                <strong>Ranking correlation:</strong> AI vs h1_avg_rating Spearman {"\u03C1"} = {bt.vs_avg_rating_rho?.toFixed(3)}.
                The cleanest human baseline (Single expert vs LOO h1_avg) is {bt.avg_expert_vs_loo_avg?.spearman_rho?.toFixed(3)} — same reference, no circularity on either side.
                AI outperforms the average individual expert by {bt.vs_avg_rating_rho && bt.avg_expert_vs_loo_avg?.spearman_rho ? (bt.vs_avg_rating_rho - bt.avg_expert_vs_loo_avg.spearman_rho).toFixed(3) : "?"} on ranking quality.
              </p>
            </div>
            <p className="mt-2 border-t border-border/30 pt-2">
              <strong>Verdict:</strong> AI judges achieve <strong>human-level pairwise agreement</strong> on scientific paper quality. The 42% tie fraction is a fundamental limit of peer review — not an AI flaw. LLM judges are a validated, scalable alternative to human reviewers for relative quality ranking.
            </p>
          </Section>
        );
      })()}

      {/* 2. Best Summarizer */}
      <Section num="2" title="Which Summarizer Model is Best?">
        <p>Abstract + AI summary fed to pairwise judges. Pooled accuracy across {ex.summarizer?.pooled_datasets?.length || "12"} datasets ({ex.summarizer?.total_common_pairs?.toLocaleString() || "1,521"} common pairs, {ex.summarizer?.total_papers || "?"} papers, {ex.summarizer?.avg_matches_per_paper || "?"} matches/paper avg):</p>
        <DataTable
          headers={["Summarizer", "AI-Comm", "AI-Human", "Spearman \u03C1"]}
          rows={["Opus 4.6 Thinking", "Opus 4.6", "Opus 4.5", "GPT-5.2", "Gemini 3 Pro"].map(name => {
            const v = summ[name] || {};
            return [name, `${v.accuracy || "?"}%`, `${v.ah_accuracy || "?"}%`, v.avg_rho || "?"];
          })}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> The choice of summarizer is the most impactful decision in the pipeline. Claude dominates — Opus 4.6 Thinking leads, with the thinking budget providing a modest but consistent edge. GPT and Gemini trail significantly, suggesting Claude's reasoning better captures what human reviewers value.
        </p>
      </Section>

      {/* 2. Best Judge */}
      <Section num="3" title="Which Judge Model is Best?">
        <p>Same content shown to different judges. Accuracy on {jc.total_pairs?.toLocaleString() || jc.judges?.[0]?.total_pairs || "?"} shared pairs across {jc.total_papers || "?"} papers ({jc.avg_matches_per_paper || "?"} matches/paper avg):</p>
        <DataTable
          headers={["Judge", "AI-Comm", "AI-Human", "Spearman \u03C1"]}
          rows={[
            ...(jc.judges || []).sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0)).map(j => [
              j.label || j.name || "?", `${j.accuracy}%`, `${j.ah_accuracy || "?"}%`, j.avg_rho?.toFixed(3) || "?"
            ]),
            ...(jc.round_robin ? [[`Round-Robin (rotating)`, `${jc.round_robin.accuracy}%`, "", jc.round_robin.avg_rho?.toFixed(3) || "?"]] : []),
            ...(jc.majority_vote ? [[`Majority Vote (3 judges)`, `${jc.majority_vote.accuracy}%`, "", jc.majority_vote.avg_rho?.toFixed(3) || "?"]] : []),
          ]}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> The judge model barely matters — all models perform within a narrow band. Ensembling (majority vote, round-robin) provides no advantage over the best individual judge. This contrasts sharply with summarizer choice, which has 6x the impact. Invest in better summaries, not better judges.
        </p>
      </Section>

      {/* 3. Input Format */}
      <Section num="4" title="Which Input Format Works Best?">
        <p>Pairwise accuracy against human GT. Normalized: same 3 judges (GPT-5.2, Gemini, Opus 4.6), averaged per dataset then across datasets.</p>
        <DataTable
          headers={["Format", "Datasets", "Pairs", "Accuracy"]}
          rows={[
            ["Abs + Summary (Opus 4.6 Thinking)", "14", "8,279", "77.4%"],
            ["Abs + Summary (Opus 4.6)", "14", "11,012", "73.6%"],
            ["Deep Dive (2-pass)", "7", "3,768", "72.1%"],
            ["Abs + Summary (Opus 4.5)", "14", "25,353", "70.5%"],
            ["Full PDF", "12", "7,487", "69.5%"],
            ["Abstract only", "7", "5,025", "65.5%"],
          ]}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> AI-generated summaries unlock most of the accuracy gains — any summary is far better than raw abstract. Thinking summaries provide the strongest signal. Full PDFs underperform summaries despite having more content, suggesting that irrelevant sections introduce noise that hurts judgment quality.
        </p>
      </Section>

      {/* 4. Multi-Aspect */}
      <Section num="5" title="Does Multi-Aspect Judging Help?">
        <p>5-dimension scoring (novelty, rigor, applications, clarity, significance) vs holistic verdict:</p>
        <DataTable
          headers={["Method", "Accuracy"]}
          rows={[
            ["Holistic (standard)", `${ma.baseline?.rate || "?"}%`],
            ["Multi-aspect aggregate", `${ma.aggregate?.rate || "?"}%`],
            ["Lift", `${ma.lift || "?"}pp`],
          ]}
          boldIdx={0}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Decomposing judgment into sub-dimensions actively hurts accuracy. The AI is better at making a single holistic "which paper has more impact?" decision than aggregating five separate dimension scores. The whole is greater than the sum of its parts.
        </p>
      </Section>

      {/* 5. Consistency */}
      <Section num="6" title="How Sensitive Are Judges to the Input Format?">
        <p>Same pair shown under different input formats — how often does the verdict flip? Controlled: averaged across {(() => {
          const ctrl = ex.consistency?.verdict_stability?.cross_format?.controlled;
          return ctrl ? Object.values(ctrl)[0]?.shared_format_pairs || "?" : "?";
        })()} shared format pairs where all 4 models have data.</p>
        {(() => {
          const ctrl = ex.consistency?.verdict_stability?.cross_format?.controlled || {};
          const raw = ex.consistency?.verdict_stability?.cross_format?.by_model || {};
          const hasCtrl = Object.keys(ctrl).length > 0;
          const models = hasCtrl ? ctrl : raw;
          const sorted = Object.entries(models).sort((a, b) =>
            (a[1].mean_rate ?? a[1].rate ?? 100) - (b[1].mean_rate ?? b[1].rate ?? 100)
          );
          return (
            <DataTable
              headers={["Judge", "Controlled Flip Rate", "Pairs"]}
              rows={sorted.map(([name, stats]) => [
                name,
                `${stats.mean_rate ?? stats.rate}%`,
                (stats.total || 0).toLocaleString(),
              ])}
            />
          );
        })()}
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> When controlled for identical format-pair comparisons, Claude models (Opus 4.5 and 4.6) are the most stable judges at ~13% flip rate. GPT-5.2 is least stable at ~15%. The 2pp spread between models is real but modest — the dominant factor remains the input format itself, not which model judges it.
        </p>
      </Section>

      {/* 6. Intransitive Cycles */}
      <Section num="7" title="How Often Do Intransitive Cycles Occur?">
        <p>A beats B, B beats C, C beats A — a violation of transitivity. Cycle rate per judge:</p>
        <DataTable
          headers={["Judge", "Cycle Rate"]}
          rows={[
            ["Opus 4.6", "0.95%"], ["Opus 4.5", "2.22%"],
            ["Gemini 3 Pro", "3.10%"], ["GPT-5.2", "3.57%"],
          ]}
        />
        <p className="text-[10px] mt-1">By paper quality gap:</p>
        <DataTable
          headers={["Gap", "Cycle Rate"]}
          rows={[
            ["Close-rated", `${cy.by_gap?.close?.rate || "?"}%`],
            ["Mid-gap", `${cy.by_gap?.mid?.rate || "?"}%`],
            ["Far-rated", `${cy.by_gap?.far?.rate || "?"}%`],
          ]}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> Transitivity violations are rare but real. Opus 4.6 is 4x more transitive than GPT-5.2, producing almost perfectly consistent preference orderings. Cycles concentrate on closely-rated papers where quality differences are genuinely ambiguous — this is expected noise, not a fundamental flaw.
        </p>
      </Section>

      {/* 7. Model Agreement */}
      <Section num="8" title="How Much Do Models Agree?">
        <p>Pairwise agreement on the same 6,477 paper pairs (only pairs where all 4 models voted):</p>
        <DataTable
          headers={["Model Pair", "Agreement"]}
          rows={[
            ["Opus 4.6 vs Opus 4.5", "88.2%"],
            ["Opus 4.6 vs Gemini 3 Pro", "85.0%"],
            ["Opus 4.5 vs Gemini 3 Pro", "83.9%"],
            ["Opus 4.5 vs GPT-5.2", "82.7%"],
            ["GPT-5.2 vs Gemini 3 Pro", "82.5%"],
            ["Opus 4.6 vs GPT-5.2", "82.2%"],
          ]}
        />
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>Verdict:</strong> The Claude model family forms a tight cluster (88% agreement), while cross-family pairs show ~82-85% agreement. The overall ~15% disagreement rate mirrors inter-reviewer disagreement at human peer review venues — AI judges are as (dis)agreeable as human reviewers.
        </p>
      </Section>

      {/* 8. Institution Bias */}
      <Section num="9" title="Do LLMs Favor Prestigious Institutions?">
        <p>Controlled same-pair test: 1,891 pairs where one paper is from a prestigious institution (MIT, Stanford, Google, etc.).</p>
        <p className="mt-1"><em>How often does each pick the prestigious paper?</em></p>
        <DataTable
          headers={["Source", "Rate", "Delta vs Human"]}
          rows={[
            ["Human GT (reviewers)", "78.5%", "—"],
            ["Opus 4.6", "73.8%", "-4.7pp"],
            ["Opus 4.5", "73.5%", "-5.0pp"],
            ["GPT-5.2", "73.4%", "-5.1pp"],
            ["Gemini 3 Pro", "72.4%", "-6.1pp"],
          ]}
          boldIdx={0}
        />

        <div className="mt-3 p-3 border border-amber-200 rounded-lg bg-amber-50/30">
          <h4 className="text-[11px] font-semibold text-amber-900 mb-1">Is Higher Accuracy Driven by Shared Bias?</h4>
          <p className="text-[10px] text-amber-800/80 mb-2">If a model's accuracy advantage is concentrated in prestige-gap pairs (where matching human bias helps), it suggests bias inflation. If the advantage is uniform across all pair types, it's genuine quality detection.</p>

          <p className="text-[10px] font-medium text-amber-900/70 mt-2 mb-1">BY JUDGE</p>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]" style={{ tableLayout: "fixed" }}>
              <colgroup>
                <col />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
              </colgroup>
              <thead><tr className="border-b border-amber-200">
                <th className="text-left py-1 pr-2">Judge</th>
                <th className="text-right py-1 px-1">Prestige-Gap</th>
                <th className="text-right py-1 px-1">No Institution</th>
                <th className="text-right py-1 px-1">Other Inst.</th>
                <th className="text-right py-1 px-1">Gap Adv.</th>
              </tr></thead>
              <tbody>
                {[
                  { name: "GPT-5.2", pg: "78.1%", ni: "69.4%", oi: "73%", gap: "+8.7pp" },
                  { name: "Gemini 3 Pro", pg: "78.4%", ni: "71%", oi: "68.4%", gap: "+7.4pp" },
                  { name: "Opus 4.5", pg: "79.3%", ni: "70.8%", oi: "75.6%", gap: "+8.5pp" },
                  { name: "Opus 4.6", pg: "79.8%", ni: "71.7%", oi: "74.7%", gap: "+8.1pp" },
                ].map(j => (
                  <tr key={j.name} className="border-b border-amber-100">
                    <td className="py-0.5 pr-2">{j.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.pg}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.ni}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{j.oi}</td>
                    <td className="text-right py-0.5 px-1 font-mono text-amber-700">{j.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[10px] font-medium text-amber-900/70 mt-3 mb-1">BY SUMMARIZER</p>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]" style={{ tableLayout: "fixed" }}>
              <colgroup>
                <col />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
              </colgroup>
              <thead><tr className="border-b border-amber-200">
                <th className="text-left py-1 pr-2">Summarizer</th>
                <th className="text-right py-1 px-1">Prestige-Gap</th>
                <th className="text-right py-1 px-1">No Institution</th>
                <th className="text-right py-1 px-1">Other Inst.</th>
                <th className="text-right py-1 px-1">Gap Adv.</th>
              </tr></thead>
              <tbody>
                {[
                  { name: "GPT-5.2", pg: "75.2%", ni: "69.1%", oi: "71.4%", gap: "+6.1pp" },
                  { name: "Gemini 3 Pro", pg: "74.5%", ni: "68.8%", oi: "70.7%", gap: "+5.7pp" },
                  { name: "Opus 4.5", pg: "78.4%", ni: "70.7%", oi: "72%", gap: "+7.7pp" },
                  { name: "Opus 4.6", pg: "80%", ni: "70.7%", oi: "74.9%", gap: "+9.3pp" },
                  { name: "Opus 4.6 Thinking", pg: "84.9%", ni: "77.4%", oi: "79.3%", gap: "+7.5pp" },
                ].map(s => (
                  <tr key={s.name} className="border-b border-amber-100">
                    <td className="py-0.5 pr-2">{s.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.pg}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.ni}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{s.oi}</td>
                    <td className="text-right py-0.5 px-1 font-mono text-amber-700">{s.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-3 pt-2 border-t border-amber-200 text-[10px] text-amber-900/80 space-y-1.5">
            <p><strong>Judges:</strong> All 4 judges show a similar "Gap Advantage" (~8pp). Since this is <em>uniform</em> across judges, the accuracy difference between judges is <strong>not driven by prestige bias</strong>. Prestige-gap pairs are inherently easier because the quality gap tends to be larger.</p>
            <p><strong>Summarizers:</strong> <strong>Opus 4.6 Thinking</strong> (the best overall at 84.9% on prestige-gap) also leads on no-institution pairs (77.4% vs 68-71%). Since its lead is strongest where prestige can't help, its advantage is primarily <strong>genuine quality detection</strong>.</p>
          </div>
        </div>
      </Section>

      {/* 9. Single-Item vs Pairwise */}
      <Section num="10" title="Single-Item Scoring vs Pairwise Tournament">
        <p>Can 1 LLM call per paper match hundreds of pairwise comparisons? Results across {ds.length} datasets:</p>

        <div className="my-2 p-3 border border-blue-200 rounded-lg bg-blue-50/30">
          <h4 className="text-[11px] font-semibold text-blue-900 mb-1">Why Ground Truth Type Matters</h4>
          <p className="text-[10px] text-blue-800/80 mb-1.5">The "GT" column indicates how human reviewers generated the ground truth — the single strongest predictor of which AI method wins:</p>
          <div className="text-[10px] text-blue-800/80 space-y-1">
            <p><span className="inline-block text-[8px] px-1 rounded bg-violet-100 text-violet-700 mr-1">comp</span><strong>Comparative GT</strong> (ICLR, PeerRead): Reviewers scored papers on a numeric scale and acceptance decisions were made by committees comparing papers against each other.</p>
            <p><span className="inline-block text-[8px] px-1 rounded bg-blue-100 text-blue-700 mr-1">stan</span><strong>Standalone GT</strong> (Qeios, ResearchHub, eLife): Each paper was rated independently by individual reviewers on numeric scales or tiered assessments.</p>
          </div>
          <p className="text-[10px] text-blue-800/80 mt-1.5"><strong>The eLife exception:</strong> eLife Neuroscience empirically behaves as <em>comparative</em> GT. The diagnostic is the Gap signal (pairwise rank minus standalone rank): on Cancer and Comp &amp; Sys Bio, the Gap signal is near zero ({"\u03C1"}{"\u2248"}0.01, ns). On Neuroscience, Gap {"\u03C1"}=0.52 (p&lt;0.001) — as strong as ICLR. The likely cause: Neuro's ratings cluster heavily at a single tier (51% at tier 3), so real quality differentiation only emerges through pairwise comparison.</p>
        </div>
        <div className="overflow-x-auto mt-1">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1 pr-2">Dataset</th>
                <th className="text-center py-1 px-1">GT</th>
                <th className="text-right py-1 px-1">Pairs</th>
                <th className="text-right py-1 px-1">SI Acc</th>
                <th className="text-right py-1 px-1">PW Acc</th>
                <th className="text-right py-1 px-1">SI Spearman {"\u03C1"}</th>
                <th className="text-right py-1 px-1">PW Spearman {"\u03C1"}</th>
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
                    <td className="text-right py-0.5 px-1 font-mono text-muted-foreground">{d.single_item_pairs?.toLocaleString() ?? "\u2014"}</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${!pwWins ? "font-bold" : ""}`}>{si.accuracy}%</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${pwWins ? "font-bold" : ""}`}>{pw.accuracy}%</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${(si.spearman_rho || 0) > (pw.spearman_rho || 0) ? "font-bold" : ""}`}>{si.spearman_rho?.toFixed(3) || "\u2014"}</td>
                    <td className={`text-right py-0.5 px-1 font-mono ${(pw.spearman_rho || 0) > (si.spearman_rho || 0) ? "font-bold" : ""}`}>{pw.spearman_rho?.toFixed(3) || "\u2014"}</td>
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

      {/* 10. Gap Signal */}
      <Section num="11" title="The Gap Signal (Pairwise Rank vs Standalone Rank)">
        <p>The gap between pairwise rank and standalone rank (BT - SI) independently predicts quality:</p>
        <div className="overflow-x-auto mt-1">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-1 pr-2">Dataset</th>
                <th className="text-right py-1 px-1">Gap {"\u03C1"}</th>
                <th className="text-right py-1 px-1">Gap Accuracy</th>
                <th className="text-center py-1 px-1">Sig?</th>
              </tr>
            </thead>
            <tbody>
              {ds.filter(d => d.sp_analysis).sort((a, b) => (b.sp_analysis?.sp_rho || 0) - (a.sp_analysis?.sp_rho || 0)).map(d => {
                const sp = d.sp_analysis;
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-0.5 pr-2">{d.name}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{sp.sp_rho != null ? (sp.sp_rho > 0 ? "+" : "") + sp.sp_rho.toFixed(3) : "\u2014"}</td>
                    <td className="text-right py-0.5 px-1 font-mono">{sp.sp_accuracy != null ? sp.sp_accuracy + "%" : "\u2014"}</td>
                    <td className="text-center py-0.5 px-1">{sp.significant ? "***" : "(ns)"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 border-t border-border/30 pt-2">
          <strong>What high-Gap papers share:</strong> 6/7 top "surprisingly competitive" papers across ICLR are practical systems/frameworks — L2MAC, fairret, BioBridge, etc. Single-item scoring systematically undervalues engineering contributions whose strengths only emerge in comparison. The Gap signal detects "hidden practical value."
        </p>
        <p className="mt-1">
          <strong>Caveat:</strong> The Gap signal measures comparative strength everywhere, but we can only validate it against comparative GT. On standalone-GT datasets the signal is unmeasurable, not necessarily absent.
        </p>
      </Section>

    </div>
  );
}
