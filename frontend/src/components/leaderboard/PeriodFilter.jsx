import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Clock, Calendar, CalendarDays, Infinity, Search, X, Lock } from "lucide-react";

const PERIODS = [
  { key: "recent", label: "Most Recent", icon: Clock },
  { key: "week", label: "Last 7 Days", icon: Calendar },
  { key: "month", label: "Last 30 Days", icon: CalendarDays },
  { key: "all", label: "All Time", icon: Infinity },
];

export function PeriodFilter({ period, setPeriod, keyword, setKeyword, isLoggedIn, requireAuth }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 mb-6">
      <div className="flex items-center gap-1 p-1 bg-secondary/50 rounded-lg overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-1" data-testid="period-filter">
        {PERIODS.map((p) => {
          const Icon = p.icon;
          const isLocked = !isLoggedIn && (p.key === "month" || p.key === "all");
          return isLocked ? (
            <Tooltip key={p.key}>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" onClick={requireAuth} className="gap-1.5 text-xs h-8 shrink-0 opacity-40" data-testid={`filter-${p.key}-locked`}>
                  <Lock className="h-3 w-3" /> {p.label}
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Sign in to access {p.label.toLowerCase()} view</p></TooltipContent>
            </Tooltip>
          ) : (
            <Button key={p.key} variant={period === p.key ? "default" : "ghost"} size="sm" onClick={() => setPeriod(p.key)} className="gap-1.5 text-xs h-8 shrink-0" data-testid={`filter-${p.key}`}>
              <Icon className="h-3.5 w-3.5" /> {p.label}
            </Button>
          );
        })}
      </div>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input placeholder="Search papers..." value={keyword} onChange={e => setKeyword(e.target.value)} className="h-8 text-xs pl-8 w-full sm:w-48" data-testid="keyword-search" />
        {keyword && (
          <button onClick={() => setKeyword("")} className="absolute right-2 top-1/2 -translate-y-1/2">
            <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
          </button>
        )}
      </div>
    </div>
  );
}
