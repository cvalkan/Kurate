import { Bot } from "lucide-react";

const MODEL_COLORS = {
  openai: "bg-green-50 text-green-700 border-green-200",
  anthropic: "bg-orange-50 text-orange-700 border-orange-200",
  gemini: "bg-blue-50 text-blue-700 border-blue-200",
};

const MODEL_LABELS = {
  "gpt-5.2": "gpt-5.2",
  "claude-opus-4-6": "claude-opus-4.6",
  "claude-opus-4-5-20251101": "claude-opus-4.5",
  "gemini-3.1-pro-preview": "gemini-3.1",
  "gemini-3-pro-preview": "gemini-3",
};

function getLabel(model) {
  return MODEL_LABELS[model] || model?.split("-").slice(0, 2).join("-") || "?";
}

export function ModelBadge({ model }) {
  if (!model || !model.provider) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border ${MODEL_COLORS[model.provider] || "bg-secondary text-muted-foreground border-border"}`}>
      <Bot className="h-2.5 w-2.5" />
      {getLabel(model.model)}
    </span>
  );
}
