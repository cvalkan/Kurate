import { useState, useEffect, useCallback, useRef } from "react";
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
import { Switch } from "@/components/ui/switch";
import {
  Trophy, Clock, Calendar, CalendarDays, Infinity,
  Users, Swords, Activity, Tag, X, ChevronDown, ChevronUp, HelpCircle, Search, Globe, MapPin,
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
  const [tagMode, setTagMode] = useState("or"); // "or" or "and"
  const [tagFilterOpen, setTagFilterOpen] = useState(false);
  const [tagSearch, setTagSearch] = useState("");

  // Keyword search
  const [keyword, setKeyword] = useState("");

  // Global/Local stats toggle (tag mode only)
  const [globalStats, setGlobalStats] = useState(false);

  // Abort controller to cancel stale requests
  const abortRef = useRef(null);

  const categoryName = categories.find(c => c.id === category)?.name || "Papers";
  const hasSelectedTags = selectedTags.length > 0;
  const isTagMode = tagFilterOpen || hasSelectedTags;

  // Notify navbar of category/tag changes
  useEffect(() => {
    if (hasSelectedTags) {
      window.dispatchEvent(new CustomEvent("category-change", { detail: { tags: selectedTags } }));
    } else if (isTagMode) {
      window.dispatchEvent(new CustomEvent("category-change", { detail: { name: "All Papers" } }));
    } else if (categoryName && categoryName !== "Papers") {
      window.dispatchEvent(new CustomEvent("category-change", { detail: { name: categoryName } }));
    }
  }, [categoryName, isTagMode, hasSelectedTags, selectedTags]);

  // Load categories and tags once
  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      setCategories(res.data.categories || []);
      setCategory(res.data.default || "cs.RO");
    }).catch(() => {
      setCategories([{ id: "cs.RO", name: "Robotics" }]);
      setCategory("cs.RO");
    });
    axios.get(`${API}/api/tags`).then(res => {
      setAllTags(res.data.tags || []);
    }).catch(() => {});
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    if (!category && !isTagMode) return;

    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const params = { period };
      if (isTagMode && hasSelectedTags) {
        // Tag filter active: fetch matching papers
        params.tags = selectedTags.join(",");
        params.tag_mode = tagMode;
        params.global_stats = globalStats;
      } else if (isTagMode && !hasSelectedTags) {
        // Tag panel open, no tags selected: show all papers
        params.show_all = true;
      } else {
        // Normal category view
        params.category = category;
      }
      const res = await axios.get(`${API}/api/leaderboard`, { params, signal: controller.signal });
      // Only update if this request wasn't cancelled
      if (!controller.signal.aborted) {
        setLeaderboard(res.data.leaderboard || []);
        setTotalPapers(res.data.total_papers || 0);
        setTotalMatches(res.data.total_matches || 0);
        setIsRanking(res.data.is_ranking || false);
        setLoading(false);
      }
    } catch (err) {
      if (err.name !== "CanceledError" && err.code !== "ERR_CANCELED") {
        console.error("Failed to fetch leaderboard:", err);
        setLoading(false);
      }
    }
  }, [category, period, selectedTags, tagMode, isTagMode, hasSelectedTags, globalStats]);

  // Fetch on param change
  useEffect(() => {
    setLoading(true);
    fetchLeaderboard();
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [fetchLeaderboard]);

  // Auto-refresh only for primary category view (cached, fast). Skip for tag queries.
  useEffect(() => {
    if (isTagMode) return;
    const interval = setInterval(fetchLeaderboard, 30000);
    return () => clearInterval(interval);
  }, [fetchLeaderboard, isTagMode]);

  const toggleTag = (tagId) => {
    setSelectedTags(prev =>
      prev.includes(tagId) ? prev.filter(t => t !== tagId) : [...prev, tagId]
    );
  };

  const clearTags = () => {
    setSelectedTags([]);
    setTagFilterOpen(false);
    setTagSearch("");
    setGlobalStats(false);
  };

  const filteredTags = allTags.filter(t => {
    if (tagSearch && !t.id.toLowerCase().includes(tagSearch.toLowerCase())) return false;
    return true;
  });

  const title = hasSelectedTags
    ? `${selectedTags.join(tagMode === "and" ? " ∩ " : " ∪ ")} Papers`
    : isTagMode
    ? "All Papers"
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
          {hasSelectedTags
            ? `Cross-category view: showing papers tagged with ${selectedTags.join(tagMode === "and" ? " AND " : " OR ")}. Rankings based on available tournament matches.`
            : isTagMode
            ? "Showing all papers across all categories. Select tags below to filter."
            : `AI-estimated scientific impact ranking of the latest arXiv ${categoryName} papers. Papers are evaluated using full-text analysis by GPT-5.2, Claude Opus 4.5, and Gemini 3 Pro.`
          }
        </p>
      </div>

      {/* Category Tabs */}
      {categories.length > 1 && (
        <div className={`mb-3 -mx-4 px-4 overflow-x-auto transition-opacity ${isTagMode ? "opacity-40 pointer-events-none" : ""}`}>
          <div className="flex items-center gap-1 p-1 bg-primary/5 rounded-lg w-max" data-testid="category-tabs">
            {categories.map((c) => (
              <Button
                key={c.id}
                variant={!isTagMode && category === c.id ? "default" : "ghost"}
                size="sm"
                onClick={() => { setCategory(c.id); setSelectedTags([]); setTagFilterOpen(false); }}
                className="text-xs h-8 shrink-0"
                data-testid={`cat-${c.id}`}
                disabled={isTagMode}
              >
                {c.name}
              </Button>
            ))}
          </div>
          {isTagMode && (
            <p className="text-[10px] text-muted-foreground mt-1 ml-1">Category tabs disabled while tag filter is active</p>
          )}
        </div>
      )}

      {/* Tag Filter */}
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
              <p className="text-xs">Papers have multiple arXiv category tags (primary + secondary). Use this to view papers across categories. Select multiple tags and choose AND (intersection) or OR (union).</p>
            </TooltipContent>
          </Tooltip>

          {/* AND/OR toggle — show when 2+ tags selected */}
          {selectedTags.length >= 2 && (
            <div className="flex items-center gap-0.5 p-0.5 bg-secondary/50 rounded-md">
              <button
                onClick={() => setTagMode("or")}
                className={`px-2 py-0.5 text-[11px] rounded font-medium transition-colors ${tagMode === "or" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                OR
              </button>
              <button
                onClick={() => setTagMode("and")}
                className={`px-2 py-0.5 text-[11px] rounded font-medium transition-colors ${tagMode === "and" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                AND
              </button>
            </div>
          )}

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
          {(selectedTags.length > 0 || tagFilterOpen) && (
            <button onClick={clearTags} className="text-xs text-muted-foreground hover:text-foreground underline">
              {selectedTags.length > 0 ? "Clear all" : "Close"}
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
                return (
                  <button
                    key={tag.id}
                    onClick={() => toggleTag(tag.id)}
                    className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-colors ${
                      isSelected
                        ? "bg-primary text-primary-foreground border-primary"
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
      <div className="flex items-center gap-3 mb-6 text-xs flex-wrap" data-testid="status-bar">
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
        {hasSelectedTags && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
              <Tag className="h-3 w-3" />
              Cross-category {tagMode === "and" && selectedTags.length >= 2 ? "(AND)" : "(OR)"}
            </span>
          </>
        )}
        {isTagMode && !hasSelectedTags && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
              <Globe className="h-3 w-3" />
              All categories
            </span>
          </>
        )}
      </div>

      {/* Global/Local Stats Toggle — only when tags are selected */}
      {hasSelectedTags && (
        <div className="flex items-center gap-4 mb-4 p-2.5 bg-secondary/30 border border-border rounded-lg" data-testid="stats-toggle-bar">
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className={`flex items-center gap-1 text-xs font-medium cursor-help ${!globalStats ? "text-foreground" : "text-muted-foreground"}`}>
                  <MapPin className="h-3 w-3" />
                  Local
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-xs">
                <p className="text-xs">Stats computed only from matches between papers in the current filtered set. Win rates and match counts reflect head-to-head comparisons within this group.</p>
              </TooltipContent>
            </Tooltip>

            <Switch
              checked={globalStats}
              onCheckedChange={setGlobalStats}
              className="h-4 w-7"
              data-testid="global-local-toggle"
            />

            <Tooltip>
              <TooltipTrigger asChild>
                <div className={`flex items-center gap-1 text-xs font-medium cursor-help ${globalStats ? "text-foreground" : "text-muted-foreground"}`}>
                  <Globe className="h-3 w-3" />
                  Global
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-xs">
                <p className="text-xs">Stats from all tournament matches each paper has participated in, including matches against papers outside this filtered set. Gives the full picture of each paper's performance.</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      )}

      {/* Period Filter + Keyword Search */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 mb-6">
        <div className="flex items-center gap-1 p-1 bg-secondary/50 rounded-lg overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-1" data-testid="period-filter">
          {PERIODS.map((p) => {
            const Icon = p.icon;
            return (
              <Button
                key={p.key}
                variant={period === p.key ? "default" : "ghost"}
                size="sm"
                onClick={() => setPeriod(p.key)}
                className="gap-1.5 text-xs h-8 shrink-0"
                data-testid={`filter-${p.key}`}
              >
                <Icon className="h-3.5 w-3.5" />
                {p.label}
              </Button>
            );
          })}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search titles..."
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            className="h-8 text-xs pl-8 w-full sm:w-48"
            data-testid="keyword-search"
          />
          {keyword && (
            <button onClick={() => setKeyword("")} className="absolute right-2 top-1/2 -translate-y-1/2">
              <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
            </button>
          )}
        </div>
      </div>

      {/* Leaderboard Table */}
      {(() => {
        const kw = keyword.toLowerCase().trim();
        const displayList = kw
          ? leaderboard.filter(p => p.title.toLowerCase().includes(kw))
          : leaderboard;
        const isFiltered = kw && displayList.length !== leaderboard.length;

        // Helper: pick the right stat based on Global/Local toggle
        const getWinRate = (paper) => {
          if (hasSelectedTags && globalStats && paper.global_win_rate !== undefined) return paper.global_win_rate;
          return paper.win_rate;
        };
        const getComparisons = (paper) => {
          if (hasSelectedTags && globalStats && paper.global_comparisons !== undefined) return paper.global_comparisons;
          return paper.comparisons;
        };
        const getWilsonMargin = (paper) => {
          if (hasSelectedTags && globalStats) return null;
          return paper.wilson_margin;
        };

        const showCatCol = isTagMode;

        return loading ? (
        <div className="space-y-3" data-testid="loading-skeleton">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 bg-secondary/30 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : displayList.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground" data-testid="empty-state">
          <Trophy className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">
            {kw ? `No papers matching "${keyword}".` : `No papers found for this ${hasSelectedTags ? "tag combination" : "period"}.`}
          </p>
          <p className="text-xs mt-1">{kw ? "Try different keywords." : hasSelectedTags ? "Try different tags, switch to OR mode, or clear the filter." : "Try a broader time range."}</p>
        </div>
      ) : (
        <>
        {isFiltered && (
          <div className="text-xs text-muted-foreground mb-2">
            Showing {displayList.length} of {leaderboard.length} papers matching "{keyword}"
          </div>
        )}
        <div className="border border-border rounded-lg overflow-x-auto" data-testid="leaderboard-table">
          <div className={`grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4 py-2.5 bg-secondary/50 text-xs font-medium text-muted-foreground border-b border-border ${
            showCatCol
              ? "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4rem_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_4.5rem_5rem_4.5rem_4.5rem_4rem_7rem]"
              : "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem]"
          }`}>
            <div>#</div>
            <div>Paper</div>
            {showCatCol && <div className="text-center hidden sm:block">Cat</div>}
            <div className="text-right">Score</div>
            <div className="text-right hidden sm:block">
              {hasSelectedTags && globalStats ? "Win % (G)" : "Win %"}
            </div>
            <div className="text-right hidden sm:block">95% CI</div>
            <div className="text-right hidden sm:block">
              {hasSelectedTags && globalStats ? "Mtch (G)" : "Mtch"}
            </div>
            <div className="text-right hidden md:block">Published</div>
          </div>
          {displayList.map((paper, idx) => (
            <Link
              key={paper.id}
              to={`/paper/${paper.id}`}
              className={`grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4 py-2 sm:py-3 items-center border-b border-border/50 hover:bg-secondary/30 transition-colors cursor-pointer ${
                showCatCol
                  ? "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4rem_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_4.5rem_5rem_4.5rem_4.5rem_4rem_7rem]"
                  : "grid-cols-[2rem_1fr_3rem] sm:grid-cols-[2.5rem_1fr_4.5rem_4rem_4rem_4rem] md:grid-cols-[3rem_1fr_5rem_4.5rem_4.5rem_4rem_7rem]"
              } ${idx < 3 && !kw ? "bg-accent/[0.02]" : ""}`}
              data-testid={`leaderboard-row-${idx}`}
            >
              <div><RankBadge rank={paper.rank} /></div>
              <div className="min-w-0">
                <p className="text-xs sm:text-sm font-medium truncate leading-tight" title={paper.title}>{paper.title}</p>
                <p className="text-[10px] sm:text-xs text-muted-foreground truncate mt-0.5">
                  {paper.authors?.slice(0, 2).join(", ")}
                  {paper.authors?.length > 2 && ` +${paper.authors.length - 2}`}
                </p>
              </div>
              {showCatCol && (
                <div className="text-center hidden sm:block">
                  <span className="inline-block text-[9px] px-1.5 py-0.5 rounded font-mono bg-secondary text-muted-foreground">
                    {paper.primary_category || "?"}
                  </span>
                </div>
              )}
              <div className="text-right font-mono text-xs sm:text-sm font-medium">{paper.score}</div>
              <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground hidden sm:block">{getWinRate(paper)}%</div>
              <div className="text-right font-mono text-xs text-muted-foreground hidden sm:block">
                {(() => {
                  const wm = getWilsonMargin(paper);
                  return wm != null && wm > 0 ? `\u00B1${wm}%` : "--";
                })()}
              </div>
              <div className="text-right font-mono text-[10px] sm:text-xs text-muted-foreground hidden sm:block">{getComparisons(paper)}</div>
              <div className="text-right text-xs text-muted-foreground hidden md:block">
                {paper.published ? new Date(paper.published).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "--"}
              </div>
            </Link>
          ))}
        </div>
        </>
      );
      })()}

      <div className="mt-6 text-center text-xs text-muted-foreground">
        {hasSelectedTags
          ? "Cross-category rankings based on available tournament matches between tagged papers."
          : isTagMode
          ? "All papers ranked by their tournament performance within their primary categories."
          : "Elo-style ratings from Bradley-Terry model with 95% confidence intervals. Papers compared using full-text deep analysis."
        }
      </div>
    </div>
    </TooltipProvider>
  );
}
