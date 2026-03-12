import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { Archive, ChevronLeft, Calendar } from "lucide-react";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ArchivePage() {
  const { category, year, weekOrMonth } = useParams();
  const [archive, setArchive] = useState(null);
  const [loading, setLoading] = useState(true);

  // Parse week/month from URL
  const isWeekly = weekOrMonth?.startsWith("w");
  const num = parseInt(weekOrMonth?.replace(/^[wm]/, ""), 10);

  useEffect(() => {
    const url = isWeekly
      ? `${API}/api/archive/${category}/${year}/w${num}`
      : `${API}/api/archive/${category}/${year}/m${num}`;
    axios.get(url).then(res => {
      if (res.data.status === "not_found") {
        setArchive(null);
      } else {
        setArchive(res.data);
      }
    }).catch(() => setArchive(null))
      .finally(() => setLoading(false));
  }, [category, year, num, isWeekly]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10">
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-secondary/30 rounded-lg animate-pulse" />)}
        </div>
      </div>
    );
  }

  if (!archive) {
    return (
      <div className="container mx-auto px-4 md:px-6 max-w-7xl py-10 text-center">
        <Archive className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <h1 className="text-lg font-semibold mb-2">Archive Not Found</h1>
        <p className="text-sm text-muted-foreground mb-4">
          No snapshot exists for {category} {isWeekly ? `Week ${num}` : `Month ${num}`}, {year}.
        </p>
        <Link to="/" className="text-accent hover:underline text-sm">Back to leaderboard</Link>
      </div>
    );
  }

  const entries = archive.leaderboard || [];

  return (
    <TooltipProvider delayDuration={200}>
      <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
        <div className="mb-6">
          <Link to={`/?cat=${category}`} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-2">
            <ChevronLeft className="h-3 w-3" /> Back to live leaderboard
          </Link>
          <div className="flex items-center gap-3 mb-1">
            <Archive className="h-5 w-5 text-accent" />
            <h1 className="font-heading text-2xl md:text-3xl font-semibold tracking-tight" data-testid="archive-title">
              {archive.label}
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Frozen leaderboard snapshot for <span className="font-medium text-foreground">{category}</span>.
            {" "}{entries.length} papers, {archive.match_count?.toLocaleString()} matches.
            {" "}Archived {new Date(archive.created_at).toLocaleDateString()}.
          </p>
        </div>

        <div className="border border-border rounded-lg overflow-hidden" data-testid="archive-table">
          <LeaderboardTable
            leaderboard={entries}
            displayCount={entries.length}
            sortKey="rank"
            sortDir="asc"
            onSort={() => {}}
            showRatingCol={entries.some(e => e.ai_rating)}
            showGapCol={entries.some(e => e.sp_score)}
          />
        </div>

        <div className="mt-6 text-center">
          <Link to={`/?cat=${category}&period=week`} className="text-xs text-accent hover:underline">
            View current live leaderboard for {category}
          </Link>
        </div>
      </div>
    </TooltipProvider>
  );
}
