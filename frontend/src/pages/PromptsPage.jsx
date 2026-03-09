import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { FileText, ArrowLeft, Bot, Sparkles } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function PromptBlock({ label, icon: Icon, systemPrompt, userPrompt }) {
  if (!systemPrompt) return null;
  return (
    <div className="space-y-4" data-testid={`prompt-block-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-accent" />
        <h2 className="font-heading font-medium text-lg">{label}</h2>
      </div>
      <div className="space-y-3">
        <div>
          <h3 className="text-xs uppercase tracking-wide text-muted-foreground mb-2">System Prompt</h3>
          <pre className="text-sm leading-relaxed whitespace-pre-wrap bg-secondary/30 border border-border rounded-lg p-4 font-mono" data-testid={`${label.toLowerCase().replace(/\s+/g, "-")}-system`}>
            {systemPrompt}
          </pre>
        </div>
        <div>
          <h3 className="text-xs uppercase tracking-wide text-muted-foreground mb-2">User Prompt Template</h3>
          <pre className="text-sm leading-relaxed whitespace-pre-wrap bg-secondary/30 border border-border rounded-lg p-4 font-mono" data-testid={`${label.toLowerCase().replace(/\s+/g, "-")}-user`}>
            {userPrompt}
          </pre>
        </div>
      </div>
    </div>
  );
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/api/prompts`).then(res => {
      setPrompts(res.data);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-3xl py-6 md:py-10">
      <Link to="/methodology" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors" data-testid="back-to-methodology">
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Methodology
      </Link>

      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="prompts-title">
          Evaluation Prompts
        </h1>
        <p className="text-muted-foreground text-sm max-w-2xl">
          The exact prompts used by the AI models to evaluate and compare papers. These define the criteria and output format for each judgment.
        </p>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground">Loading prompts...</div>
      ) : !prompts ? (
        <div className="text-sm text-muted-foreground">Failed to load prompts.</div>
      ) : (
        <div className="space-y-10">
          <PromptBlock
            label="Comparison Prompt"
            icon={Bot}
            systemPrompt={prompts.evaluation?.system_prompt}
            userPrompt={prompts.evaluation?.user_prompt}
          />
          {prompts.summary && (
            <PromptBlock
              label="AI Impact Summary Prompt"
              icon={Sparkles}
              systemPrompt={prompts.summary?.system_prompt}
              userPrompt={prompts.summary?.user_prompt}
            />
          )}
          {prompts.rating_extraction && (
            <PromptBlock
              label="Rating Extraction Prompt"
              icon={Bot}
              systemPrompt={prompts.rating_extraction?.system_prompt}
              userPrompt={prompts.rating_extraction?.user_prompt}
            />
          )}
          {prompts.single_item && (
            <PromptBlock
              label="Single-Item Scoring Prompt (Validation)"
              icon={Sparkles}
              systemPrompt={prompts.single_item?.system_prompt}
              userPrompt={prompts.single_item?.user_prompt}
            />
          )}
        </div>
      )}

      <div className="mt-8 p-4 bg-secondary/30 rounded-lg border border-border text-xs text-muted-foreground">
        <p>Template variables like <code className="font-mono text-foreground">{"{paper1_title}"}</code> are replaced with actual paper data at runtime. The models must respond with structured JSON containing a winner and reasoning.</p>
      </div>
    </div>
  );
}
