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
          How PaperSumo ranks academic papers across {categories.length || "multiple"} categories using AI-powered pairwise comparison.
        </p>
      </div>

      <div>
        <Step number={1} icon={Search} title="Paper Discovery & AI Impact Assessment">
          <p>The system queries the arXiv API for the latest papers across {catList || "Robotics, Distributed Computing, Economics, Computational Physics, Biomolecules"}. For each paper, the full PDF is downloaded and three independent <span className="text-foreground font-medium">AI Impact Assessments</span> are generated — one each from GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro — analyzing the paper's novelty, methodology, potential impact, and limitations. These pre-computed summaries power both the pairwise tournament and the paper detail pages.</p>
        </Step>

        <Step number={2} icon={Swords} title="Pairwise Tournament">
          <p>Papers are compared head-to-head in pairs using their <span className="text-foreground font-medium">abstract + AI summary</span> as input. Each comparison is assigned to one of three AI models via <span className="text-foreground font-medium">round-robin rotation</span>, ensuring every paper is evaluated by all three models equally:</p>
          <div className="flex flex-wrap gap-2 my-2">
            <span className="text-xs font-mono px-2 py-1 rounded border bg-green-50 text-green-700 border-green-200">GPT-5.2</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-orange-50 text-orange-700 border-orange-200">Claude Opus 4.5</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-blue-50 text-blue-700 border-blue-200">Gemini 3 Pro</span>
          </div>
          <p>Each model evaluates which paper has higher potential scientific impact across five dimensions: novelty, real-world applications, methodological rigor, breadth of impact, and timeliness. <Link to="/prompts" className="text-accent hover:underline" data-testid="prompts-link-evaluation">View the evaluation prompt &rarr;</Link></p>
        </Step>

        <Step number={3} icon={Shuffle} title="Positional Bias Correction">
          <p>The presentation order of each pair is <span className="text-foreground font-medium">randomly flipped with 50% probability</span> before sending to the LLM. This eliminates positional bias — a known issue where models tend to prefer the paper presented first.</p>
        </Step>

        <Step number={4} icon={RefreshCw} title="Two-Tier Convergence">
          <p>The matchmaker uses a <span className="text-foreground font-medium">goal-directed</span> approach with two-tier convergence targets:</p>
          <ul className="list-disc list-inside space-y-1 text-xs mt-1">
            <li><span className="text-foreground">General papers</span> — Wilson 95% CI margin &le; 15% (configurable). Ensures all papers have stable win-rate estimates.</li>
            <li><span className="text-foreground">Top-K papers</span> — Wilson 95% CI margin &le; 10% (configurable). Tighter confidence for the papers that matter most in the leaderboard.</li>
            <li><span className="text-foreground">Top-K cross-matches</span> — Every pair of top-K papers must have played against each other at least once to ensure direct comparison.</li>
          </ul>
          <p className="mt-2">Papers with the widest confidence intervals are matched first. To ensure new papers integrate into the existing ranking, a <span className="text-foreground font-medium">calibration ratio</span> (default 50%) controls what fraction of new-paper matches are against established (already-converged) papers vs. other new papers. This balances fast CI convergence with proper score calibration through transitive chains to known rankings.</p>
        </Step>

        <Step number={5} icon={Users} title="Multi-Model Consensus">
          <p>Round-robin rotation ensures each model contributes equally to every paper's ranking. The <Link to="/correlation" className="text-accent hover:underline">Model Analysis</Link> page shows pairwise agreement rates broken down by pair difficulty — clear-cut pairs typically show higher agreement than contested ones.</p>
        </Step>

        <Step number={6} icon={BarChart3} title="Bradley-Terry Scoring">
          <p>Rankings are computed using the <span className="text-foreground font-medium">Bradley-Terry model</span>, a statistical method for deriving global rankings from pairwise comparisons. Raw parameters are converted to Elo-like scores centered at 1200. Win rates are reported with <span className="text-foreground font-medium">95% Wilson confidence intervals</span>.</p>
        </Step>

        <Step number={7} icon={Tag} title="Cross-Category Filtering">
          <p>Papers often have multiple arXiv tags. The leaderboard supports tag-based filtering with AND/OR logic, letting users view papers across primary categories.</p>
        </Step>

        <Step number={8} icon={Sparkles} title="Pre-Generated Impact Assessments">
          <p>When a paper is first fetched, three independent <span className="text-foreground font-medium">AI Impact Assessments</span> are generated from the full PDF text — one from each model (Claude, Gemini, GPT). These are immediately available on the paper detail page in a tabbed view, allowing comparison of how different models evaluate the same paper. <Link to="/prompts" className="text-accent hover:underline" data-testid="prompts-link-summary">View the assessment prompt &rarr;</Link></p>
        </Step>

        <Step number={9} icon={Trophy} title="Dynamic Leaderboard">
          <p>Rankings display Elo score, win rate, confidence interval, match count, and publication date. All data is pre-computed in the background for instant loading. Rankings update dynamically as new papers arrive.</p>
        </Step>

        <Step number={10} icon={Download} title="Continuous Operation">
          <p>The system runs autonomously — fetching new papers on a schedule, running comparisons until all goals are met, then idling. Manual overrides allow administrators to trigger additional comparison rounds at any time.</p>
        </Step>
      </div>

      <div className="mt-4 p-4 bg-secondary/30 rounded-lg border border-border text-xs text-muted-foreground">
        <p className="font-medium text-foreground mb-1">Limitations</p>
        <p>AI-based evaluation is an approximation of scientific impact, not a replacement for human peer review. Rankings reflect the consensus of three large language models. The matchmaker's preference for pairing similar-strength papers means pairwise agreement statistics are biased toward difficult comparisons.</p>
      </div>
    </div>
  );
}
