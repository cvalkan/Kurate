import { Link } from "react-router-dom";
import {
  Search, Download, FileText, Swords, Bot, Trophy, BarChart3,
  ArrowRight, RefreshCw, Sparkles,
} from "lucide-react";

function Step({ number, icon: Icon, title, children }) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent/10 text-accent font-mono font-bold text-sm">
          {number}
        </div>
        <div className="w-px flex-1 bg-border mt-2" />
      </div>
      <div className="pb-10">
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
  return (
    <div className="container mx-auto px-4 md:px-6 max-w-3xl py-6 md:py-10">
      <div className="mb-10">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          Methodology
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          How PaperSumo ranks the latest Robotics papers using AI-powered pairwise comparison.
        </p>
      </div>

      <div>
        <Step number={1} icon={Search} title="Paper Discovery">
          <p>Every 24 hours, the system queries the arXiv API for the latest papers in the <span className="font-mono text-foreground text-xs bg-secondary px-1 py-0.5 rounded">cs.RO</span> (Robotics) category. New papers not already in the database are stored with their metadata — title, authors, abstract, publication date, and PDF link.</p>
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
          <p>Each model acts as a scientific paper evaluator, assessing which of the two papers has higher potential scientific impact. It considers five dimensions: novelty and innovation, real-world applications, methodological rigor, breadth of impact across fields, and timeliness. The model returns a winner and a brief reasoning.</p>
          <p>The evaluation prompt is fully customizable via the Admin panel.</p>
        </Step>

        <Step number={4} icon={RefreshCw} title="Adaptive Matchmaking">
          <p>The system uses an intelligent matchmaking algorithm to decide which papers to compare next. It balances several priorities:</p>
          <ul className="list-disc list-inside space-y-1 text-xs mt-1">
            <li><span className="text-foreground">New paper calibration</span> — Recent papers are matched against established top-ranked papers to ensure a fair entry into the leaderboard</li>
            <li><span className="text-foreground">Minimum coverage</span> — Every paper gets at least a configurable minimum number of matches</li>
            <li><span className="text-foreground">Top-K confidence</span> — Extra comparisons focus on papers near the top of the ranking to narrow their confidence intervals</li>
            <li><span className="text-foreground">UCB exploration</span> — An Upper Confidence Bound strategy ensures under-compared papers get their turn</li>
          </ul>
          <p className="mt-2">The system runs comparisons continuously until convergence goals are met, then idles until new papers arrive.</p>
        </Step>

        <Step number={5} icon={BarChart3} title="Bradley-Terry Scoring">
          <p>Rankings are computed using the <span className="text-foreground font-medium">Bradley-Terry model</span>, a well-established statistical method for deriving global rankings from pairwise comparisons. Raw Bradley-Terry parameters are converted to an Elo-like score centered at 1200, similar to <a href="https://lmarena.ai" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">LMArena</a>.</p>
          <p>Win rates are reported with <span className="text-foreground font-medium">95% Wilson confidence intervals</span>, providing a statistically rigorous measure of ranking certainty.</p>
        </Step>

        <Step number={6} icon={Bot} title="Multi-Model Consensus">
          <p>By randomly assigning GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro to each comparison, the system avoids single-model bias. The <Link to="/correlation" className="text-accent hover:underline">Model Analysis</Link> page shows how well the three models agree — typically 72–83% pairwise agreement with Spearman rank correlations of 0.62–0.68.</p>
        </Step>

        <Step number={7} icon={Sparkles} title="Impact Assessment">
          <p>Once a paper's ranking has converged (confidence interval below threshold or maximum matches reached), the system generates a structured <span className="text-foreground font-medium">AI Impact Assessment</span>. This summary evaluates the paper across five dimensions — novelty, real-world applications, methodological rigor, breadth of impact, and timeliness — drawing on both the paper's content and the reasoning from its tournament comparisons.</p>
        </Step>

        <Step number={8} icon={Trophy} title="Dynamic Leaderboard">
          <p>The final leaderboard displays all ranked papers with their Elo score, win rate, confidence interval, match count, and publication date. The rankings update dynamically as new papers are fetched and compared. Users can filter by time period — Today, This Week, This Month, or All Time — while scores remain globally consistent.</p>
        </Step>
      </div>

      <div className="mt-4 p-4 bg-secondary/30 rounded-lg border border-border text-xs text-muted-foreground">
        <p className="font-medium text-foreground mb-1">Limitations</p>
        <p>AI-based evaluation is an approximation of expert judgment, not a replacement. Rankings may differ from human expert consensus. The system evaluates papers based on available text content, which may miss contributions that require domain-specific expertise to fully appreciate. Using multiple models mitigates individual model biases but cannot eliminate them entirely.</p>
      </div>
    </div>
  );
}
