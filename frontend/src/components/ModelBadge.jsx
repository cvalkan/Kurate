import { Bot } from "lucide-react";

const MODEL_COLORS = {
  openai: "bg-green-50 text-green-700 border-green-200",
  anthropic: "bg-orange-50 text-orange-700 border-orange-200",
  gemini: "bg-blue-50 text-blue-700 border-blue-200",
};

export function ModelBadge({ model }) {
  if (!model || !model.provider) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border ${MODEL_COLORS[model.provider] || "bg-secondary text-muted-foreground border-border"}`}>
      <Bot className="h-2.5 w-2.5" />
      {model.model?.split("-").slice(0, 2).join("-") || model.provider}
    </span>
  );
}
