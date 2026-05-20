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

function SimilarityLandscapeSection({ category = "cs.AI" }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [useUmap, setUseUmap] = useState(false);
  const [nClusters, setNClusters] = useState(null);
  const [embMode, setEmbMode] = useState(null); // null | "abstract" | "combined"

  useEffect(() => {
    const url = category === "cs.AI"
      ? `${API}/api/similarity-landscape`
      : `${API}/api/similarity-landscape/${category}`;
    axios.get(url, { params: { _t: Date.now() } })
      .then(r => {
        setData(r.data);
        setNClusters(r.data.n_clusters);
        if (r.data.has_jaccard_stable && !r.data.cluster_labels) setEmbMode("jaccard_stable");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [category]);

  // Update default K when switching view mode
  useEffect(() => {
    if (!data) return;
    const bestK = embMode === "abstract" ? data.emb_abstract_best_k
      : embMode === "combined" ? data.emb_combined_best_k
      : embMode === "tags" ? data.emb_tags_best_k
      : embMode === "tags_consolidated" ? data.emb_tags_consolidated_best_k
      : embMode === "jaccard_laplacian" ? data.jaccard_laplacian_best_k
      : embMode === "jaccard_lap14" ? data.jaccard_lap14_best_k
      : embMode === "jaccard_stable" ? data.jaccard_stable_best_k
      : embMode === "jaccard_lap10" ? data.jaccard_lap10_best_k
      : embMode === "jaccard_ce" ? data.jaccard_ce_best_k
      : embMode === "jaccard_ce10" ? data.jaccard_ce10_best_k
      : embMode === "jaccard_pmi50" ? data.jaccard_pmi50_best_k
      : embMode === "jaccard_pmi60" ? data.jaccard_pmi60_best_k
      : embMode?.startsWith("jaccard_") ? data[`${embMode}_best_k`]
      : data.n_clusters;
    if (bestK) setNClusters(bestK);
  }, [data, embMode, useUmap]);

  // Re-cluster: use precomputed labels matching the current view (MDS vs UMAP)
  const clustered = useMemo(() => {
    if (!data?.papers || !nClusters) return data?.papers || [];
    const papers = data.papers;
    const k = nClusters;

    // Use cluster labels matching the current view
    const labelsKey = embMode === "abstract" ? "emb_abstract_cluster_labels"
      : embMode === "combined" ? "emb_combined_cluster_labels"
      : embMode === "tags" ? "emb_tags_cluster_labels"
      : embMode === "tags_consolidated" ? "emb_tags_consolidated_cluster_labels"
      : embMode === "jaccard_incr" ? "jaccard_incr_cluster_labels"
      : embMode?.startsWith("jaccard_") ? `${embMode}_cluster_labels`
      : useUmap ? "umap_cluster_labels" : "cluster_labels";
    const labelsSource = data[labelsKey];
    if (labelsSource?.[String(k)]) {
      const labels = labelsSource[String(k)];
      return papers.map((p, i) => ({ ...p, cluster: labels[i] }));
    }

    if (k === data.n_clusters) return papers;

    // Simple k-means fallback on current view's 2D coords
    const coords = papers.map(p => {
      if (embMode === "abstract") return [p.x_emb_abstract || p.x, p.y_emb_abstract || p.y];
      if (embMode === "combined") return [p.x_emb_combined || p.x, p.y_emb_combined || p.y];
      if (embMode === "tags") return [p.x_emb_tags || p.x, p.y_emb_tags || p.y];
      if (embMode === "tags_consolidated") return [p.x_emb_tags_consolidated || p.x, p.y_emb_tags_consolidated || p.y];
      if (embMode === "jaccard_incr") return [p.x_jaccard_incr || p.x, p.y_jaccard_incr || p.y];
      if (embMode?.startsWith("jaccard_")) {
        const key = embMode;
        return [p[`x_${key}`] || p.x, p[`y_${key}`] || p.y];
      }
      return [useUmap ? p.x_umap : p.x, useUmap ? p.y_umap : p.y];
    });
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
  }, [data, nClusters, useUmap, embMode]);

  const chartData = useMemo(() => {
    if (!clustered.length) return [];
    return clustered.map(p => ({
      x: embMode === "abstract" ? p.x_emb_abstract : embMode === "combined" ? p.x_emb_combined : embMode === "tags" ? p.x_emb_tags : embMode === "tags_consolidated" ? p.x_emb_tags_consolidated : embMode?.startsWith("jaccard_") ? (p[`x_${embMode}`] || p.x) : useUmap ? p.x_umap : p.x,
      y: embMode === "abstract" ? p.y_emb_abstract : embMode === "combined" ? p.y_emb_combined : embMode === "tags" ? p.y_emb_tags : embMode === "tags_consolidated" ? p.y_emb_tags_consolidated : embMode?.startsWith("jaccard_") ? (p[`y_${embMode}`] || p.y) : useUmap ? p.y_umap : p.y,
      title: p.title,
      cluster: p.cluster,
      score: p.score,
      published: p.published,
      id: p.id,
      r: scoreToRadius(p.score),
      tags: embMode?.startsWith("jaccard_") ? (p.tags_incremental || p.tags) : p.tags,
    }));
  }, [clustered, useUmap, embMode]);

  const clusterNames = useMemo(() => {
    // Use pre-generated LLM titles matching the current view
    const titlesSource = embMode === "jaccard_incr" ? data?.jaccard_incr_cluster_titles
      : embMode === "jaccard_laplacian" ? data?.jaccard_laplacian_cluster_titles
      : embMode?.startsWith("jaccard_") ? data?.[`${embMode}_cluster_titles`]
      : embMode ? null
      : useUmap ? data?.umap_cluster_titles : data?.cluster_titles;
    if (titlesSource?.[String(nClusters)]) {
      return titlesSource[String(nClusters)];
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
        <span><b className="text-foreground">{nClusters}</b> clusters (silhouette {
          (() => {
            const methodKey = embMode === "abstract" ? "emb_abstract"
              : embMode === "combined" ? "emb_combined"
              : embMode === "tags" ? "emb_tags"
              : embMode === "tags_consolidated" ? "emb_tags_consolidated"
              : embMode === "jaccard_incr" ? "jaccard_incr"
              : embMode?.startsWith("jaccard_") ? embMode
              : useUmap ? "umap" : "mds";
            const perK = data.silhouettes_per_k?.[methodKey];
            if (perK && perK[String(nClusters)] !== undefined) return perK[String(nClusters)];
            if (embMode === "abstract") return data.emb_abstract_silhouette;
            if (embMode === "combined") return data.emb_combined_silhouette;
            if (embMode === "tags") return data.emb_tags_silhouette;
            return data.silhouette;
          })()
        })</span>
        <span>Model: {data.model}</span>
        <span>Score range: {data.score_range}</span>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-4 items-center">
        <div className="flex gap-1.5">
          {(data.has_umap || data.cluster_labels) && <button onClick={() => { setUseUmap(false); setEmbMode(null); }}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${!useUmap && !embMode ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
          >MDS</button>}
          {data.has_umap && <button onClick={() => { setUseUmap(true); setEmbMode(null); }}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${useUmap && !embMode ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
          >UMAP</button>}
          {data.has_embeddings && <>
            <button onClick={() => { setUseUmap(false); setEmbMode("abstract"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "abstract" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Emb: Abstract</button>
            <button onClick={() => { setUseUmap(false); setEmbMode("combined"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "combined" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Emb: Summary</button>
          </>}
          {data.has_tag_embeddings &&
            <button onClick={() => { setUseUmap(false); setEmbMode("tags"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "tags" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Emb: Tags</button>
          }
          {data.has_consolidated_tags &&
            <button onClick={() => { setUseUmap(false); setEmbMode("tags_consolidated"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "tags_consolidated" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Emb: Tags (consolidated)</button>
          }
          {data.has_jaccard_incr &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_incr"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_incr" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: All</button>
          }
          {data.has_jaccard_per_key && ["topics", "methods", "domains", "concepts"].map(key =>
            <button key={key} onClick={() => { setUseUmap(false); setEmbMode(`jaccard_${key}`); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === `jaccard_${key}` ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: {key.charAt(0).toUpperCase() + key.slice(1)}</button>
          )}
          {data.has_jaccard_laplacian &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_laplacian"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_laplacian" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: Top 100</button>
          }
          {data.has_jaccard_lap14 &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_lap14"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_lap14" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: Top 14</button>
          }
          {data.has_jaccard_stable &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_stable"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_stable" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: Stable ({data.stable_cutoff || Object.keys(data.stable_selected_tags || {}).length})</button>
          }
          {data.has_jaccard_lap10 &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_lap10"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_lap10" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >Jaccard: Top 10</button>
          }
          {data.has_jaccard_ce &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_ce"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_ce" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >CE: Stable ({data.ce_stable_cutoff})</button>
          }
          {data.has_jaccard_ce10 &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_ce10"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_ce10" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >CE: Top 10</button>
          }
          {data.has_jaccard_pmi50 &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_pmi50"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_pmi50" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >PMI: Top 50</button>
          }
          {data.has_jaccard_pmi60 &&
            <button onClick={() => { setUseUmap(false); setEmbMode("jaccard_pmi60"); }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${embMode === "jaccard_pmi60" ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
            >PMI: Stable (60)</button>
          }
        </div>
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
                const tags = d.tags || {};
                // Handle both flat tags ({"tags": [...]}) and categorized ({"topics": [...], ...})
                const allTagsRaw = Array.isArray(tags.tags) ? tags.tags
                  : [...(tags.topics || []), ...(tags.methods || []), ...(tags.domains || []), ...(tags.concepts || [])];
                const seen = new Set();
                const allTags = allTagsRaw.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; });
                // Determine which tags are "active" for the current view
                const activeTagSet = new Set(
                  embMode === "jaccard_lap14" ? (data.laplacian14_tag_set || [])
                  : embMode === "jaccard_lap10" ? (data.lap10_tag_set || [])
                  : embMode === "jaccard_laplacian" ? (data.laplacian100_tag_set || [])
                  : embMode === "jaccard_stable" ? (data.stable_tag_set || [])
                  : embMode === "jaccard_ce" ? (data.ce_tag_set || [])
                  : embMode === "jaccard_ce10" ? (data.ce10_tag_set || [])
                  : embMode === "jaccard_pmi50" ? (data.pmi50_tag_set || [])
                  : embMode === "jaccard_pmi60" ? (data.pmi60_tag_set || [])
                  : []
                );
                return (
                  <div className="rounded-lg border border-border bg-popover p-3 shadow-lg text-xs max-w-80">
                    <div className="font-medium text-sm leading-tight">{d.title}</div>
                    <div className="flex gap-3 mt-1.5 text-muted-foreground">
                      <span>Score: <b className="text-foreground">{d.score}</b></span>
                      <span style={{ color: CLUSTER_COLORS[d.cluster % CLUSTER_COLORS.length] }}>
                        {clusterNames[d.cluster] || `Cluster ${d.cluster}`}
                      </span>
                    </div>
                    {allTags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {allTags.slice(0, 12).map((tag, i) => {
                          const isActive = activeTagSet.size > 0 && activeTagSet.has(tag);
                          return (
                            <span key={i} className={`px-1.5 py-0.5 rounded text-[10px] ${isActive ? "bg-purple-500/20 text-purple-700 dark:text-purple-300 font-medium ring-1 ring-purple-400/30" : "bg-muted text-muted-foreground"}`}>{tag}</span>
                          );
                        })}
                      </div>
                    )}
                    {d.published && <div className="text-muted-foreground mt-1">{d.published}</div>}
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

      {/* Procrustes stability chart — switches between Laplacian and PMI data */}
      {(() => {
        const isPmi = embMode?.startsWith("jaccard_pmi");
        const pData = isPmi ? data.procrustes_pmi_data : data.procrustes_data;
        const cutoff = isPmi ? data.pmi_stable_cutoff : data.stable_cutoff;
        if (!pData || !pData.length) return null;
        return (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Procrustes Stability{isPmi ? " (PMI)" : " (Laplacian)"}</h3>
          <p className="text-xs text-muted-foreground mb-3">How much the map changes when adding one more tag (lower = more stable). The green bar marks the stability cutoff ({cutoff} tags).</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.15} vertical={false} />
              <XAxis dataKey="top_n" tick={{ fontSize: 10 }} label={{ value: "Number of tags", position: "bottom", fontSize: 11, offset: -5 }} />
              <YAxis tick={{ fontSize: 10 }} width={40} label={{ value: "Layout change", angle: -90, position: "insideLeft", fontSize: 11 }} />
              <RechartsTooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0]?.payload;
                  return (
                    <div className="rounded-lg border border-border bg-popover px-2.5 py-1.5 shadow-lg text-xs">
                      {d.top_n} tags: <b>{d.disparity.toFixed(3)}</b> Procrustes distance
                    </div>
                  );
                }}
              />
              <Bar dataKey="disparity" radius={[2, 2, 0, 0]}
                shape={(props) => {
                  const { x, y, width, height, payload } = props;
                  const isStable = payload.top_n === cutoff;
                  return <rect x={x} y={y} width={width} height={height} rx={2}
                    fill={isStable ? "#10b981" : "#3b82f6"} fillOpacity={isStable ? 0.9 : 0.5} />;
                }}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
        );
      })()}

      {/* Methodology */}
      <div className="border border-border rounded-lg p-4 bg-card space-y-3">
        <h3 className="text-sm font-medium">Methodology</h3>
        <div className="text-xs text-muted-foreground space-y-2.5 leading-relaxed max-w-3xl">
          {data.method === "incremental_tags_laplacian_stable" ? <>
            {/* Streamlined methodology for pipeline-generated maps (GT etc.) */}
            <p className="text-foreground font-medium text-sm">Papers mapped using: incremental tag extraction → feature selection → Procrustes stability analysis → UMAP with native Jaccard metric.</p>
            <div>
              <span className="text-foreground font-medium">1. Incremental Tag Extraction.</span>{" "}
              Claude Opus 4.6 extracts 8-10 descriptive tags per paper as a flat list. Each paper sees the full vocabulary extracted so far and reuses existing tags where suitable, producing a self-consistent vocabulary with minimal synonyms ({data.n_papers} papers, ~{Object.keys(data.incremental_tag_summary || {}).length * 10} unique tags).
            </div>
            <div>
              <span className="text-foreground font-medium">2. Feature Selection.</span>{" "}
              Three tag selection methods are compared. <em>Laplacian score</em> measures whether nearby papers agree on a tag — preserves neighborhood structure but includes ubiquitous tags. <em>Conditional Entropy</em> measures how much sharing a tag reduces uncertainty about other tags. <em>Pointwise Mutual Information (PMI)</em> selects tags with the strongest non-random co-occurrence patterns — it naturally excludes generic tags like "game theory" because they co-occur with everything at the expected rate. PMI at top-50 achieves the highest average silhouette (0.700 across K=2-10), producing the most robust clusters for homogeneous categories.
            </div>
            <div>
              <span className="text-foreground font-medium">3. Stability Cutoff.</span>{" "}
              Tags are added in rank order until the map stabilizes — the Procrustes distance between consecutive layouts drops below 0.20. The chart above shows this curve. Both "Stable" views use this principled cutoff.{data.has_jaccard_lap10 && " Silhouette-optimized 'Top 10' views are also available for maximum cluster separation at the cost of stability."}
            </div>
            <div>
              <span className="text-foreground font-medium">4. UMAP Projection.</span>{" "}
              Papers are represented as binary tag vectors and projected to 2D using UMAP with native Jaccard metric. This lets UMAP build proper nearest-neighbor graphs directly from the binary data, avoiding ring artifacts from precomputed distance matrices.
            </div>
            <div>
              <span className="text-foreground font-medium">5. Clustering &amp; Titles.</span>{" "}
              K-Means on the 2D UMAP coordinates for K=1-10, default K from best silhouette score. Claude Opus 4.6 generates contrastive cluster titles by seeing abstracts from all clusters simultaneously. Tags used for each view are highlighted in the paper tooltip.
            </div>
          </> : <>
            {/* Full comparative methodology for physics etc. */}
            <p className="text-foreground font-medium text-sm">This page compares multiple methods for mapping research papers in 2D: LLM pairwise scoring, text embeddings, tag-based similarity (Jaccard), and Laplacian-filtered tag selection.</p>

            <div className="mt-3 mb-1 text-foreground font-medium text-xs uppercase tracking-wider">LLM Pairwise Methods (MDS &amp; UMAP)</div>
          <div>
            <span className="text-foreground font-medium">1. Pairwise Similarity Scoring.</span>{" "}
            Each paper is compared with 20 randomly selected papers from the same category. For each pair, Claude Opus 4.6 rates topical similarity on an integer scale from 1 (unrelated) to 20 (identical research question), using the paper's abstract and AI impact assessment as input. This produces a sparse similarity matrix covering ~10% of all possible pairs.
          </div>
          <div>
            <span className="text-foreground font-medium">2. Distance Matrix.</span>{" "}
            Similarity scores are converted to distances (distance = 20 &minus; similarity). Uncompared pairs receive the median distance (10), positioning them neutrally.
          </div>
          <div>
            <span className="text-foreground font-medium">3. MDS Embedding.</span>{" "}
            Multidimensional Scaling projects the distance matrix into 2D by minimizing <em>stress</em> — the difference between original and 2D distances. Preserves global structure but can distort local neighborhoods.
          </div>
          <div>
            <span className="text-foreground font-medium">4. UMAP Embedding.</span>{" "}
            UMAP constructs a k-nearest-neighbor graph from the distance matrix, then optimizes a layout preserving topological structure. Prioritizes local neighborhoods over global distances, producing more visually separated clusters.
          </div>

          <div className="mt-3 mb-1 text-foreground font-medium text-xs uppercase tracking-wider">Embedding Methods (Emb: Abstract, Emb: Summary &amp; Emb: Tags)</div>
          <div>
            <span className="text-foreground font-medium">5. Text Embeddings.</span>{" "}
            Each paper is embedded into a 1536-dimensional vector using OpenAI <code className="text-[11px]">text-embedding-3-small</code>. Two variants are compared: <em>Abstract</em> (abstract text only) and <em>Summary</em> (abstract + Claude Opus 4.6 impact assessment). Cosine similarity between all N&times;N paper pairs produces a dense distance matrix with 100% coverage — no missing pairs, no sampling needed.
          </div>
          <div>
            <span className="text-foreground font-medium">6. Tag Embeddings.</span>{" "}
            Claude Opus 4.6 extracts structured tags from each paper's summary: topics (3-5), methods (2-4), application domains (1-2), and key concepts (3-5), using canonical terminology to reduce synonyms. The concatenated tag string is then embedded using the same embedding model. This combines Claude's domain-aware semantic understanding with embedding-based fuzzy matching for related-but-not-identical terms.
          </div>
          <div>
            <span className="text-foreground font-medium">7. Consolidated Tag Embeddings.</span>{" "}
            The 2,856 unique raw tags are themselves embedded, then clustered into 150 canonical groups using agglomerative clustering on cosine distances. Each group is named after its most frequent member (e.g. "Monte Carlo simulation" and "Monte Carlo sampling" merge under "Monte Carlo simulation"). Papers are represented as binary vectors over these 150 groups, and cosine similarity is computed directly — no text embedding needed. This tests whether synonym consolidation improves clustering quality.
          </div>
          <div>
            <span className="text-foreground font-medium">8. Jaccard on Incremental Tags.</span>{" "}
            Instead of extracting tags independently per paper, Claude processes papers sequentially — each paper sees the full vocabulary extracted so far and is instructed to reuse existing tags where suitable, only coining new terms when genuinely needed. This reduces 2,856 fragmented tags to 658 canonical terms (77% reduction) with only 15% hapax tags (vs 82% for independent extraction). Similarity is computed as Jaccard index (tag set overlap) directly — no embeddings needed. Five views are available: <em>All</em> (combined tags, silhouette 0.444), <em>Topics</em> (research subfields, 0.475), <em>Methods</em> (computational techniques, 0.457), <em>Domains</em> (application areas, 0.829 — near-perfect separation with only 14 terms), and <em>Concepts</em> (scientific concepts, 0.422). The per-criterion views reveal which dimension drives clustering: domain membership produces the clearest separation, while concepts are too fragmented to cluster well.
          </div>
          <div>
            <span className="text-foreground font-medium">9. Laplacian-Filtered Jaccard.</span>{" "}
            Not all tags are equally useful for clustering. The <em>Laplacian score</em> measures whether a tag preserves local neighborhood structure: if two papers are similar (by other tags), do they agree on this tag? Three variants are tested using the top-N Laplacian-ranked tags:
          </div>
          <div className="ml-4 space-y-1.5">
            <div>
              <span className="text-foreground font-medium">Top 14</span> (silhouette-optimized): achieves <b>0.918</b> at K=7 — the highest single silhouette across all methods. However, this operates in the "unstable" regime where adding one more tag significantly reorganizes the map.
            </div>
            <div>
              <span className="text-foreground font-medium">Stable (35)</span> (stability-optimized): the cutoff is determined by <em>Procrustes stability analysis</em> — tags are added one by one and the layout change between consecutive maps is measured. The "elbow" where the smoothed Procrustes distance drops below 0.20 and stays there is at ~35 tags. This map is robust: adding tag #36 barely changes the layout. Achieves silhouette 0.804 at K=2.
            </div>
            <div>
              <span className="text-foreground font-medium">Top 100</span>: broader vocabulary captures more nuance but dilutes cluster separation (silhouette 0.760 at K=2).
            </div>
          </div>
          <div>
            <span className="text-foreground font-medium">10. UMAP Projection.</span>{" "}
            All distance matrices (LLM pairwise, embedding cosine, Jaccard) are projected to 2D using UMAP with the same parameters (n_neighbors=12, min_dist=0.5, spread=2.0). Dense matrices (embeddings, Jaccard) produce more reliable local structure than the sparse LLM pairwise matrix.
          </div>

          <div className="mt-3 mb-1 text-foreground font-medium text-xs uppercase tracking-wider">Shared</div>
          <div>
            <span className="text-foreground font-medium">11. Clustering.</span>{" "}
            K-Means is applied independently to each embedding's 2D coordinates for K=1 through 10. Clusters are view-specific — switching between methods shows clusters computed on that method's layout. The default K maximizes silhouette score.
          </div>
          <div>
            <span className="text-foreground font-medium">12. Cluster Titles.</span>{" "}
            For the LLM pairwise methods, Claude Opus 4.6 generates contrastive cluster titles by seeing abstracts from ALL clusters simultaneously. For embedding methods, titles fall back to keyword extraction from paper titles within each cluster.
          </div>
          <div>
            <span className="text-foreground font-medium">13. Dot Sizing.</span>{" "}
            Each paper's dot radius reflects its Kurate impact score in 5 tiers: &ge;1500 (largest), 1400, 1300, 1200, and &lt;1200 (smallest).
          </div>

          <div className="mt-3 mb-1 text-foreground font-medium text-xs uppercase tracking-wider">Cost Comparison</div>
          <div>
            The LLM pairwise approach requires N&times;20 Claude calls (~$7.50 for 249 papers, ~85 min). Abstract/summary embeddings require N OpenAI embedding calls (~$0.01, ~30 sec). Tag embeddings require N Claude calls for extraction + N embedding calls (~$0.75, ~8 min). Incremental tag extraction costs the same (~$0.75, ~12 min sequential) but produces a self-consistent vocabulary that works with simple Jaccard similarity. Laplacian-filtered Jaccard on just 14 selected tags achieved the highest silhouette (<b>0.918</b> at K=7) — demonstrating that a tiny, carefully selected vocabulary outperforms both expensive pairwise LLM scoring and high-dimensional embeddings.
          </div>
          </>}
        </div>
      </div>
      {data.tag_summary && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-3">Extracted Tags</h3>
          <p className="text-xs text-muted-foreground mb-4">Tags extracted by Claude Opus 4.6 from paper summaries. Shown: top tags by frequency across {data.n_papers} papers.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {["topics", "methods", "domains", "concepts"].map(key => {
              const tags = data.tag_summary[key];
              if (!tags) return null;
              const entries = Object.entries(tags).sort((a, b) => b[1] - a[1]);
              const maxCount = entries[0]?.[1] || 1;
              return (
                <div key={key}>
                  <div className="text-xs font-medium text-foreground mb-2 capitalize">{key}</div>
                  <div className="space-y-0.5">
                    {entries.slice(0, 15).map(([tag, count]) => (
                      <div key={tag} className="flex items-center gap-2 text-xs">
                        <div className="flex-1 flex items-center gap-1.5">
                          <div className="h-1.5 rounded-full bg-accent/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                          <span className="text-muted-foreground truncate">{tag}</span>
                        </div>
                        <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Consolidated tags */}
      {data.consolidated_tag_summary && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Consolidated Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">2,856 raw tags clustered into 150 canonical groups via embedding similarity. Synonyms like "Monte Carlo simulation" and "Monte Carlo sampling" are merged under the most frequent variant.</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(data.consolidated_tag_summary).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.consolidated_tag_summary));
              const opacity = 0.4 + (count / maxCount) * 0.6;
              return (
                <span key={tag} className="px-2 py-0.5 rounded-full border border-border text-xs" style={{ opacity }}>
                  {tag} <span className="text-muted-foreground/60">{count}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Incremental vocabulary tags */}
      {data.incremental_tag_summary && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Incremental Vocabulary Tags</h3>
          <p className="text-xs text-muted-foreground mb-4">Tags extracted sequentially — each paper sees the growing vocabulary and reuses existing terms. Reduces 2,856 independent tags to 658 canonical terms (77% reduction, 15% hapax vs 82% original).</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {["topics", "methods", "domains", "concepts"].map(key => {
              const tags = data.incremental_tag_summary[key];
              if (!tags) return null;
              const entries = Object.entries(tags).sort((a, b) => b[1] - a[1]);
              const maxCount = entries[0]?.[1] || 1;
              return (
                <div key={key}>
                  <div className="text-xs font-medium text-foreground mb-2 capitalize">{key}</div>
                  <div className="space-y-0.5">
                    {entries.slice(0, 15).map(([tag, count]) => (
                      <div key={tag} className="flex items-center gap-2 text-xs">
                        <div className="flex-1 flex items-center gap-1.5">
                          <div className="h-1.5 rounded-full bg-blue-500/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                          <span className="text-muted-foreground truncate">{tag}</span>
                        </div>
                        <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* CE Top 10 tags */}
      {data.ce10_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Conditional Entropy Top 10 Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">Tags ranked by conditional entropy — sharing these tags maximally reduces uncertainty about a paper's other tags. Unlike Laplacian, CE naturally excludes ubiquitous tags.</p>
          <div className="space-y-0.5">
            {Object.entries(data.ce10_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.ce10_selected_tags));
              return (
                <div key={tag} className="flex items-center gap-2 text-xs">
                  <div className="flex-1 flex items-center gap-1.5">
                    <div className="h-1.5 rounded-full bg-rose-500/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                    <span className="text-muted-foreground truncate">{tag}</span>
                  </div>
                  <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* CE Stable tags */}
      {data.ce_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Conditional Entropy Stable Tags ({data.ce_stable_cutoff})</h3>
          <p className="text-xs text-muted-foreground mb-3">CE-ranked tags at the Procrustes stability cutoff.</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(data.ce_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.ce_selected_tags));
              const opacity = 0.4 + (count / maxCount) * 0.6;
              return (
                <span key={tag} className="px-2 py-0.5 rounded-full border border-border text-xs" style={{ opacity }}>
                  {tag} <span className="text-muted-foreground/60">{count}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* PMI Top 50 tags */}
      {data.pmi50_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">PMI Top 50 Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">Tags ranked by average Pointwise Mutual Information — tags with the strongest non-random co-occurrence patterns. Excludes ubiquitous tags naturally. Best avg silhouette (0.700) across all methods at this scale. Note: 44% of papers have no PMI-top-50 tags and fall into a catch-all cluster.</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(data.pmi50_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.pmi50_selected_tags));
              const opacity = 0.4 + (count / maxCount) * 0.6;
              return (
                <span key={tag} className="px-2 py-0.5 rounded-full border border-border text-xs" style={{ opacity }}>
                  {tag} <span className="text-muted-foreground/60">{count}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Laplacian Top 10 tags */}
      {data.lap10_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Laplacian Top 10 Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">The 10 most structure-preserving tags — silhouette-optimized for maximum cluster separation ({data.jaccard_lap10_silhouette} at K={data.jaccard_lap10_best_k}).</p>
          <div className="space-y-0.5">
            {Object.entries(data.lap10_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.lap10_selected_tags));
              return (
                <div key={tag} className="flex items-center gap-2 text-xs">
                  <div className="flex-1 flex items-center gap-1.5">
                    <div className="h-1.5 rounded-full bg-amber-500/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                    <span className="text-muted-foreground truncate">{tag}</span>
                  </div>
                  <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Laplacian-selected tags: Top 14 */}
      {data.laplacian14_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Laplacian Top 14 Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">The 14 most structure-preserving tags by Laplacian score. This minimal vocabulary achieves silhouette 0.918 at K=7 — the highest of all methods.</p>
          <div className="space-y-0.5">
            {Object.entries(data.laplacian14_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.laplacian14_selected_tags));
              return (
                <div key={tag} className="flex items-center gap-2 text-xs">
                  <div className="flex-1 flex items-center gap-1.5">
                    <div className="h-1.5 rounded-full bg-purple-500/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                    <span className="text-muted-foreground truncate">{tag}</span>
                  </div>
                  <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Laplacian-selected tags: Top 100 */}
      {data.stable_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Laplacian Stable Tags (35)</h3>
          <p className="text-xs text-muted-foreground mb-3">The 35 most structure-preserving tags — the stability cutoff where adding more tags stops meaningfully changing the map (Procrustes distance &lt; 0.20).</p>
          <div className="space-y-0.5">
            {Object.entries(data.stable_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.stable_selected_tags));
              return (
                <div key={tag} className="flex items-center gap-2 text-xs">
                  <div className="flex-1 flex items-center gap-1.5">
                    <div className="h-1.5 rounded-full bg-emerald-500/50" style={{ width: `${count / maxCount * 100}%`, minWidth: 4 }} />
                    <span className="text-muted-foreground truncate">{tag}</span>
                  </div>
                  <span className="text-muted-foreground/60 tabular-nums shrink-0">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Laplacian-selected tags: Top 100 */}
      {data.laplacian_selected_tags && (
        <div className="border border-border rounded-lg p-4 bg-card">
          <h3 className="text-sm font-medium mb-1">Laplacian Top 100 Tags</h3>
          <p className="text-xs text-muted-foreground mb-3">The 100 most structure-preserving tags. Broader vocabulary captures more nuance but dilutes cluster separation (silhouette 0.760 at K=2).</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(data.laplacian_selected_tags).sort((a, b) => b[1] - a[1]).map(([tag, count]) => {
              const maxCount = Math.max(...Object.values(data.laplacian_selected_tags));
              const opacity = 0.4 + (count / maxCount) * 0.6;
              return (
                <span key={tag} className="px-2 py-0.5 rounded-full border border-border text-xs" style={{ opacity }}>
                  {tag} <span className="text-muted-foreground/60">{count}</span>
                </span>
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
