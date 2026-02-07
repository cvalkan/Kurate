import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Trophy, Clock, Calendar, CalendarDays, Infinity,
  Users, Swords, Activity, Tag, X, ChevronDown, ChevronUp, HelpCircle,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const PERIODS = [
  { key: "recent", label: "Most Recent", icon: Clock },
  { key: "week", label: "This Week", icon: Calendar },
  { key: "month", label: "This Month", icon: CalendarDays },
  { key: "all", label: "All Time", icon: Infinity },
];

function RankBadge({ rank }) {
  if (rank === 1) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-amber-100 text-amber-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>1</span>;
  if (rank === 2) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-slate-100 text-slate-600 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>2</span>;
  if (rank === 3) return <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-orange-100 text-orange-700 font-mono font-bold text-sm" data-testid={`rank-${rank}`}>3</span>;
  return <span className="inline-flex items-center justify-center w-7 h-7 font-mono text-sm text-muted-foreground" data-testid={`rank-${rank}`}>{rank}</span>;
}

export default function LeaderboardPage() {
  const [leaderboard, setLeaderboard] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");
  const [period, setPeriod] = useState("week");
  const [loading, setLoading] = useState(true);
  const [totalPapers, setTotalPapers] = useState(0);
  const [totalMatches, setTotalMatches] = useState(0);
  const [isRanking, setIsRanking] = useState(false);

  // Tag filter state
  const [allTags, setAllTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [tagFilterOpen, setTagFilterOpen] = useState(false);
  const [tagSearch, setTagSearch] = useState("");

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";
  const isTagMode = selectedTags.length > 0;

  // Load categories once
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      setCategory(res.data.default || "cs.RO");
    }).catch(() => {
      setCategories([{ id: "cs.RO", name: "Robotics" }]);
      setCategory("cs.RO");
    });
    // Load all tags
    axios.get(`${API}/api/tags`).then(res => {
      setAllTags(res.data.tags || []);
    }).catch(() => {});
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    if (!category && !isTagMode) return;
    try {
      const params = { period };
      if (isTagMode) {
        params.tags = selectedTags.join(",");
      } else {
        params.category = category;
      }
      const res = await axios.get(`${API}/api/leaderboard`, { params });
      setLeaderboard(res.data.leaderboard || []);
      setTotalPapers(res.data.total_papers || 0);
      setTotalMatches(res.data.total_matches || 0);
      setIsRanking(res.data.is_ranking || false);
    } catch (err) {
      console.error("Failed to fetch leaderboard:", err);
    } finally {
      setLoading(false);
    }
  }, [category, period, selectedTags, isTagMode]);

  useEffect(() => {
    setLoading(true);
    fetchLeaderboard();
  }, [fetchLeaderboard]);

  useEffect(() => {
    const interval = setInterval(fetchLeaderboard, 30000);
    return () => clearInterval(interval);
  }, [fetchLeaderboard]);

  const toggleTag = (tagId) => {
    setSelectedTags(prev =>
      prev.includes(tagId) ? prev.filter(t => t !== tagId) : [...prev, tagId]
    );
  };

  const clearTags = () => {
    setSelectedTags([]);
    setTagFilterOpen(false);
    setTagSearch("");
  };

  // Filter tags by search and exclude already-selected
  const mainCatIds = new Set(categories.map(c => c.id));
  const filteredTags = allTags.filter(t => {
    if (tagSearch && !t.id.toLowerCase().includes(tagSearch.toLowerCase())) return false;
    return true;
  });

  const title = isTagMode
    ? `${selectedTags.join(" + ")} Papers`
    : `${categoryName} Paper Rankings`;

  return (
    <TooltipProvider delayDuration={200}>
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-3xl md:text-4xl font-semibold tracking-tight mb-2" data-testid="page-title">
          {title}
        </h1>
        <p className="text-muted-foreground text-sm md:text-base max-w-2xl">
          {isTagMode
            ? `Cross-category view: showing all papers tagged with ${selectedTags.join(", ")}. Rankings based on available tournament matches.`
            : `AI-estimated scientific impact ranking of the latest arXiv ${categoryName} papers. Papers are evaluated using full-text analysis by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.`
          }
        </p>
      </div>

      {/* Category Tabs */}
      {categories.length > 1 && (
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg" data-testid="category-tabs">
            {categories.map((c) => (
              <Button
                key={c.id}
                variant={!isTagMode && category === c.id ? "default" : "ghost"}
                size="sm"
                onClick={() => { setCategory(c.id); setSelectedTags([]); setLoading(true); }}
                className="text-xs h-8"
                data-testid={`cat-${c.id}`}
              >
                {c.name}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* Tag Filter Toggle */}
      <div className="mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant={tagFilterOpen ? "default" : "outline"}
            size="sm"
            onClick={() => setTagFilterOpen(!tagFilterOpen)}
            className="gap-1.5 text-xs h-7"
            data-testid="tag-filter-toggle"
          >
            <Tag className="h-3 w-3" />
            Filter by tags
            {tagFilterOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-xs">
              <p className="text-xs">Papers often have multiple arXiv category tags. Use this filter to view papers across categories — e.g., find all papers tagged "cs.AI" regardless of their primary category. Select multiple tags to combine.</p>
            </TooltipContent>
          </Tooltip>

          {/* Selected tag chips */}
          {selectedTags.map(tag => (
            <Badge
              key={tag}
              variant="secondary"
              className="gap-1 text-xs cursor-pointer hover:bg-destructive/10"
              onClick={() => toggleTag(tag)}
            >
              {tag}
              <X className="h-3 w-3" />
            </Badge>
          ))}
          {selectedTags.length > 0 && (
            <button onClick={clearTags} className="text-xs text-muted-foreground hover:text-foreground underline">
              Clear all
            </button>
          )}
        </div>

        {/* Expanded tag panel */}
        {tagFilterOpen && (
          <div className="mt-2 p-3 bg-secondary/30 border border-border rounded-lg" data-testid="tag-panel">
            <Input
              placeholder="Search tags (e.g. cs.AI, physics)..."
              value={tagSearch}
              onChange={e => setTagSearch(e.target.value)}
              className="h-8 text-xs mb-2 max-w-xs"
            />
            <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
              {filteredTags.map(tag => {
                const isSelected = selectedTags.includes(tag.id);
                const isMain = mainCatIds.has(tag.id);
                return (
                  <button
                    key={tag.id}
                    onClick={() => toggleTag(tag.id)}
                    className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-colors ${
                      isSelected
                        ? "bg-primary text-primary-foreground border-primary"
                        : isMain
                          ? "bg-primary/10 text-primary border-primary/30 hover:bg-primary/20"
                          : "bg-background text-muted-foreground border-border hover:bg-secondary"
                    }`}
                  >
                    {tag.id}
                    <span className={`font-mono text-[10px] ${isSelected ? "text-primary-foreground/70" : "text-muted-foreground/60"}`}>
                      {tag.count}
                    </span>
                  </button>
                );
              })}
              {filteredTags.length === 0 && (
                <span className="text-xs text-muted-foreground">No matching tags</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Status Bar */}
      <div className="flex items-center gap-3 mb-6 text-xs flex-nowrap" data-testid="status-bar">
        <div className="flex items-center gap-1.5 text-muted-foreground shrink-0">
          <Users className="h-3.5 w-3.5" />
          <span className="font-mono">{totalPapers}</span>
          <span>papers</span>
        </div>
        <div className="w-px h-3 bg-border shrink-0" />
        <div className="flex items-center gap-1.5 text-muted-foreground shrink-0">
          <Swords className="h-3.5 w-3.5" />
          <span className="font-mono">{totalMatches}</span>
          <span>comparisons</span>
        </div>
        {isRanking && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <span className="inline-flex items-center gap-1 text-xs text-accent animate-pulse shrink-0">
              <Activity className="h-3 w-3" />
              Ranking in progress
            </span>
          </>
        )}
        {isTagMode && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
              <Tag className="h-3 w-3" />
              Cross-category view
            </span>
          </>
        )}
      </div>

      {/* Period Filter */}
      <div className="flex items-center gap-1 mb-6 p-1 bg-secondary/50 rounded-lg w-fit" data-testid="period-filter">
        {PERIODS.map((p) => {
          const Icon = p.icon;
          return (
            <Button
              key={p.key}
              variant={period === p.key ? "default" : "ghost"}
              size="sm"
              onClick={() => setPeriod(p.key)}
              className="gap-1.5 text-xs h-8"
              data-testid={`filter-${p.key}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {p.label}
            </Button>
          );
        })}
      </div>

      {/* Leaderboard Table */}
      {loading ? (
        <div className="space-y-3" data-testid="loading-skeleton">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : leaderboard.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground" data-testid="empty-state">
          <Trophy className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No papers found for this {isTagMode ? "tag combination" : "period"}.</p>
          <p className="text-xs mt-1">{isTagMode ? "Try different tags or clear the filter." : "Try a broader time range or wait for the next daily fetch."}</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="leaderboard-table">
          {/* Table Header */}
          <div className="grid grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem] gap-2 px-3 md:px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border">
            <div>#</div>
            <div>Paper</div>
            <div className="text-right">Score</div>
            <div className="text-right">Win %</div>
            <div className="text-right">95% CI</div>
            <div className="text-right">Matches</div>
            <div className="text-right hidden md:block">Published</div>
          </div>

          {/* Table Body */}
          {leaderboard.map((paper, idx) => (
            <Link
              key={paper.id}
              to={`/paper/${paper.id}`}
              className={`grid grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem] gap-2 px-3 md:px-4 py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${
                idx < 3 ? "bg-accent/[0.02]" : ""
              }`}
              data-testid={`leaderboard-row-${idx}`}
            >
              <div><RankBadge rank={paper.rank} /></div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate leading-tight" title={paper.title}>
                  {paper.title}
                </p>
                <p className="text-xs text-muted-foreground truncate mt-0.5">
                  {paper.authors?.slice(0, 3).join(", ")}
                  {paper.authors?.length > 3 && ` +${paper.authors.length - 3}`}
                </p>
              </div>
              <div className="text-right font-mono text-sm font-medium">{paper.score}</div>
              <div className="text-right font-mono text-xs text-muted-foreground">{paper.win_rate}%</div>
              <div className="text-right font-mono text-xs text-muted-foreground">
                {paper.wilson_margin > 0 ? `\u00B1${paper.wilson_margin}%` : "--"}
              </div>
              <div className="text-right font-mono text-xs text-muted-foreground">{paper.comparisons}</div>
              <div className="text-right text-xs text-muted-foreground hidden md:block">
                {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "--"}
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Footer Info */}
      <div className="mt-6 text-center text-xs text-muted-foreground">
        {isTagMode
          ? "Cross-category rankings based on available tournament matches between tagged papers."
          : "Elo-style ratings from Bradley-Terry model with 95% confidence intervals. Papers compared using full-text deep analysis."
        }
      </div>
    </div>
    </TooltipProvider>
  );
}
