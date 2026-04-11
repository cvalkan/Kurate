import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Globe, MapPin } from "lucide-react";

export function StatsToggle({ globalStats, setGlobalStats }) {
  return (
    <div className="flex items-center gap-4 mb-4 p-2.5 bg-secondary/30 border border-border rounded-lg" data-testid="stats-toggle-bar">
      <div className="flex items-center gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={`flex items-center gap-1 text-xs font-medium cursor-help ${!globalStats ? "text-foreground" : "text-muted-foreground"}`}>
              <MapPin className="h-3 w-3" /> Local
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">Recomputes win-rate stats from only matches between papers in the current filtered set. Sorted by local win-rate (the only metric computable from a match subset).</p></TooltipContent>
        </Tooltip>
        <Switch checked={globalStats} onCheckedChange={setGlobalStats} className="h-4 w-7" data-testid="global-local-toggle" />
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={`flex items-center gap-1 text-xs font-medium cursor-help ${globalStats ? "text-foreground" : "text-muted-foreground"}`}>
              <Globe className="h-3 w-3" /> Global
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">Each paper's TrueSkill score from all tournament matches in its primary category. Default ranking metric.</p></TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
