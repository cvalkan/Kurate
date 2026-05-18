import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Cell } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const CLUSTER_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
  "#14b8a6", "#e11d48",
];

function SimilarityLandscapeSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [useUmap, setUseUmap] = useState(false);
  const [hoveredPaper, setHoveredPaper] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/similarity-landscape`)
      .then(r => { setData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const chartData = useMemo(() => {
    if (!data?.papers) return [];
    return data.papers.map((p, i) => ({
      x: useUmap ? p.x_umap : p.x,
      y: useUmap ? p.y_umap : p.y,
      title: p.title,
      cluster: p.cluster,
      score: p.score,
      published: p.published,
      id: p.id,
      size: Math.max(40, Math.min(200, (p.score - 1100) / 3)),
    }));
  }, [data, useUmap]);

  const clusterNames = useMemo(() => {
    if (!data?.papers) return {};
    const groups = {};
    data.papers.forEach(p => {
      if (!groups[p.cluster]) groups[p.cluster] = [];
      groups[p.cluster].push(p.title);
    });
    return Object.fromEntries(
      Object.entries(groups).map(([k, titles]) => [
        k,
        `Cluster ${parseInt(k) + 1} (${titles.length} papers)`,
      ])
    );
  }, [data]);

  if (loading) return <div className="text-sm text-muted-foreground py-8 text-center">Loading similarity landscape...</div>;
  if (!data) return <div className="text-sm text-muted-foreground py-8 text-center">No similarity data available yet. Run the experiment first.</div>;

  return (
    <div className="space-y-4" data-testid="similarity-landscape">
      {/* Stats bar */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span><b className="text-foreground">{data.n_papers}</b> papers</span>
        <span><b className="text-foreground">{data.n_pairs?.toLocaleString()}</b> similarity comparisons</span>
        <span><b className="text-foreground">{data.n_clusters}</b> clusters (silhouette {data.silhouette})</span>
        <span>MDS stress: {data.mds_stress}</span>
        <span>Model: {data.model}</span>
        <span>Score range: {data.score_range}</span>
      </div>

      {/* Toggle MDS vs UMAP */}
      {data.has_umap && (
        <div className="flex gap-2">
          <button
            onClick={() => setUseUmap(false)}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${!useUmap ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
          >MDS</button>
          <button
            onClick={() => setUseUmap(true)}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${useUmap ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
          >UMAP</button>
        </div>
      )}

      {/* Scatter plot */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <ResponsiveContainer width="100%" height={500}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis type="number" dataKey="x" tick={false} axisLine={false} />
            <YAxis type="number" dataKey="y" tick={false} axisLine={false} />
            <RechartsTooltip
              cursor={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return (
                  <div className="rounded-lg border border-border bg-popover p-3 shadow-lg text-xs max-w-72">
                    <div className="font-medium text-sm leading-tight">{d.title}</div>
                    <div className="flex gap-3 mt-1.5 text-muted-foreground">
                      <span>Score: <b className="text-foreground">{d.score}</b></span>
                      <span style={{ color: CLUSTER_COLORS[d.cluster % CLUSTER_COLORS.length] }}>
                        {clusterNames[d.cluster] || `Cluster ${d.cluster}`}
                      </span>
                    </div>
                    {d.published && <div className="text-muted-foreground mt-0.5">{d.published}</div>}
                  </div>
                );
              }}
            />
            <Scatter data={chartData} isAnimationActive={false}>
              {chartData.map((entry, idx) => (
                <Cell
                  key={idx}
                  fill={CLUSTER_COLORS[entry.cluster % CLUSTER_COLORS.length]}
                  fillOpacity={0.7}
                  stroke={CLUSTER_COLORS[entry.cluster % CLUSTER_COLORS.length]}
                  strokeWidth={1}
                  r={Math.max(4, Math.min(12, entry.size / 20))}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        {Object.entries(clusterNames).map(([k, name]) => (
          <span key={k} className="flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: CLUSTER_COLORS[parseInt(k) % CLUSTER_COLORS.length] }}
            />
            {name}
          </span>
        ))}
        <span className="text-muted-foreground ml-2">Dot size = Kurate score</span>
      </div>

      {/* Score distribution */}
      {data.score_distribution && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-3">Similarity Score Distribution (1-20)</h3>
          <div className="grid grid-cols-10 gap-1 items-end h-32">
            {Array.from({ length: 20 }, (_, i) => {
              const score = i + 1;
              const count = data.score_distribution[String(score)] || 0;
              const maxCount = Math.max(...Object.values(data.score_distribution));
              const height = maxCount > 0 ? (count / maxCount) * 100 : 0;
              return (
                <div key={score} className="flex flex-col items-center gap-0.5">
                  <span className="text-[9px] text-muted-foreground">{count || ""}</span>
                  <div
                    className="w-full rounded-t bg-accent/60"
                    style={{ height: `${height}%`, minHeight: count > 0 ? 2 : 0 }}
                  />
                  <span className="text-[9px] text-muted-foreground">{score}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Paper list by cluster */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-3">Papers by Cluster</h3>
        <div className="space-y-4">
          {Object.entries(clusterNames).map(([k, name]) => {
            const clusterPapers = (data.papers || [])
              .filter(p => p.cluster === parseInt(k))
              .sort((a, b) => b.score - a.score);
            return (
              <div key={k}>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: CLUSTER_COLORS[parseInt(k) % CLUSTER_COLORS.length] }}
                  />
                  <span className="text-xs font-medium">{name}</span>
                </div>
                <div className="space-y-0.5 ml-3.5">
                  {clusterPapers.map(p => (
                    <div key={p.id} className="flex items-baseline gap-2 text-xs">
                      <span className="text-muted-foreground w-8 text-right shrink-0">{p.score}</span>
                      <a
                        href={`/paper/${p.id}`}
                        className="text-foreground hover:text-accent truncate"
                        title={p.title}
                      >
                        {p.title}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default SimilarityLandscapeSection;
