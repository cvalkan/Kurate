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
          <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">Stats computed only from matches between papers in the current filtered set.</p></TooltipContent>
        </Tooltip>
        <Switch checked={globalStats} onCheckedChange={setGlobalStats} className="h-4 w-7" data-testid="global-local-toggle" />
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={`flex items-center gap-1 text-xs font-medium cursor-help ${globalStats ? "text-foreground" : "text-muted-foreground"}`}>
              <Globe className="h-3 w-3" /> Global
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs"><p className="text-xs">Stats from all tournament matches each paper has participated in, using Bradley-Terry scores across all categories.</p></TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
