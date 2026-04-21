import { useState, useEffect, useCallback, useRef, Component } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { BarChart3, ChevronDown } from "lucide-react";
import { CorrelationSection } from "@/components/CorrelationSection";
import { LeaderboardConvergence } from "@/components/ConvergenceSection";
import { SiRatingSection } from "@/components/SiRatingSection";
import { ScoringMethodSection } from "@/components/ScoringMethodSection";
import { PwVsSiSection } from "@/components/PwVsSiSection";
import { InterModelSection } from "@/components/InterModelSection";

import PositionalBiasSection from "@/pages/PositionalBiasSection";

const API = process.env.REACT_APP_BACKEND_URL;

class SectionBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return <div className="p-4 border border-red-200 bg-red-50 rounded-lg text-xs text-red-700">Section failed to render: {this.state.error.message}</div>;
    }
    return this.props.children;
  }
}

export default function CorrelationPage() {
  const [data, setData] = useState(null);
  const [siData, setSiData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState("aggregate");
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");
  const moreCatsRef = useRef(null);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    const handler = (e) => { if (moreCatsRef.current && !moreCatsRef.current.contains(e.target)) setMoreOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      const cats = res.data.categories || [];
      setCategories([{ id: "", name: "All Categories" }, ...cats]);
      setCategory("");
    }).catch(() => setCategory(""));
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const params = category ? { category } : {};
      const res = await axios.get(`${API}/api/model-analysis`, { params });
      // If server is still warming caches, retry after a delay
      if (res.data?.status === "warming_up") {
        setTimeout(() => fetchData(), 10000);
        return;
      }
      setData(res.data);
      // Build siData in the format PwVsSiSection and SiRatingSection expect
      const si = res.data?.si_data || {};
      si.pw_vs_si = res.data?.pw_vs_si || null;
      si.avg_pw_vs_si = res.data?.avg_pw_vs_si || null;
      setSiData(si.status === "ok" || si.pw_vs_si ? si : null);
    } catch (err) {
      console.error("Failed to fetch model analysis data:", err);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-5xl py-10">
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <div className="h-8 w-8 border-[3px] border-muted-foreground/20 border-t-muted-foreground rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">Loading model analysis&hellip;</p>
        </div>
      </div>
    );
  }

  if (!data || !data.models?.length) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-5xl py-10 text-center text-muted-foreground">
        <BarChart3 className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Not enough data for correlation analysis yet.</p>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Model Correlation
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          How well do Claude Opus, GPT-5.2, and Gemini 3 Pro agree on paper rankings?
        </p>
        <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg max-w-2xl">
          <p className="text-xs text-amber-900">
            <span className="font-semibold">Matchmaking bias:</span> The tournament uses adaptive matchmaking that over-samples contested pairs to converge rankings faster.
            Agreement rates below are biased downward — models are disproportionately tested on the hardest cases.
            On a random sample of pairs, agreement would be substantially higher.
          </p>
        </div>
      </div>

      {categories.length > 1 && (
        <div className="flex items-center gap-1 mb-6 p-1 bg-primary/5 rounded-lg overflow-x-auto scrollbar-none" data-testid="corr-cat-tabs">
          {categories.slice(0, 5).map((c) => (
            <Button key={c.id} variant={category === c.id ? "default" : "ghost"} size="sm" onClick={() => { setCategory(c.id); setMoreOpen(false); }} className="text-xs h-8 shrink-0">
              {c.name}
            </Button>
          ))}
          {categories.length > 5 && (
            <div className="relative shrink-0" ref={moreCatsRef}>
              <Button
                variant={categories.slice(5).some(c2 => c2.id === category) ? "default" : "ghost"}
                size="sm" className="text-xs h-8 gap-1 shrink-0"
                onClick={() => setMoreOpen(v => !v)}
              >
                {categories.slice(5).find(c2 => c2.id === category)?.name || "More"}
                <ChevronDown className={`h-3 w-3 transition-transform ${moreOpen ? "rotate-180" : ""}`} />
              </Button>
              {moreOpen && (
                <div className="fixed z-50 bg-background border border-border rounded-lg shadow-lg min-w-48 py-1" style={{ top: moreCatsRef.current?.getBoundingClientRect().bottom + 4, left: moreCatsRef.current?.getBoundingClientRect().left }}>
                  {categories.slice(5).map((c2) => (
                    <button key={c2.id} className={`w-full text-left px-3 py-1.5 text-sm hover:bg-accent/10 transition-colors ${category === c2.id ? "bg-accent/10 text-accent font-medium" : ""}`} onClick={() => { setCategory(c2.id); setMoreOpen(false); }}>
                      <span className="font-mono text-[11px] text-muted-foreground mr-2">{c2.id}</span>{c2.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <SectionBoundary>
        <CorrelationSection
          sectionData={data}
          title="Standard Tournament"
          description='Full-text evaluation: "Which paper has higher scientific impact?"'
          viewMode={viewMode} setViewMode={setViewMode}
        />
      </SectionBoundary>

      <SectionBoundary>
        <div className="mb-6">
          <LeaderboardConvergence category={category || null} />
        </div>
      </SectionBoundary>

      <SectionBoundary>
        <ScoringMethodSection category={category || null} scoringData={data?.scoring_method} viewMode={viewMode} osUpdatedAt={data?.openskill_updated_at} />
      </SectionBoundary>

      <SectionBoundary>
        <PwVsSiSection category={category || null} siData={siData} viewMode={viewMode} osUpdatedAt={data?.openskill_updated_at} coherenceData={data?.score_pairwise_coherence} />
      </SectionBoundary>

      <SectionBoundary>
        <InterModelSection pwData={data} siData={siData} viewMode={viewMode} osUpdatedAt={data?.openskill_updated_at} />
      </SectionBoundary>

      <SectionBoundary>
        <SiRatingSection category={category || null} hidePwVsSi siData={siData} />
      </SectionBoundary>

      <SectionBoundary>
        {/* PositionalBiasSection hidden pending bias investigation — see POSITIONAL_BIAS_INVESTIGATION.md */}
      </SectionBoundary>

    </div>
  );
}
