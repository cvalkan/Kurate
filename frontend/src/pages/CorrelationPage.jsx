import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { BarChart3, ChevronDown } from "lucide-react";
import { CorrelationSection } from "@/components/CorrelationSection";
import { LeaderboardConvergence } from "@/components/ConvergenceSection";

const API = process.env.REACT_APP_BACKEND_URL;

export default function CorrelationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
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
      const res = await axios.get(`${API}/api/model-correlation`, { params });
      setData(res.data);
    } catch (err) {
      console.error("Failed to fetch correlation data:", err);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-5xl py-10">
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-secondary/30 rounded-lg animate-pulse" />)}
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
          How well do GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro agree on paper rankings?
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
            <Button key={c.id} variant={category === c.id ? "default" : "ghost"} size="sm" onClick={() => { setCategory(c.id); setMoreOpen(false); setLoading(true); }} className="text-xs h-8 shrink-0">
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
                    <button key={c2.id} className={`w-full text-left px-3 py-1.5 text-sm hover:bg-accent/10 transition-colors ${category === c2.id ? "bg-accent/10 text-accent font-medium" : ""}`} onClick={() => { setCategory(c2.id); setMoreOpen(false); setLoading(true); }}>
                      <span className="font-mono text-[11px] text-muted-foreground mr-2">{c2.id}</span>{c2.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <CorrelationSection
        sectionData={data}
        title="Standard Tournament"
        description='Full-text evaluation: "Which paper has higher scientific impact?"'
      />

      <div className="mb-6">
        <LeaderboardConvergence category={category || null} />
      </div>

      <div className="space-y-3 mb-6">
        <div className="p-4 bg-secondary/30 border border-border rounded-lg text-sm">
          <h3 className="font-medium text-foreground mb-2">Pair difficulty breakdown</h3>
          <p className="text-xs text-muted-foreground">
            Each model pair's agreement is broken down by difficulty. Hover <span className="font-medium text-foreground cursor-help border-b border-dotted border-muted-foreground" title="Papers with a win rate difference ≥10 percentage points. One paper is clearly stronger. Models tend to agree more here (typically 70-90%).">clear-cut</span> and <span className="font-medium text-foreground cursor-help border-b border-dotted border-muted-foreground" title="Papers with similar win rates (<10pp difference). Genuine toss-ups where reasonable judges can disagree. Agreement drops to ~50% (near random).">contested</span> labels in the cards above for definitions.
          </p>
        </div>
      </div>
    </div>
  );
}
