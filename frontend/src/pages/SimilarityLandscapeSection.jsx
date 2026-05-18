import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Cell, BarChart, Bar } from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const CLUSTER_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
  "#14b8a6", "#e11d48",
];

// Score → dot radius (5 tiers)
function scoreToRadius(score) {
  if (score >= 1500) return 10;  // top tier
  if (score >= 1400) return 8;
  if (score >= 1300) return 6;
  if (score >= 1200) return 4.5;
  return 3;                       // below average
}

function SimilarityLandscapeSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [useUmap, setUseUmap] = useState(false);
  const [nClusters, setNClusters] = useState(null);

  useEffect(() => {
    axios.get(`${API}/api/similarity-landscape`)
      .then(r => { setData(r.data); setNClusters(r.data.n_clusters); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  // Re-cluster client-side with different K using simple k-means
  const clustered = useMemo(() => {
    if (!data?.papers || !nClusters) return data?.papers || [];
    const papers = data.papers;
    const k = nClusters;

    // Use pre-generated labels if available
    if (data.cluster_labels?.[String(k)]) {
      const labels = data.cluster_labels[String(k)];
      return papers.map((p, i) => ({ ...p, cluster: labels[i] }));
    }

    if (k === data.n_clusters) return papers; // use server default clusters

    // Simple k-means on 2D coords
    const coords = papers.map(p => [useUmap ? p.x_umap : p.x, useUmap ? p.y_umap : p.y]);
    // Initialize centroids from random papers
    const idxs = [];
    while (idxs.length < k) {
      const r = Math.floor(Math.random() * papers.length);
      if (!idxs.includes(r)) idxs.push(r);
    }
    let centroids = idxs.map(i => [...coords[i]]);
    let labels = new Array(papers.length).fill(0);

    for (let iter = 0; iter < 50; iter++) {
      // Assign
      for (let i = 0; i < papers.length; i++) {
        let minD = Infinity;
        for (let c = 0; c < k; c++) {
          const d = (coords[i][0] - centroids[c][0]) ** 2 + (coords[i][1] - centroids[c][1]) ** 2;
          if (d < minD) { minD = d; labels[i] = c; }
        }
      }
      // Update centroids
      const sums = Array.from({ length: k }, () => [0, 0, 0]);
      for (let i = 0; i < papers.length; i++) {
        sums[labels[i]][0] += coords[i][0];
        sums[labels[i]][1] += coords[i][1];
        sums[labels[i]][2] += 1;
      }
      centroids = sums.map(s => s[2] > 0 ? [s[0] / s[2], s[1] / s[2]] : [0, 0]);
    }
    return papers.map((p, i) => ({ ...p, cluster: labels[i] }));
  }, [data, nClusters, useUmap]);

  const chartData = useMemo(() => {
    if (!clustered.length) return [];
    return clustered.map(p => ({
      x: useUmap ? p.x_umap : p.x,
      y: useUmap ? p.y_umap : p.y,
      title: p.title,
      cluster: p.cluster,
      score: p.score,
      published: p.published,
      id: p.id,
      r: scoreToRadius(p.score),
    }));
  }, [clustered, useUmap]);

  const clusterNames = useMemo(() => {
    // Use pre-generated LLM titles if available for this K
    if (data?.cluster_titles?.[String(nClusters)]) {
      return data.cluster_titles[String(nClusters)];
    }
    // Fallback: keyword extraction
    const groups = {};
    clustered.forEach(p => {
      if (!groups[p.cluster]) groups[p.cluster] = [];
      groups[p.cluster].push(p.title);
    });
    const stopwords = new Set(["a","an","the","of","in","for","and","with","to","on","from","by","as","is","at","via","its","are","or","can","do","how","into","that","this","using","based","towards","toward","beyond","through","between"]);
    const allWords = {};
    Object.values(groups).flat().forEach(t => {
      t.toLowerCase().replace(/[^a-z0-9\s]/g, "").split(/\s+/).filter(w => w.length > 2 && !stopwords.has(w))
        .forEach(w => { allWords[w] = (allWords[w] || 0) + 1; });
    });
    return Object.fromEntries(
      Object.entries(groups).map(([k, titles]) => {
        const wordCounts = {};
        titles.forEach(t => {
          t.toLowerCase().replace(/[^a-z0-9\s]/g, "").split(/\s+/).filter(w => w.length > 2 && !stopwords.has(w))
            .forEach(w => { wordCounts[w] = (wordCounts[w] || 0) + 1; });
        });
        const scored = Object.entries(wordCounts)
          .map(([w, c]) => [w, c / Math.max(allWords[w] || 1, 1) * Math.log(1 + c)])
          .sort((a, b) => b[1] - a[1]);
        const topWords = scored.slice(0, 3).map(([w]) => w[0].toUpperCase() + w.slice(1));
        return [k, `${topWords.join(", ")} (${titles.length})`];
      })
    );
  }, [data, clustered, nClusters]);

  const histogramData = useMemo(() => {
    if (!data?.score_distribution) return [];
    return Array.from({ length: 20 }, (_, i) => ({
      score: i + 1,
      count: data.score_distribution[String(i + 1)] || 0,
    }));
  }, [data]);

  if (loading) return <div className="text-sm text-muted-foreground py-8 text-center">Loading similarity landscape...</div>;
  if (!data) return <div className="text-sm text-muted-foreground py-8 text-center">No similarity data available yet. Run the experiment first.</div>;

  return (
    <div className="space-y-4" data-testid="similarity-landscape">
      {/* Stats bar */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span><b className="text-foreground">{data.n_papers}</b> papers</span>
        <span><b className="text-foreground">{data.n_pairs?.toLocaleString()}</b> similarity comparisons</span>
        <span><b className="text-foreground">{nClusters}</b> clusters (silhouette {data.silhouette})</span>
        <span>Model: {data.model}</span>
        <span>Score range: {data.score_range}</span>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-4 items-center">
        {data.has_umap && (
          <div className="flex gap-1.5">
            <button onClick={() => setUseUmap(false)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${!useUmap ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >MDS</button>
            <button onClick={() => setUseUmap(true)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${useUmap ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >UMAP</button>
          </div>
        )}
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Clusters:</span>
          {[3, 5, 7, 10].map(k => (
            <button key={k} onClick={() => setNClusters(k)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${nClusters === k ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >{k}</button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground ml-2">
          <span>Dot size = score:</span>
          {[{label: "≥1500", r: 10}, {label: "1400", r: 8}, {label: "1300", r: 6}, {label: "1200", r: 4.5}, {label: "<1200", r: 3}].map(t => (
            <span key={t.label} className="flex items-center gap-0.5">
              <span className="inline-block rounded-full bg-muted-foreground/40" style={{ width: t.r * 2, height: t.r * 2 }} />
              <span>{t.label}</span>
            </span>
          ))}
        </div>
      </div>

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
            <Scatter data={chartData} isAnimationActive={false}
              shape={(props) => {
                const { cx, cy, payload } = props;
                const r = payload.r || 5;
                const color = CLUSTER_COLORS[payload.cluster % CLUSTER_COLORS.length];
                return <circle cx={cx} cy={cy} r={r} fill={color} fillOpacity={0.7} stroke={color} strokeWidth={1} />;
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Cluster legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        {Object.entries(clusterNames).map(([k, name]) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: CLUSTER_COLORS[parseInt(k) % CLUSTER_COLORS.length] }} />
            {name}
          </span>
        ))}
      </div>

      {/* Score distribution — proper bar chart */}
      {histogramData.length > 0 && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-3">Similarity Score Distribution (1-20)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={histogramData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.15} vertical={false} />
              <XAxis dataKey="score" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} width={40} />
              <RechartsTooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0]?.payload;
                  return (
                    <div className="rounded-lg border border-border bg-popover px-2.5 py-1.5 shadow-lg text-xs">
                      Score {d.score}: <b>{d.count}</b> pairs ({(d.count / data.n_pairs * 100).toFixed(1)}%)
                    </div>
                  );
                }}
              />
              <Bar dataKey="count" fill="#3b82f6" opacity={0.7} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Paper list by cluster */}
      <div className="border border-border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-medium mb-3">Papers by Cluster</h3>
        <div className="space-y-4">
          {Object.entries(clusterNames).map(([k, name]) => {
            const clusterPapers = clustered
              .filter(p => p.cluster === parseInt(k))
              .sort((a, b) => b.score - a.score);
            return (
              <div key={k}>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CLUSTER_COLORS[parseInt(k) % CLUSTER_COLORS.length] }} />
                  <span className="text-xs font-medium">{name}</span>
                </div>
                <div className="space-y-0.5 ml-3.5">
                  {clusterPapers.map(p => (
                    <div key={p.id} className="flex items-baseline gap-2 text-xs">
                      <span className="text-muted-foreground w-8 text-right shrink-0">{p.score}</span>
                      <a href={`/paper/${p.id}`} className="text-foreground hover:text-accent truncate" title={p.title}>
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
