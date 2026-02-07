import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import {
  Search, Download, FileText, Swords, Bot, Trophy, BarChart3,
  RefreshCw, Sparkles, Tag, Shuffle,
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
        <Step number={1} icon={Search} title="Paper Discovery">
          <p>The system queries the arXiv API for the latest papers across multiple categories: {catList || "Robotics, Distributed Computing, Economics, Computational Physics, Biomolecules"}. Each category is fetched independently with pagination to ensure sufficient coverage, even for niche fields. New papers are stored with their metadata — title, authors, abstract, publication date, and PDF link.</p>
          <p>Papers are primarily categorized by their main arXiv tag, but secondary category tags are preserved for cross-category filtering.</p>
        </Step>

        <Step number={2} icon={Download} title="Full-Text Extraction">
          <p>For each new paper, the system downloads the full PDF from arXiv and extracts the text content. Key sections are identified — Introduction, Methodology, Results, and Conclusion — so the AI judges can evaluate the complete scientific contribution, not just the abstract.</p>
        </Step>

        <Step number={3} icon={Swords} title="Pairwise Tournament">
          <p>Papers are compared head-to-head in pairs. For each comparison, the system randomly selects one of three AI models:</p>
          <div className="flex flex-wrap gap-2 my-2">
            <span className="text-xs font-mono px-2 py-1 rounded border bg-green-50 text-green-700 border-green-200">GPT-5.2</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-orange-50 text-orange-700 border-orange-200">Claude Opus 4.5</span>
            <span className="text-xs font-mono px-2 py-1 rounded border bg-blue-50 text-blue-700 border-blue-200">Gemini 3 Pro</span>
          </div>
          <p>Each model evaluates which paper has higher potential scientific impact across five dimensions: novelty, real-world applications, methodological rigor, breadth of impact, and timeliness. Tournaments run independently per category in parallel.</p>
        </Step>

        <Step number={4} icon={Shuffle} title="Positional Bias Correction">
          <p>The presentation order of each pair is <span className="text-foreground font-medium">randomly flipped with 50% probability</span> before sending to the LLM. This eliminates positional bias — a known issue where models tend to prefer the paper presented first. Over many comparisons, each paper appears equally often as "Paper 1" and "Paper 2."</p>
        </Step>

        <Step number={5} icon={RefreshCw} title="Adaptive Matchmaking">
          <p>An intelligent matchmaking algorithm selects which papers to compare next, using <span className="text-foreground font-medium">adaptive per-paper round caps</span> based on urgency:</p>
          <ul className="list-disc list-inside space-y-1 text-xs mt-1">
            <li><span className="text-foreground">Deficit phase</span> — New papers get a boosted match cap to quickly reach the minimum</li>
            <li><span className="text-foreground">CI-driven priority</span> — Papers with wide confidence intervals get more matches</li>
            <li><span className="text-foreground">Win-rate similarity</span> — Pairs with similar strength are preferred (more informative for ranking separation)</li>
            <li><span className="text-foreground">Top-K focus</span> — Extra comparisons target papers near the top to narrow their confidence intervals</li>
            <li><span className="text-foreground">Extreme deprioritization</span> — Papers with very high or low win rates and narrow CIs get fewer matches</li>
          </ul>
          <p className="mt-2">The system runs continuously until convergence goals are met for each category, then idles until new papers arrive.</p>
        </Step>

        <Step number={6} icon={BarChart3} title="Bradley-Terry Scoring">
          <p>Rankings are computed using the <span className="text-foreground font-medium">Bradley-Terry model</span>, a well-established statistical method for deriving global rankings from pairwise comparisons. An optimized implementation pre-indexes matches by paper for fast computation. Raw Bradley-Terry parameters are converted to an Elo-like score centered at 1200.</p>
          <p>Win rates are reported with <span className="text-foreground font-medium">95% Wilson confidence intervals</span>, providing a statistically rigorous measure of ranking certainty.</p>
        </Step>

        <Step number={7} icon={Bot} title="Multi-Model Consensus">
          <p>By randomly assigning three different AI models to each comparison, the system avoids single-model bias. The <Link to="/correlation" className="text-accent hover:underline">Model Analysis</Link> page shows pairwise agreement rates broken down by pair difficulty — clear-cut pairs typically show much higher agreement than contested pairs, which constitute the majority of the sample due to the matchmaker's preference for informative comparisons.</p>
        </Step>

        <Step number={8} icon={Tag} title="Cross-Category Filtering">
          <p>Papers on arXiv often have multiple category tags. The leaderboard supports <span className="text-foreground font-medium">tag-based filtering</span> — users can select one or more arXiv tags to view papers across primary categories. Tags can be combined with AND (intersection) or OR (union) logic. A keyword search further filters by paper title.</p>
        </Step>

        <Step number={9} icon={Sparkles} title="Impact Assessment">
          <p>Once a paper's ranking has converged, the system generates a structured <span className="text-foreground font-medium">AI Impact Assessment</span>. This summary evaluates the paper's novelty, applications, methodology, breadth of impact, and timeliness — drawing on both the paper's content and the reasoning from its tournament comparisons.</p>
        </Step>

        <Step number={10} icon={Trophy} title="Dynamic Leaderboard">
          <p>The leaderboard displays ranked papers with Elo score, win rate, confidence interval, match count, and publication date. All data is pre-computed in the background and served from cache for instant loading. Rankings update dynamically as new papers are fetched and compared. Users can filter by time period and search by keyword.</p>
        </Step>
      </div>

      <div className="mt-4 p-4 bg-secondary/30 rounded-lg border border-border text-xs text-muted-foreground">
        <p className="font-medium text-foreground mb-1">Limitations</p>
        <p>AI-based evaluation is an approximation of scientific impact, not a replacement for human peer review. Rankings reflect the consensus of three large language models. The matchmaker's preference for pairing similar-strength papers means pairwise agreement statistics are biased toward difficult comparisons. Using multiple models and random order assignment mitigates individual biases but cannot eliminate them entirely.</p>
      </div>
    </div>
  );
}
