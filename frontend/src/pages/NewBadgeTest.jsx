import { Link } from "react-router-dom";
import { Sparkles, Plus, Zap, Bell, Star } from "lucide-react";

const CATEGORIES = "Computer Vision, HCI, General Relativity, Number Theory";

export default function NewBadgeTest() {
  return (
    <div className="container mx-auto px-6 max-w-4xl py-10 space-y-16">
      <h1 className="text-2xl font-bold mb-2">New Category Badge — 5 Variants</h1>
      <p className="text-sm text-muted-foreground mb-8">Each variant shown in context with the subtitle line.</p>

      {/* Variant A: Green pill (current) */}
      <div className="space-y-1">
        <h2 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">A — Green pill</h2>
        <div className="p-6 rounded-xl border border-border">
          <h3 className="font-heading text-3xl font-semibold tracking-tight mb-2">Artificial Intelligence Paper Rankings</h3>
          <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
            AI-estimated scientific impact ranking of the latest arXiv Artificial Intelligence preprints.{" "}
            <Link to="/" className="text-accent hover:underline">Methodology</Link>{" "}
            <span className="inline-flex items-center gap-1 ml-1 text-xs font-medium text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 dark:text-emerald-400 px-2 py-0.5 rounded-full">
              New: {CATEGORIES}
            </span>
          </p>
        </div>
      </div>

      {/* Variant B: Subtle inline with sparkle icon */}
      <div className="space-y-1">
        <h2 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">B — Sparkle inline, warm amber</h2>
        <div className="p-6 rounded-xl border border-border">
          <h3 className="font-heading text-3xl font-semibold tracking-tight mb-2">Artificial Intelligence Paper Rankings</h3>
          <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
            AI-estimated scientific impact ranking of the latest arXiv Artificial Intelligence preprints.{" "}
            <Link to="/" className="text-accent hover:underline">Methodology</Link>{" "}
            <span className="inline-flex items-center gap-1 ml-1 text-xs text-amber-600 dark:text-amber-400">
              <Sparkles className="h-3 w-3" /> Newly added: {CATEGORIES}
            </span>
          </p>
        </div>
      </div>

      {/* Variant C: Blue outline badge */}
      <div className="space-y-1">
        <h2 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">C — Blue outline badge</h2>
        <div className="p-6 rounded-xl border border-border">
          <h3 className="font-heading text-3xl font-semibold tracking-tight mb-2">Artificial Intelligence Paper Rankings</h3>
          <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
            AI-estimated scientific impact ranking of the latest arXiv Artificial Intelligence preprints.{" "}
            <Link to="/" className="text-accent hover:underline">Methodology</Link>{" "}
            <span className="inline-flex items-center gap-1 ml-1 text-[11px] font-medium text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 px-2 py-0.5 rounded-md">
              <Plus className="h-2.5 w-2.5" /> {CATEGORIES}
            </span>
          </p>
        </div>
      </div>

      {/* Variant D: Gradient background, bolder */}
      <div className="space-y-1">
        <h2 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">D — Gradient pill, bold</h2>
        <div className="p-6 rounded-xl border border-border">
          <h3 className="font-heading text-3xl font-semibold tracking-tight mb-2">Artificial Intelligence Paper Rankings</h3>
          <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
            AI-estimated scientific impact ranking of the latest arXiv Artificial Intelligence preprints.{" "}
            <Link to="/" className="text-accent hover:underline">Methodology</Link>{" "}
            <span className="inline-flex items-center gap-1 ml-1 text-xs font-semibold text-white bg-gradient-to-r from-violet-500 to-indigo-500 px-2.5 py-0.5 rounded-full shadow-sm">
              <Zap className="h-3 w-3" /> New: {CATEGORIES}
            </span>
          </p>
        </div>
      </div>

      {/* Variant E: Minimal, muted text with dot indicator */}
      <div className="space-y-1">
        <h2 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">E — Minimal dot + muted text</h2>
        <div className="p-6 rounded-xl border border-border">
          <h3 className="font-heading text-3xl font-semibold tracking-tight mb-2">Artificial Intelligence Paper Rankings</h3>
          <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
            AI-estimated scientific impact ranking of the latest arXiv Artificial Intelligence preprints.{" "}
            <Link to="/" className="text-accent hover:underline">Methodology</Link>{" "}
            <span className="inline-flex items-center gap-1.5 ml-2 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> New fields: {CATEGORIES}
            </span>
          </p>
        </div>
      </div>

    </div>
  );
}
