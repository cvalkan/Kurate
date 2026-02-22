import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import {
  Search, Download, Swords, Trophy, BarChart3,
  RefreshCw, Sparkles, Tag, Shuffle, Users,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function Step({ number, icon: Icon, title, children }) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent/10 text-accent font-mono font-bold text-sm">
          {number}
        </div>
        <div className="w-px flex-1 bg-border mt-2" />
      </div>
      <div className="pb-8 md:pb-10">
        <div className="flex items-center gap-2 mb-1.5">
          <Icon className="h-4 w-4 text-accent" />
          <h3 className="font-heading font-medium text-sm">{title}</h3>
        </div>
        <div className="text-sm text-muted-foreground leading-relaxed space-y-2">
          {children}
        </div>
      </div>
    </div>
  );
}

export default function MethodologyPage() {
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
    }).catch(() => {});
  }, []);

  const catList = categories.map(c => c.name).join(", ");

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-3xl py-6 md:py-10">
      <div className="mb-10">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Methodology
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          How PaperSumo ranks arXiv preprints across {categories.length || "multiple"} categories using AI-powered pairwise comparison.
        </p>
      </div>

      <div>
        <Step number={1} icon={Search} title="Preprint Discovery">
          <p>The system fetches the latest preprints from the arXiv API across {catList || "Robotics, Distributed Computing, Economics, Computational Physics, Biomolecules"} and downloads the full PDF for each.</p>
        </Step>

        <Step number={2} icon={Sparkles} title="AI Impact Assessment">
          <p>Three independent <span className="text-foreground font-medium">AI Impact Assessments</span> are generated from each paper's full text — one each from GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro. Each assessment analyzes novelty, methodology, potential impact, and limitations. These are visible on every paper's detail page and serve as input to the pairwise tournament. <Link to="/prompts" className="text-accent hover:underline" data-testid="prompts-link-summary">View the assessment prompt &rarr;</Link></p>
        </Step>

        <Step number={3} icon={Swords} title="Pairwise Tournament">
          <p>Papers are compared head-to-head using their <span className="text-foreground font-medium">abstract + AI Impact Assessment</span> as input. Each comparison is judged by one of three models via round-robin rotation:</p>
          <div className="flex flex-wrap gap-2 my-2">
            <span className="text-xs font-mono px-2 py-1 rounded border bg-green-50 text-green-700 border-green-200">GPT-5.2</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-orange-50 text-orange-700 border-orange-200">Claude Opus 4.6</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-blue-50 text-blue-700 border-blue-200">Gemini 3 Pro</span>
          </div>
          <p>Each model evaluates which paper has higher potential scientific impact across five dimensions: novelty, real-world applications, methodological rigor, breadth of impact, and timeliness. <Link to="/prompts" className="text-accent hover:underline" data-testid="prompts-link-evaluation">View the evaluation prompt &rarr;</Link></p>
        </Step>

        <Step number={4} icon={Shuffle} title="Positional Bias Correction">
          <p>The presentation order of each pair is <span className="text-foreground font-medium">randomly flipped with 50% probability</span> before sending to the LLM, eliminating the known tendency for models to prefer the paper presented first.</p>
        </Step>

        <Step number={5} icon={RefreshCw} title="Adaptive Matchmaking">
          <p>The matchmaker uses goal-directed pair selection with two convergence tiers: <span className="text-foreground">general papers</span> (Wilson 95% CI &le; 15%) and <span className="text-foreground">top-K papers</span> (CI &le; 10%, with mandatory cross-matches). Papers with the widest confidence intervals are matched first. A calibration ratio ensures new papers are compared against established ones for transitive score calibration.</p>
        </Step>

        <Step number={6} icon={BarChart3} title="Bradley-Terry Scoring">
          <p>Global rankings are derived from pairwise results using the <span className="text-foreground font-medium">Bradley-Terry model</span>, converted to Elo-like scores centered at 1200. Win rates include <span className="text-foreground font-medium">95% Wilson confidence intervals</span>.</p>
        </Step>

        <Step number={7} icon={Users} title="Multi-Model Consensus">
          <p>Round-robin rotation ensures each model contributes equally to every paper's ranking. The <Link to="/correlation" className="text-accent hover:underline">Model Analysis</Link> page shows inter-model agreement rates and per-model ranking correlations.</p>
        </Step>

        <Step number={8} icon={Tag} title="Cross-Category Filtering">
          <p>Papers with multiple arXiv tags can be viewed across primary categories using AND/OR tag filtering.</p>
        </Step>

        <Step number={9} icon={Trophy} title="Dynamic Leaderboard">
          <p>Rankings show Elo score, win rate, confidence interval, match count, and publication date. All data is pre-computed for instant loading and updates automatically as new papers arrive.</p>
        </Step>

        <Step number={10} icon={Download} title="Continuous Operation">
          <p>The system runs autonomously — fetching new papers on a configurable schedule, running pairwise comparisons until convergence targets are met, then idling. Administrators can trigger additional rounds or adjust parameters at any time.</p>
        </Step>
      </div>

      <div className="mt-4 p-4 bg-secondary/30 rounded-lg border border-border text-xs text-muted-foreground">
        <p className="font-medium text-foreground mb-1">Limitations</p>
        <p>AI-based evaluation is an approximation of scientific impact, not a replacement for human peer review. Rankings reflect the consensus of three large language models. The matchmaker's preference for pairing similar-strength papers means pairwise agreement statistics are biased toward difficult comparisons.</p>
      </div>
    </div>
  );
}
