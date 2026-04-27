import { useState } from "react";
import { Sparkles, ArrowRight, Bookmark, Layers, CalendarRange, Tags, Lightbulb } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function SignupCTA({ onClick, categories = [] }) {
  // Controlled tooltip: open on hover (desktop) AND on tap (mobile).
  // Mouse handlers cover desktop hover; onClick covers tap-to-open on touch
  // devices where hover is unreliable.
  const [open, setOpen] = useState(false);
  const categoryNames = categories.map(c => c.name).filter(Boolean).join(", ");
  const perks = [
    { icon: Layers, label: "Browse all available categories", detail: categoryNames || "All arXiv & chemRxiv fields tracked on Kurate" },
    { icon: CalendarRange, label: "Monthly & all-time rankings", detail: "Beyond the default last-7-day window" },
    { icon: Tags, label: "Cross-category tag filters", detail: "Filter the leaderboard by tag combinations" },
    { icon: Bookmark, label: "Bookmark papers", detail: "Build personalized reading lists" },
    { icon: Lightbulb, label: "Suggest new fields", detail: "Vote on which arXiv categories to add next" },
  ];
  return (
    <div
      className="mb-6 rounded-lg border border-accent/25 bg-accent/[0.07] px-4 py-3 sm:px-5 sm:py-3.5 flex items-center justify-between gap-3 sm:gap-4"
      data-testid="signup-cta-banner"
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="hidden sm:flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
          <Sparkles className="h-4 w-4" />
        </div>
        <p className="text-sm sm:text-[15px] leading-snug text-foreground">
          <span className="font-medium">Sign up for free</span>
          <span className="text-muted-foreground"> to unlock all papers &{" "}</span>
          <Tooltip open={open} onOpenChange={setOpen}>
            <TooltipTrigger asChild>
              <button
                type="button"
                onMouseEnter={() => setOpen(true)}
                onMouseLeave={() => setOpen(false)}
                onClick={() => setOpen(o => !o)}
                className="underline decoration-dotted underline-offset-[3px] decoration-muted-foreground/60 cursor-help text-foreground focus:outline-none"
                data-testid="signup-cta-more-trigger"
              >
                more
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="start" className="max-w-xs p-3" data-testid="signup-cta-perks">
              <p className="text-xs font-semibold mb-2">What you get with a free account</p>
              <ul className="space-y-1.5">
                {perks.map(({ icon: Icon, label, detail }) => (
                  <li key={label} className="flex items-start gap-2">
                    <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-accent" />
                    <div className="min-w-0">
                      <div className="text-xs font-medium leading-tight">{label}</div>
                      <div className="text-[11px] opacity-80 leading-tight">{detail}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </TooltipContent>
          </Tooltip>
        </p>
      </div>
      <button
        onClick={onClick}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-md bg-accent text-accent-foreground px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm font-medium hover:bg-accent/90 transition-colors"
        data-testid="signup-cta-button"
      >
        Sign up
        <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
