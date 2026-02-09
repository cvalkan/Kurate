import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { BarChart3 } from "lucide-react";
import { CorrelationSection } from "@/components/CorrelationSection";

const API = process.env.REACT_APP_BACKEND_URL;

export default function CorrelationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");

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
          How well do GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro agree on paper rankings?
        </p>
      </div>

      {categories.length > 1 && (
        <div className="flex items-center gap-1 mb-6 p-1 bg-primary/5 rounded-lg overflow-x-auto scrollbar-none" data-testid="corr-cat-tabs">
          {categories.map((c) => (
            <Button
              key={c.id}
              variant={category === c.id ? "default" : "ghost"}
              size="sm"
              onClick={() => { setCategory(c.id); setLoading(true); }}
              className="text-xs h-8 shrink-0"
            >
              {c.name}
            </Button>
          ))}
        </div>
      )}

      <CorrelationSection
        sectionData={data}
        title="Standard Tournament"
        description='Full-text evaluation: "Which paper has higher scientific impact?"'
      />

      <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
        <span className="font-medium">Note:</span> Standard tournament uses adaptive matchmaking (biased toward contested pairs).
        Prediction tournament analysis is available in the Admin panel under the Experiment tab.
      </div>
    </div>
  );
}
