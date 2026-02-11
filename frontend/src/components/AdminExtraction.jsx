import { useState, useEffect } from "react";
import axios from "axios";
import { FileText, CheckCircle, XCircle, BarChart3, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export function AdminExtraction() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/api/admin/extraction-stats`, {
        headers: getAdminHeaders(),
      });
      setStats(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load extraction stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 bg-secondary/50 rounded animate-pulse" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-secondary/30 rounded-lg animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 border border-red-200 bg-red-50 rounded-lg text-red-700">
        <p className="font-medium">Error loading extraction stats</p>
        <p className="text-sm mt-1">{error}</p>
        <Button variant="outline" size="sm" onClick={fetchStats} className="mt-3">
          Retry
        </Button>
      </div>
    );
  }

  if (!stats) return null;

  const sectionOrder = ["introduction", "methodology", "results", "conclusion"];
  const sectionLabels = {
    introduction: "Introduction",
    methodology: "Methodology",
    results: "Results",
    conclusion: "Conclusion",
  };

  return (
    <div className="space-y-6" data-testid="admin-extraction">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-heading text-lg font-medium">PDF Extraction Statistics</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Analysis of section extraction from {stats.papers_with_text.toLocaleString()} papers with PDF text
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchStats} className="gap-2">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 border border-border rounded-lg bg-background">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <FileText className="h-4 w-4" />
            <span className="text-xs font-medium">Papers with PDF</span>
          </div>
          <div className="text-2xl font-semibold">{stats.papers_with_text.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground mt-1">
            {stats.text_coverage_rate}% of {stats.total_papers.toLocaleString()} total
          </div>
        </div>

        <div className="p-4 border border-border rounded-lg bg-background">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <CheckCircle className="h-4 w-4 text-green-500" />
            <span className="text-xs font-medium">All 4 Sections Found</span>
          </div>
          <div className="text-2xl font-semibold">{stats.all_sections_found.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground mt-1">
            {stats.all_sections_rate}% success rate
          </div>
        </div>

        <div className="p-4 border border-border rounded-lg bg-background">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <BarChart3 className="h-4 w-4" />
            <span className="text-xs font-medium">Avg Extracted</span>
          </div>
          <div className="text-2xl font-semibold">{stats.avg_extracted_chars.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground mt-1">
            chars ({stats.extraction_ratio}% of full text)
          </div>
        </div>

        <div className="p-4 border border-border rounded-lg bg-background">
          <div className="flex items-center gap-2 text-muted-foreground mb-1">
            <XCircle className="h-4 w-4 text-amber-500" />
            <span className="text-xs font-medium">No Sections Found</span>
          </div>
          <div className="text-2xl font-semibold">{stats.no_sections_found}</div>
          <div className="text-xs text-muted-foreground mt-1">
            {stats.no_sections_rate}% failure rate
          </div>
        </div>
      </div>

      {/* Section Success Rates */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-secondary/30 border-b border-border">
          <h3 className="text-sm font-medium">Section Extraction Rates (Overall)</h3>
        </div>
        <div className="p-4 space-y-4">
          {sectionOrder.map((section) => {
            const data = stats.overall[section];
            return (
              <div key={section} className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{sectionLabels[section]}</span>
                  <span className="text-muted-foreground">
                    {data.found.toLocaleString()} / {data.total.toLocaleString()} ({data.rate}%)
                  </span>
                </div>
                <Progress value={data.rate} className="h-2" />
                <div className="text-xs text-muted-foreground">
                  Avg {data.avg_chars.toLocaleString()} chars when found
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Per-Category Breakdown */}
      <div className="border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-secondary/30 border-b border-border">
          <h3 className="text-sm font-medium">Extraction by Category</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary/20">
                <th className="text-left px-4 py-2.5 font-medium">Category</th>
                <th className="text-right px-3 py-2.5 font-medium">Papers</th>
                <th className="text-right px-3 py-2.5 font-medium">Intro</th>
                <th className="text-right px-3 py-2.5 font-medium">Method</th>
                <th className="text-right px-3 py-2.5 font-medium">Results</th>
                <th className="text-right px-3 py-2.5 font-medium">Conclusion</th>
                <th className="text-right px-3 py-2.5 font-medium">All 4</th>
                <th className="text-right px-4 py-2.5 font-medium">Avg Text</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.by_category)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([cat, data]) => (
                  <tr key={cat} className="border-b border-border/50 hover:bg-secondary/10">
                    <td className="px-4 py-2.5 font-mono text-xs">{cat}</td>
                    <td className="text-right px-3 py-2.5">{data.total}</td>
                    <td className="text-right px-3 py-2.5">
                      <span className={data.introduction.rate >= 95 ? "text-green-600" : data.introduction.rate >= 80 ? "text-amber-600" : "text-red-600"}>
                        {data.introduction.rate}%
                      </span>
                    </td>
                    <td className="text-right px-3 py-2.5">
                      <span className={data.methodology.rate >= 95 ? "text-green-600" : data.methodology.rate >= 80 ? "text-amber-600" : "text-red-600"}>
                        {data.methodology.rate}%
                      </span>
                    </td>
                    <td className="text-right px-3 py-2.5">
                      <span className={data.results.rate >= 95 ? "text-green-600" : data.results.rate >= 80 ? "text-amber-600" : "text-red-600"}>
                        {data.results.rate}%
                      </span>
                    </td>
                    <td className="text-right px-3 py-2.5">
                      <span className={data.conclusion.rate >= 95 ? "text-green-600" : data.conclusion.rate >= 80 ? "text-amber-600" : "text-red-600"}>
                        {data.conclusion.rate}%
                      </span>
                    </td>
                    <td className="text-right px-3 py-2.5">
                      <span className={data.all_sections / data.total >= 0.9 ? "text-green-600" : "text-amber-600"}>
                        {Math.round(data.all_sections / data.total * 100)}%
                      </span>
                    </td>
                    <td className="text-right px-4 py-2.5 text-muted-foreground text-xs">
                      {(data.avg_full_text_chars / 1000).toFixed(1)}K
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Sample Papers */}
      {stats.sample_papers && stats.sample_papers.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-secondary/30 border-b border-border">
            <h3 className="text-sm font-medium">Sample Papers (first 50)</h3>
          </div>
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-background">
                <tr className="border-b border-border">
                  <th className="text-left px-3 py-2 font-medium">Title</th>
                  <th className="text-left px-2 py-2 font-medium">Category</th>
                  <th className="text-right px-2 py-2 font-medium">Sections</th>
                  <th className="text-right px-2 py-2 font-medium">Intro</th>
                  <th className="text-right px-2 py-2 font-medium">Method</th>
                  <th className="text-right px-2 py-2 font-medium">Results</th>
                  <th className="text-right px-2 py-2 font-medium">Concl</th>
                  <th className="text-right px-3 py-2 font-medium">Full Text</th>
                </tr>
              </thead>
              <tbody>
                {stats.sample_papers.map((paper) => (
                  <tr key={paper.id} className="border-b border-border/30 hover:bg-secondary/10">
                    <td className="px-3 py-1.5 max-w-[250px] truncate" title={paper.title}>
                      {paper.title}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-muted-foreground">{paper.category}</td>
                    <td className="text-right px-2 py-1.5">
                      <span className={paper.sections_found === 4 ? "text-green-600" : paper.sections_found >= 2 ? "text-amber-600" : "text-red-600"}>
                        {paper.sections_found}/4
                      </span>
                    </td>
                    <td className="text-right px-2 py-1.5 text-muted-foreground">
                      {paper.intro_chars > 0 ? paper.intro_chars : "-"}
                    </td>
                    <td className="text-right px-2 py-1.5 text-muted-foreground">
                      {paper.method_chars > 0 ? paper.method_chars : "-"}
                    </td>
                    <td className="text-right px-2 py-1.5 text-muted-foreground">
                      {paper.results_chars > 0 ? paper.results_chars : "-"}
                    </td>
                    <td className="text-right px-2 py-1.5 text-muted-foreground">
                      {paper.conclusion_chars > 0 ? paper.conclusion_chars : "-"}
                    </td>
                    <td className="text-right px-3 py-1.5 text-muted-foreground">
                      {(paper.full_text_chars / 1000).toFixed(1)}K
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Algorithm Info */}
      <div className="border border-border rounded-lg p-4 bg-secondary/10">
        <h3 className="text-sm font-medium mb-2">Extraction Algorithm</h3>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li><span className="text-foreground font-medium">1. Regex-based header detection</span> — Matches numbered sections (e.g., "1. Introduction") and all-caps headers</li>
          <li><span className="text-foreground font-medium">2. Field-adaptive markers</span> — Economics uses "Data/Identification", Physics uses "Theory/Numerical Methods", etc.</li>
          <li><span className="text-foreground font-medium">3. Position-aware extraction</span> — Introduction must be in first 30%, Conclusion in last 40% of document</li>
          <li><span className="text-foreground font-medium">4. Fallback</span> — If header not found, simple substring search within position bounds</li>
        </ul>
      </div>
    </div>
  );
}
