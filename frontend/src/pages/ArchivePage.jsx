import { useState, useEffect, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { Archive, ChevronLeft, Search } from "lucide-react";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";

const API = process.env.REACT_APP_BACKEND_URL;

const CATEGORY_NAMES = {
  "cs.RO": "Robotics", "cs.DC": "Distributed Computing", "econ.GN": "Economics",
  "physics.comp-ph": "Computational Physics", "q-bio.BM": "Biomolecules",
  "cs.GT": "Game Theory", "physics.chem-ph": "Chemical Physics",
  "chemrxiv.IC": "Inorganic Chemistry", "cs.CR": "Cryptography & Security",
  "cs.IT": "Information Theory", "quant-ph": "Quantum Physics",
  "astro-ph.CO": "Cosmology & Astrophysics", "cond-mat.mtrl-sci": "Materials Science",
  "cs.AI": "Artificial Intelligence", "cs.SI": "Social & Information Networks",
  "q-fin.CP": "Quantitative Finance",
};

export default function ArchivePage() {
  const { category, year, weekOrMonth } = useParams();
  const [archive, setArchive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState("rank");
  const [sortDir, setSortDir] = useState("asc");
  const [keyword, setKeyword] = useState("");

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

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "title" || key === "published" ? "asc" : "desc");
    }
  };

  const sortedEntries = useMemo(() => {
    if (!archive?.leaderboard) return [];
    let data = [...archive.leaderboard];

    // Filter by keyword
    if (keyword.trim()) {
      const kw = keyword.toLowerCase();
      data = data.filter(e =>
        (e.title || "").toLowerCase().includes(kw) ||
        (e.authors || []).some(a => a.toLowerCase().includes(kw))
      );
    }

    // Default: preserve array order (position = rank)
    if (!sortKey || sortKey === "rank") {
      return sortDir === "desc" ? [...data].reverse() : data;
    }

    // Non-default sort
    const key = sortKey === "score" ? "score"
      : sortKey === "wilson_margin" ? "ts_sigma"
      : sortKey === "gap_score" ? "gap_score"
      : sortKey;
    const dir = sortDir || "desc";
    data.sort((a, b) => {
      let va = a[key], vb = b[key];
      if (typeof va === "string" && typeof vb === "string") {
        return dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      va = va ?? (dir === "asc" ? Infinity : -Infinity);
      vb = vb ?? (dir === "asc" ? Infinity : -Infinity);
      return dir === "asc" ? va - vb : vb - va;
    });

    return data;
  }, [archive, sortKey, sortDir, keyword]);

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
              {CATEGORY_NAMES[category] || category} Papers — {archive.label}
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Leaderboard snapshot.
            {" "}{entries.length} preprints from arXiv ({category}), {archive.match_count?.toLocaleString()} matches.
          </p>
        </div>

        <div className="mb-4">
          <div className="relative max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              placeholder="Search papers..."
              className="pl-8 h-8 text-sm"
              data-testid="archive-search"
            />
          </div>
        </div>

        <div className="border border-border rounded-lg overflow-hidden" data-testid="archive-table">
          <LeaderboardTable
            leaderboard={sortedEntries}
            displayCount={sortedEntries.length}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
            showRatingCol={entries.some(e => e.ai_rating)}
            showGapCol={entries.some(e => e.gap_score != null)}
            scoringMethod="ts"
          />
        </div>

        <div className="mt-6 text-center">
          <Link to={`/?cat=${category}&period=all`} className="text-xs text-accent hover:underline">
            View All Time leaderboard for {CATEGORY_NAMES[category] || category}
          </Link>
        </div>
      </div>
    </TooltipProvider>
  );
}
