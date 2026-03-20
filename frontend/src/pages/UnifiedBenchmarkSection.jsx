import { useState, useEffect } from "react";
import axios from "axios";
import { Scale, ChevronDown, ChevronRight } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL || "";

function Metric({ label, value, sub, accent }) {
  return (
    <div className="text-center px-3 py-2">
      <div className={`text-lg font-bold font-mono ${accent ? "text-accent" : "text-foreground"}`}>{value}</div>
      <div className="text-[10px] text-muted-foreground leading-tight">{label}</div>
      {sub && <div className="text-[9px] text-muted-foreground/60 mt-0.5">{sub}</div>}
    </div>
  );
}

function BTCorrelationTable({ pwCorrs, siCorrs }) {
  if (!pwCorrs && !siCorrs) return null;
  const rows = [
    { key: "vs_individual", label: "vs Individual aggregate", desc: "BT vs all-expert-votes BT" },
    { key: "vs_avg_rating", label: "vs Avg Rating", desc: "BT vs average reviewer scores" },
    { key: "vs_majority", label: "vs Majority", desc: "BT vs majority-vote BT" },
    { key: "vs_committee", label: "vs Committee (ICLR PC)", desc: "BT vs committee tier decisions" },
  ];
  const f = v => v != null ? v.toFixed(3) : "\u2014";
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Ranking Correlation (Bradley-Terry) — PW vs SI</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Comparison</th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-violet-500/[0.06]" colSpan={2}>Pairwise (PW)</th>
              <th className="py-1.5 px-1.5 text-right font-medium bg-emerald-500/[0.06]" colSpan={2}>Single-Item (SI)</th>
              <th className="py-1.5 px-2 text-left font-medium">Description</th>
            </tr>
            <tr className="border-b border-border text-muted-foreground text-[9px]">
              <th></th>
              <th className="py-0.5 px-1.5 text-right bg-violet-500/[0.06]">{"\u03C1"}</th>
              <th className="py-0.5 px-1.5 text-right bg-violet-500/[0.06]">{"\u03C4"}</th>
              <th className="py-0.5 px-1.5 text-right bg-emerald-500/[0.06]">{"\u03C1"}</th>
              <th className="py-0.5 px-1.5 text-right bg-emerald-500/[0.06]">{"\u03C4"}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const pw = pwCorrs?.[r.key];
              const si = siCorrs?.[r.key];
              const pwWins = (pw?.rho || 0) >= (si?.rho || 0);
              return (
                <tr key={r.key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 font-medium">{r.label}</td>
                  <td className={`py-1.5 px-1.5 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-semibold" : ""}`}>{f(pw?.rho)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono bg-violet-500/[0.06] text-foreground/60">{f(pw?.tau)}</td>
                  <td className={`py-1.5 px-1.5 text-right font-mono bg-emerald-500/[0.06] ${!pwWins ? "font-semibold" : ""}`}>{f(si?.rho)}</td>
                  <td className="py-1.5 px-1.5 text-right font-mono bg-emerald-500/[0.06] text-foreground/60">{f(si?.tau)}</td>
                  <td className="py-1.5 px-2 text-muted-foreground text-[10px]">{pw?.desc || si?.desc || r.desc}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ComparisonTable({ data }) {
  const p = data.pooled;
  const levels = [
    { key: "easy", label: "Cross-tier (easy)" },
    { key: "medium", label: "Adjacent-tier (medium)" },
    { key: "hard", label: "Within-tier (hard)" },
  ];
  const hasSI = (p.si_total || 0) > 0 || (p.intersection?.pairs || 0) > 0;
  const hasIntersection = (p.intersection?.pairs || 0) > 0;
  const pwAcc = hasIntersection ? p.intersection.pw_accuracy : p.pw_accuracy;
  const siAcc = hasIntersection ? p.intersection.si_accuracy : (hasSI ? p.si_accuracy : null);
  const pwWins = (pwAcc || 0) >= (siAcc || 0);
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border flex items-center gap-2">
        <Scale className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">PW vs SI — Accuracy on Same Pairs, Ranking on Full Data</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "25%" }} />
            <col /><col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Scope</th>
              <th className="py-1.5 px-2 text-right font-medium bg-violet-500/[0.06]">PW Accuracy</th>
              <th className="py-1.5 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Accuracy</th>
              <th className="py-1.5 px-2 text-right font-medium bg-indigo-500/[0.06]">SI Sub-Avg Acc</th>
              <th className="py-1.5 px-2 text-right font-medium bg-violet-500/[0.06]">PW Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium bg-emerald-500/[0.06]">SI Spearman {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium bg-indigo-500/[0.06]">SI Sub-Avg {"\u03C1"}</th>
              <th className="py-1.5 px-2 text-right font-medium text-foreground/50">pairs</th>
            </tr>
          </thead>
          <tbody>
            {p.intersection && (
              <tr className="border-b border-border bg-accent/5">
                <td className="py-1.5 px-2 text-left text-xs font-semibold">{hasIntersection ? "Pooled (same pairs)" : "Pooled (full data)"}</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{pwAcc != null ? `${pwAcc}%` : "\u2014"}</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${!pwWins && siAcc != null ? "font-bold" : ""}`}>{siAcc != null ? `${siAcc}%` : "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs bg-indigo-500/[0.06]">{p.si_sub_accuracy != null && p.si_sub_accuracy > 0 ? `${p.si_sub_accuracy}%` : "\u2014"}</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-violet-500/[0.06] ${(p.pw_rho || 0) >= (p.si_rho || 0) ? "font-bold" : ""}`}>{p.pw_rho?.toFixed(3) ?? "\u2014"}</td>
                <td className={`py-1.5 px-2 text-right font-mono text-xs bg-emerald-500/[0.06] ${(p.si_rho || 0) > (p.pw_rho || 0) ? "font-bold" : ""}`}>{p.si_rho?.toFixed(3) ?? "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs bg-indigo-500/[0.06]">{p.si_sub_rho?.toFixed(3) ?? "\u2014"}</td>
                <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/50">{hasIntersection ? p.intersection.pairs?.toLocaleString() : (p.pw_total || 0).toLocaleString()}</td>
              </tr>
            )}
            {levels.map(({ key, label }) => {
              const d = p.by_difficulty?.[key] || {};
              const pwB = (d.pw_rate || 0) >= (d.si_rate || 0);
              return (
                <tr key={key} className="border-b border-border/20">
                  <td className="py-1.5 px-2 text-left text-xs text-foreground/60">{label}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06] ${pwB ? "font-semibold" : ""}`}>{d.pw_rate != null ? `${d.pw_rate}%` : "\u2014"}</td>
                  <td className={`py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06] ${!pwB ? "font-semibold" : ""}`}>{d.si_rate != null ? `${d.si_rate}%` : "\u2014"}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-violet-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/60 bg-emerald-500/[0.06]"></td>
                  <td className="py-1.5 px-2 text-right font-mono text-xs text-foreground/40">{(d.pw_pairs ?? d.si_pairs ?? 0).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 bg-secondary/5 border-t border-border/50 space-y-2">
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>PW</strong> = pairwise AI judges (round-robin GPT-5.2, Opus, Gemini).{" "}
          <strong>SI</strong> = single-item AI scoring (Opus 4.6 Thinking, 1-10).{" "}
          <strong>Accuracy</strong> is on the <strong>same {p.intersection?.pairs?.toLocaleString()} pairs</strong> where both methods have verdicts — ensuring a fair per-pair comparison.{" "}
          <strong>Spearman {"\u03C1"}</strong> uses each method's full data (PW: {p.pw_pairs?.toLocaleString()} matches, SI: {p.si_pairs?.toLocaleString()} pairs)
          because ranking quality depends on each method's total output.{" "}
          Both compared against <strong>h1_avg_rating</strong> (averaged human reviewer scores).
        </p>
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          <strong>Why split the metrics:</strong>{" "}
          Accuracy on different pair sets is confounded by difficulty — SI's C(n,2) pairs include more close-quality papers that are harder to judge.
          On the same pairs, the comparison is controlled. Ranking {"\u03C1"} is holistic — in practice, you deploy one method and use all its data to rank papers.
        </p>
        {p.pw_rho != null && p.si_rho != null && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            <strong>Winner: {(p.pw_rho || 0) > (p.si_rho || 0) ? "Pairwise" : "Single-Item"}</strong> on ranking correlation
            (Spearman {"\u03C1"} {p.pw_rho?.toFixed(3)} vs {p.si_rho?.toFixed(3)}).
          </p>
        )}
      </div>
    </div>
  );
}

function DatasetTable({ datasets }) {
  const [expanded, setExpanded] = useState(false);
  if (!datasets?.length) return null;
  return (
    <div>
      <button onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-accent hover:underline mb-2" data-testid="toggle-per-dataset">
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        Per-dataset breakdown ({datasets.length} datasets)
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1 px-2 text-left font-medium">Dataset</th>
                <th className="py-1 px-1.5 text-right font-medium bg-violet-500/[0.06]">PW Acc</th>
                <th className="py-1 px-1.5 text-right font-medium bg-emerald-500/[0.06]">SI Acc</th>
                <th className="py-1 px-1.5 text-right font-medium bg-violet-500/[0.06]">PW {"\u03C1"}</th>
                <th className="py-1 px-1.5 text-right font-medium bg-emerald-500/[0.06]">SI {"\u03C1"}</th>
                <th className="py-1 px-1.5 text-right font-medium text-foreground/50">Pairs</th>
                <th className="py-1 px-1.5 text-right font-medium">Papers</th>
                <th className="py-1 px-1.5 text-center font-medium">Winner</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(d => {
                const pwRho = d.pw?.bt_rho || 0;
                const siRho = d.si?.bt_rho || 0;
                const pwWins = pwRho > siRho;
                const intr = d.intersection || {};
                const dHasSI = (d.si?.total || 0) > 0;
                const dHasIntr = (intr.pairs || 0) > 0;
                const dPwAcc = dHasIntr ? intr.pw_accuracy : d.pw?.accuracy;
                const dSiAcc = dHasIntr ? intr.si_accuracy : (dHasSI ? d.si?.accuracy : null);
                return (
                  <tr key={d.dataset_id} className="border-b border-border/20">
                    <td className="py-1 px-2 text-left font-medium">{d.name || d.dataset_id}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{dPwAcc != null ? `${dPwAcc}%` : "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-emerald-500/[0.06] ${!pwWins && dSiAcc != null ? "font-bold" : ""}`}>{dSiAcc != null ? `${dSiAcc}%` : "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-indigo-500/[0.06]">{d.si_sub?.accuracy != null && d.si_sub.accuracy > 0 ? `${d.si_sub.accuracy}%` : "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-violet-500/[0.06] ${pwWins ? "font-bold" : ""}`}>{d.pw?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className={`py-1 px-1.5 text-right font-mono bg-emerald-500/[0.06] ${!pwWins && d.si?.bt_rho ? "font-bold" : ""}`}>{d.si?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono bg-indigo-500/[0.06]">{d.si_sub?.bt_rho?.toFixed(3) ?? "\u2014"}</td>
                    <td className="py-1 px-1.5 text-right font-mono text-foreground/50">{dHasIntr ? intr.pairs?.toLocaleString() : (d.pw?.total || 0).toLocaleString()}</td>
                    <td className="py-1 px-1.5 text-right font-mono">{d.n_papers}</td>
                    <td className="py-1 px-1.5 text-center">
                      <span className={`text-[9px] font-semibold ${pwWins ? "text-violet-700" : "text-emerald-700"}`}>{pwWins ? "PW" : "SI"}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UnifiedPage({ apiUrl, headerDesc, testId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}${apiUrl}`, { timeout: 90000 })
      .then(r => setData(r.data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiUrl]);

  if (loading) return (
    <div className="space-y-3 animate-pulse">
      {[1, 2, 3].map(i => <div key={i} className="h-24 bg-secondary/30 rounded-lg" />)}
    </div>
  );
  if (error) return <div className="text-sm text-destructive">Error: {error}</div>;
  if (!data || data.status !== "ok") return <div className="text-sm text-muted-foreground">No benchmark data available.</div>;

  const p = data.pooled;

  return (
    <div className="space-y-6" data-testid={testId}>
      <div className="text-[10px] text-muted-foreground mb-1 flex items-center justify-between flex-wrap gap-1">
        <span>{headerDesc}</span>
        <span className="font-mono text-muted-foreground/80">
          {data.n_datasets} datasets
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(() => {
          const hHasIntr = (p.intersection?.pairs || 0) > 0;
          const hHasSI = (p.si_total || 0) > 0;
          const hPwAcc = hHasIntr ? p.intersection.pw_accuracy : p.pw_accuracy;
          const hSiAcc = hHasIntr ? p.intersection.si_accuracy : (hHasSI ? p.si_accuracy : null);
          const hPairs = hHasIntr ? p.intersection.pairs : p.pw_total;
          return (<>
            <div className="border border-border rounded-lg p-3 bg-background">
              <Metric label="PW Accuracy" value={hPwAcc != null ? `${hPwAcc}%` : "\u2014"} sub={`${hPairs?.toLocaleString()} ${hHasIntr ? "same" : "PW"} pairs`} accent={hPwAcc >= (hSiAcc || 0)} />
            </div>
            <div className="border border-border rounded-lg p-3 bg-background">
              <Metric label="SI Accuracy" value={hSiAcc != null ? `${hSiAcc}%` : "\u2014"} sub={hHasSI ? `${hPairs?.toLocaleString()} ${hHasIntr ? "same" : "SI"} pairs` : "no SI data"} accent={hSiAcc != null && hSiAcc > (hPwAcc || 0)} />
            </div>
            <div className="border border-border rounded-lg p-3 bg-background">
              <Metric label="SI Sub-Avg Accuracy" value={p.si_sub_accuracy != null && p.si_sub_accuracy > 0 ? `${p.si_sub_accuracy}%` : "\u2014"} sub="mean of (sig, rig, nov, cla)" accent={false} />
            </div>
          </>);
        })()}
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`PW Spearman \u03C1`} value={p.pw_rho?.toFixed(3) ?? "\u2014"} sub="BT ranking vs h1_avg" accent={(p.pw_rho || 0) >= (p.si_rho || 0)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`SI Spearman \u03C1`} value={p.si_rho?.toFixed(3) ?? "\u2014"} sub="score ranking vs h1_avg" accent={(p.si_rho || 0) > (p.pw_rho || 0)} />
        </div>
        <div className="border border-border rounded-lg p-3 bg-background">
          <Metric label={`SI Sub-Avg \u03C1`} value={p.si_sub_rho?.toFixed(3) ?? "\u2014"} sub="subscore avg vs h1_avg" accent={false} />
        </div>
      </div>

      <ComparisonTable data={data} />
      {(() => {
        // Aggregate BT correlations from per-dataset data
        const ds = data.per_dataset || [];
        const pwKeys = new Set();
        const siKeys = new Set();
        ds.forEach(d => {
          Object.keys(d.pw?.bt_correlations || {}).forEach(k => pwKeys.add(k));
          Object.keys(d.si?.bt_correlations || {}).forEach(k => siKeys.add(k));
        });
        // Pool: average rho/tau across datasets (weighted by presence)
        const pool = (method, key) => {
          const vals = ds.map(d => d[method]?.bt_correlations?.[key]).filter(Boolean);
          if (!vals.length) return null;
          return {
            rho: vals.reduce((s, v) => s + (v.rho || 0), 0) / vals.length,
            tau: vals.reduce((s, v) => s + (v.tau || 0), 0) / vals.filter(v => v.tau != null).length || null,
            desc: vals[0]?.desc,
          };
        };
        const allKeys = [...new Set([...pwKeys, ...siKeys])];
        const pwPooled = {};
        const siPooled = {};
        allKeys.forEach(k => { pwPooled[k] = pool("pw", k); siPooled[k] = pool("si", k); });
        const hasData = Object.values(pwPooled).some(v => v) || Object.values(siPooled).some(v => v);
        return hasData ? <BTCorrelationTable pwCorrs={pwPooled} siCorrs={siPooled} /> : null;
      })()}
      <DatasetTable datasets={data.per_dataset} />
    </div>
  );
}

export function UnifiedCompSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=comp"
    headerDesc={<>PW judges (round-robin) vs SI scoring (Opus 4.6 Thinking) — accuracy on same pairs, ranking on full data. <strong>Comparative GT</strong> (8 ICLR topics, PeerRead ACL 2017).</>}
    testId="unified-comp"
  />;
}

export function UnifiedStanSection() {
  return <UnifiedPage
    apiUrl="/api/validation/unified-benchmark?gt_type=stan"
    headerDesc={<>PW judges vs SI scoring — accuracy on same pairs, ranking on full data. <strong>Standalone GT</strong> (eLife incl. Neuro, MIDL, Qeios, ResearchHub).</>}
    testId="unified-stan"
  />;
}
