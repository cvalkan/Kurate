import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FlaskConical, RefreshCw, ArrowUpDown, BarChart3 } from "lucide-react";
import { toast } from "sonner";
import { CorrelationSection } from "@/components/CorrelationSection";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export function AdminExperiment() {
  const [experiment, setExperiment] = useState(null);
  const [experimentSort, setExperimentSort] = useState("standard_rank");
  const [predictionMatches, setPredictionMatches] = useState(50);
  const [predictionLoading, setPredictionLoading] = useState(false);

  // Prediction correlation data
  const [predAbsData, setPredAbsData] = useState(null);
  const [predFtData, setPredFtData] = useState(null);
  const [corrLoading, setCorrLoading] = useState(true);

  const fetchCorrelation = useCallback(async () => {
    try {
      const [predAbsRes, predFtRes] = await Promise.all([
        axios.get(`${API}/api/model-correlation`, { params: { mode: "prediction" } }),
        axios.get(`${API}/api/model-correlation`, { params: { mode: "prediction-fulltext" } }),
      ]);
      setPredAbsData(predAbsRes.data);
      setPredFtData(predFtRes.data);
    } catch (err) {
      console.error("Failed to fetch prediction correlation:", err);
    } finally {
      setCorrLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCorrelation();
  }, [fetchCorrelation]);

  const loadComparison = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/experiment-comparison`, { headers: getAdminHeaders(), params: { category: "cs.RO" } });
      setExperiment(res.data);
    } catch (err) {
      toast.error("Failed to load");
    }
  };

  const runPrediction = async (useFullText) => {
    setPredictionLoading(true);
    try {
      await axios.post(`${API}/api/admin/run-prediction`, {
        num_matches: predictionMatches, category: "cs.RO", use_full_text: useFullText,
      }, { headers: getAdminHeaders() });
      toast.success(`Started ${predictionMatches} ${useFullText ? "full-text" : "abstract-only"} prediction matches`);
    } catch (err) {
      toast.error("Failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setPredictionLoading(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-experiment">
      <div>
        <h2 className="font-heading text-lg font-medium mb-1">Gap Score Experiment</h2>
        <p className="text-xs text-muted-foreground max-w-2xl">
          Based on Drazen Prelec's method. Compares standard rankings (full-text, "which is better?") with prediction rankings (abstract-only, "which would the crowd pick?").
          Papers that rank higher in the standard tournament than predicted may be <span className="text-foreground font-medium">hidden gems</span>.
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="number" min="1" max="500"
          value={predictionMatches}
          onChange={(e) => setPredictionMatches(Math.min(500, Math.max(1, Number(e.target.value) || 50)))}
          className="w-20 h-10 text-center font-mono text-sm"
        />
        <Button onClick={() => runPrediction(false)} disabled={predictionLoading} variant="outline" className="gap-2">
          <FlaskConical className="h-4 w-4" />
          Predict (Abstract)
        </Button>
        <Button onClick={() => runPrediction(true)} disabled={predictionLoading} className="gap-2">
          <FlaskConical className="h-4 w-4" />
          Predict (Full Text)
        </Button>
        <Button variant="outline" onClick={loadComparison} className="gap-2">
          <RefreshCw className="h-4 w-4" />
          Load Comparison
        </Button>
      </div>

      {/* Comparison Table */}
      {experiment && (
        <div>
          <div className="flex items-center gap-3 mb-3 text-xs text-muted-foreground">
            <span>Standard: <span className="font-mono text-foreground">{experiment.standard_matches}</span> matches</span>
            <span>Prediction (abstract): <span className="font-mono text-foreground">{experiment.prediction_matches}</span> matches</span>
            <span>Prediction (full text): <span className="font-mono text-foreground">{experiment.prediction_ft_matches || 0}</span> matches</span>
          </div>

          {experiment.prediction_matches === 0 ? (
            <div className="p-6 text-center text-muted-foreground border border-border rounded-lg">
              <FlaskConical className="h-8 w-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No prediction matches yet. Run the prediction tournament to generate data.</p>
            </div>
          ) : (
            <div className="border border-border rounded-lg overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-secondary/50 border-b border-border">
                    {[
                      { key: "standard_rank", label: "Std #" },
                      { key: "title", label: "Paper" },
                      { key: "standard_score", label: "Std Score" },
                      { key: "standard_win_rate", label: "Std Win%" },
                      { key: "standard_matches", label: "Std Mtch" },
                      { key: "prediction_rank", label: "Abs #" },
                      { key: "prediction_win_rate", label: "Abs Win%" },
                      { key: "prediction_matches", label: "Abs Mtch" },
                      { key: "rank_delta", label: "\u0394 Abs" },
                      { key: "pred_ft_rank", label: "FT #" },
                      { key: "pred_ft_win_rate", label: "FT Win%" },
                      { key: "pred_ft_matches", label: "FT Mtch" },
                      { key: "rank_delta_ft", label: "\u0394 FT" },
                    ].map(col => (
                      <th key={col.key}
                        className="px-2 py-2.5 text-left font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap"
                        onClick={() => setExperimentSort(col.key)}
                      >
                        <span className="inline-flex items-center gap-1">
                          {col.label}
                          {experimentSort === col.key && <ArrowUpDown className="h-3 w-3" />}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...experiment.papers]
                    .filter(p => p.standard_matches > 0 || p.prediction_matches > 0)
                    .sort((a, b) => {
                      const key = experimentSort;
                      if (key === "title") return a.title.localeCompare(b.title);
                      return a[key] - b[key];
                    })
                    .map(p => {
                      const delta = p.rank_delta;
                      const deltaFt = p.rank_delta_ft;
                      const isGem = delta > 5 || deltaFt > 5;
                      const isOverhyped = delta < -5 || deltaFt < -5;
                      return (
                        <tr key={p.id} className={`border-b border-border/50 ${isGem ? "bg-green-50/50" : isOverhyped ? "bg-red-50/30" : ""}`}>
                          <td className="px-2 py-2 font-mono">{p.standard_rank}</td>
                          <td className="px-2 py-2 max-w-[200px] truncate font-medium" title={p.title}>{p.title}</td>
                          <td className="px-2 py-2 font-mono">{p.standard_score}</td>
                          <td className="px-2 py-2 font-mono">{p.standard_win_rate}%</td>
                          <td className="px-2 py-2 font-mono text-muted-foreground">{p.standard_matches}</td>
                          <td className="px-2 py-2 font-mono">{p.prediction_matches > 0 ? p.prediction_rank : "\u2014"}</td>
                          <td className="px-2 py-2 font-mono">{p.prediction_matches > 0 ? `${p.prediction_win_rate}%` : "\u2014"}</td>
                          <td className="px-2 py-2 font-mono text-muted-foreground">{p.prediction_matches || "\u2014"}</td>
                          <td className={`px-2 py-2 font-mono font-medium ${delta > 5 ? "text-green-700" : delta < -5 ? "text-red-600" : "text-muted-foreground"}`}>
                            {p.prediction_matches > 0 ? (delta > 0 ? `+${delta}` : delta) : "\u2014"}
                          </td>
                          <td className="px-2 py-2 font-mono">{p.pred_ft_matches > 0 ? p.pred_ft_rank : "\u2014"}</td>
                          <td className="px-2 py-2 font-mono">{p.pred_ft_matches > 0 ? `${p.pred_ft_win_rate}%` : "\u2014"}</td>
                          <td className="px-2 py-2 font-mono text-muted-foreground">{p.pred_ft_matches || "\u2014"}</td>
                          <td className={`px-2 py-2 font-mono font-medium ${deltaFt > 5 ? "text-green-700" : deltaFt < -5 ? "text-red-600" : "text-muted-foreground"}`}>
                            {p.pred_ft_matches > 0 ? (deltaFt > 0 ? `+${deltaFt}` : deltaFt) : "\u2014"}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}

          {experiment.prediction_matches > 0 && (
            <div className="mt-3 text-[11px] text-muted-foreground">
              <span className="inline-block w-3 h-3 bg-green-50 border border-green-200 rounded mr-1" /> {"\u0394"} &gt; +5: Potential hidden gem &nbsp;
              <span className="inline-block w-3 h-3 bg-red-50 border border-red-200 rounded mr-1" /> {"\u0394"} &lt; -5: Potentially overhyped
            </div>
          )}
        </div>
      )}

      {/* Prediction Correlation Analysis (moved from CorrelationPage) */}
      <div className="border-t border-border pt-6 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="h-4 w-4 text-accent" />
          <h2 className="font-heading text-lg font-medium">Prediction Model Analysis</h2>
        </div>
        {corrLoading ? (
          <div className="space-y-3">
            {[...Array(2)].map((_, i) => <div key={i} className="h-16 bg-secondary/30 rounded-lg animate-pulse" />)}
          </div>
        ) : (
          <>
            <CorrelationSection
              sectionData={predAbsData}
              title="Prediction Tournament (Abstract Only)"
              description='Abstract-only: "Which paper would the scientific crowd consider more impactful?"'
            />
            <CorrelationSection
              sectionData={predFtData}
              title="Prediction Tournament (Full Text)"
              description='Full-text with prediction prompt: "Which paper would the crowd consider more impactful?"'
            />
          </>
        )}
      </div>
    </div>
  );
}
