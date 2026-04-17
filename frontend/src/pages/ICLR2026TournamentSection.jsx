import { useState, useEffect } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";
import { DatasetView } from "./ValidationPage";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ICLR2026TournamentSection() {
  const [progress, setProgress] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/validation/iclr2026-tournament`)
      .then(r => setProgress(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Build a minimal dataset object matching what DatasetView expects
  const ds = {
    dataset_id: "iclr-2026-validation",
    name: "ICLR 2026 (58K)",
    description: "3,912 ICLR 2026 papers. Round-robin judging by GPT-5.4, Claude Opus 4.6, Gemini 3 Pro. Anonymized abstracts + AI summaries (scores stripped).",
    source: "ICLR",
    papers: 3912,
  };

  return (
    <div data-testid="iclr2026-tournament">
      {/* Progress bar */}
      {!loading && progress?.total_matches > 0 && (
        <div className="space-y-1 mb-4">
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>{progress.total_matches.toLocaleString()} / {progress.target_matches.toLocaleString()} matches</span>
            <span className="font-mono">{progress.progress_pct}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-secondary/30 overflow-hidden">
            <div className="h-full rounded-full bg-accent transition-all duration-1000" style={{ width: `${progress.progress_pct}%` }} />
          </div>
        </div>
      )}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground animate-pulse p-4">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading...
        </div>
      )}

      {/* Reuse the exact same DatasetView as other tournaments */}
      <DatasetView ds={ds} isAdmin={false} hideHeader />
    </div>
  );
}
