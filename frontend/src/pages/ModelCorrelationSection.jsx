import { useState, useEffect } from "react";
import axios from "axios";
import { BarChart3, Info } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const JUDGE_COLORS = {
  "Opus 4.6": "#a78bfa", "Opus 4.5": "#8b5cf6", "GPT-5.2": "#3b82f6", "Gemini 3 Pro": "#f59e0b",
};

function AgreementMatrix({ pairs, judges, title, subtitle }) {
  if (!pairs || !pairs.length) return null;

  // Build matrix
  const matrix = {};
  for (const p of pairs) {
    matrix[`${p.judge1}|${p.judge2}`] = p;
    matrix[`${p.judge2}|${p.judge1}`] = p;
  }

  const allAgreements = pairs.map(p => p.agreement);
  const maxAg = Math.max(...allAgreements);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-secondary/10 border-b border-border">
        <h3 className="text-xs font-medium flex items-center gap-1.5"><BarChart3 className="h-3 w-3" /> {title}</h3>
        {subtitle && <p className="text-[10px] text-muted-foreground mt-0.5">{subtitle}</p>}
      </div>
      <div className="p-3 overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border text-[10px]">
              <th className="text-left py-1.5 pr-3 font-medium"></th>
              {judges.map(j => (
                <th key={j} className="text-center py-1.5 px-2 font-medium" style={{ color: JUDGE_COLORS[j] }}>{j}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {judges.map(j1 => (
              <tr key={j1} className="border-b border-border/30">
                <td className="py-2 pr-3 font-medium">{j1}</td>
                {judges.map(j2 => {
                  if (j1 === j2) return <td key={j2} className="text-center py-2 px-2 bg-secondary/10 text-muted-foreground/30">—</td>;
                  const cell = matrix[`${j1}|${j2}`];
                  if (!cell) return <td key={j2} className="text-center py-2 px-2 text-muted-foreground/30">—</td>;
                  const intensity = Math.min(cell.agreement / Math.max(maxAg, 1), 1);
                  return (
                    <td key={j2} className="text-center py-2 px-2 font-mono" style={{ backgroundColor: `rgba(34, 197, 94, ${intensity * 0.25})` }}>
                      <div className={cell.agreement >= maxAg - 1 ? "text-green-600 font-semibold" : ""}>{cell.agreement}%</div>
                      <div className="text-[9px] text-muted-foreground">{cell.same_pairs}p</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ModelCorrelationSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("pooled");

  useEffect(() => {
    axios.get(`${API}/api/validation/model-correlation-analysis/results`, { timeout: 120000 })
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-secondary/20 rounded-lg animate-pulse" />)}</div>;
  if (!data || data.status !== "ok") return <div className="text-center py-12 text-muted-foreground text-sm">No model correlation data available.</div>;

  const { pooled, by_dataset, by_format, judges } = data;
  const datasets = Object.keys(by_dataset).sort();
  const formats = Object.keys(by_format).sort();

  return (
    <div className="space-y-6" data-testid="model-correlation-analysis">
      <div className="border border-blue-200 rounded-lg p-4 bg-blue-50/30 text-xs text-blue-900 space-y-2">
        <h3 className="font-medium text-sm flex items-center gap-1.5"><Info className="h-3.5 w-3.5" /> About This Analysis</h3>
        <p>How often do different judge models agree when evaluating the <strong>same paper pair</strong>? Higher agreement indicates the models are measuring similar qualities. Low agreement suggests subjective or noisy judgments.</p>
        <p>All comparisons use <strong>same-pair data only</strong> — each cell shows the agreement rate on pairs where both judges in the pair evaluated the same papers under the same input format.</p>
      </div>

      {/* Tab navigation */}
      <div className="flex gap-2 border-b border-border pb-1">
        {[
          { id: "pooled", label: "Aggregate" },
          { id: "by_dataset", label: "By Dataset" },
          { id: "by_format", label: "By Input Format" },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors ${tab === t.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary/30"}`}
            data-testid={`corr-tab-${t.id}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "pooled" && (
        <AgreementMatrix pairs={pooled} judges={judges}
          title="Pairwise Agreement — All Datasets & Formats"
          subtitle="Percentage of same-pair verdicts where both judges chose the same winner. Aggregated across all datasets and input formats." />
      )}

      {tab === "by_dataset" && (
        <div className="space-y-4">
          {datasets.map(ds => (
            <AgreementMatrix key={ds} pairs={by_dataset[ds]} judges={judges}
              title={ds.replace("iclr-", "ICLR ").replace("elife-", "eLife ").replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
              subtitle={`Same-pair agreement for ${ds}`} />
          ))}
        </div>
      )}

      {tab === "by_format" && (
        <div className="space-y-4">
          {formats.map(fmt => (
            <AgreementMatrix key={fmt} pairs={by_format[fmt]} judges={judges}
              title={fmt}
              subtitle={`Same-pair agreement under ${fmt} input format`} />
          ))}
        </div>
      )}
    </div>
  );
}
