import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Archive, ArrowLeft, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { LeaderboardTableNew } from "@/components/leaderboard/LeaderboardTableNew";
import { useBasePath } from "@/contexts/BasePathContext";
import TopNav from "@/components/site/TopNav";

const API = process.env.REACT_APP_BACKEND_URL;

const CATEGORY_NAMES = {
  "cs.RO": "Robotics", "cs.DC": "Distributed Computing", "econ.GN": "Economics",
  "physics.comp-ph": "Computational Physics", "q-bio.BM": "Biomolecules",
  "cs.GT": "Game Theory", "physics.chem-ph": "Chemical Physics",
  "chemrxiv.IC": "Inorganic Chemistry", "cs.CR": "Cryptography & Security",
  "cs.IT": "Information Theory", "quant-ph": "Quantum Physics",
  "astro-ph.CO": "Cosmology & Astrophysics", "cond-mat.mtrl-sci": "Materials Science",
  "cs.AI": "Artificial Intelligence", "cs.SI": "Social & Information Networks",
  "q-fin.CP": "Quantitative Finance", "iacr.sk": "Secret-key Cryptography",
  "cs.LG": "Machine Learning", "stat.ML": "Machine Learning (Statistics)",
  "iacr.impl": "Implementation Cryptography", "iacr.app": "Applications Cryptography",
  "cs.IR": "Information Retrieval",
};

export default function NewArchivePage() {
  const { category, year, weekOrMonth } = useParams();
  const basePath = useBasePath();
  const navigate = useNavigate();
  const [archive, setArchive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState("rank");
  const [sortDir, setSortDir] = useState("asc");
  const [keyword, setKeyword] = useState("");

  const isWeekly = weekOrMonth?.startsWith("w");
  const num = parseInt(weekOrMonth?.replace(/^[wm]/, ""), 10);
  const catName = CATEGORY_NAMES[category] || category;

  useEffect(() => {
    const url = isWeekly
      ? `${API}/api/archive/${category}/${year}/w${num}`
      : `${API}/api/archive/${category}/${year}/m${num}`;
    setLoading(true);
    axios.get(url).then(res => {
      if (res.data.status === "not_found") setArchive(null);
      else setArchive(res.data);
    }).catch(() => setArchive(null))
      .finally(() => setLoading(false));
  }, [category, year, num, isWeekly]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir(key === "title" || key === "published" ? "asc" : "desc"); }
  };

  const sortedEntries = useMemo(() => {
    if (!archive?.leaderboard) return [];
    let data = [...archive.leaderboard];
    if (keyword.trim()) {
      const kw = keyword.toLowerCase();
      data = data.filter(e => (e.title || "").toLowerCase().includes(kw) || (e.authors || []).some(a => a.toLowerCase().includes(kw)));
    }
    if (!sortKey || sortKey === "rank") return sortDir === "desc" ? [...data].reverse() : data;
    const key = sortKey === "score" ? "score" : sortKey === "wilson_margin" ? "ts_sigma" : sortKey === "gap_score" ? "gap_score" : sortKey;
    data.sort((a, b) => {
      let va = a[key], vb = b[key];
      if (typeof va === "string" && typeof vb === "string") return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      va = va ?? (sortDir === "asc" ? Infinity : -Infinity);
      vb = vb ?? (sortDir === "asc" ? Infinity : -Infinity);
      return sortDir === "asc" ? va - vb : vb - va;
    });
    return data;
  }, [archive, sortKey, sortDir, keyword]);

  if (loading) return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-10">
        <div className="space-y-3">{[...Array(6)].map((_, i) => <div key={i} className="h-12 bg-slate-50 rounded-sm animate-pulse" />)}</div>
      </div>
    </div>
  );

  if (!archive) return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-16 text-center">
        <Archive className="h-10 w-10 mx-auto mb-3 text-slate-300" />
        <h1 className="font-heading text-lg font-semibold mb-2">Archive Not Found</h1>
        <p className="text-sm text-slate-500 mb-4">No snapshot for {catName} {isWeekly ? `Week ${num}` : `Month ${num}`}, {year}.</p>
        <a href="#" onClick={(e) => { e.preventDefault(); navigate(`${basePath}/leaderboard?cat=${category}&period=all`); }} className="text-blue-600 hover:underline text-sm">Back to leaderboard</a>
      </div>
    </div>
  );

  const entries = archive.leaderboard || [];

  return (
    <div className="kurate-homepage">
      <TopNav />
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-6 md:py-10">
        <div className="mb-6">
          <a href="#" onClick={(e) => { e.preventDefault(); navigate(`${basePath}/leaderboard?cat=${category}&period=all`); }}
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 mb-4 transition-colors cursor-pointer">
            <ArrowLeft className="h-4 w-4" /> Back to live leaderboard
          </a>
          <h1 className="font-heading text-xl md:text-2xl font-semibold tracking-tight mb-1">
            {catName} Papers — {archive.label}
          </h1>
          <p className="text-sm text-slate-500">
            Leaderboard snapshot. {entries.length} preprints from arXiv ({category}), {archive.match_count?.toLocaleString()} matches.
          </p>
        </div>

        <div className="mb-4">
          <div className="relative max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
            <Input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="Search papers..."
              className="pl-8 h-9 text-sm rounded-sm border-slate-200" />
          </div>
        </div>

        <div className="border border-slate-200 rounded-sm overflow-hidden">
          <LeaderboardTableNew
            leaderboard={sortedEntries} loading={false}
            sortKey={sortKey} sortDir={sortDir} onSort={handleSort}
            showRatingCol={entries.some(e => e.ai_rating)}
            showGapCol={entries.some(e => e.gap_score != null)}
            hasSelectedTags={false} globalStats={false}
            isArchive={true} nextCursor={null}
            loadMore={null} loadingMore={false} keyword={keyword}
          />
        </div>

        <div className="mt-6 text-center">
          <a href="#" onClick={(e) => { e.preventDefault(); navigate(`${basePath}/leaderboard?cat=${category}&period=all`); }}
            className="text-sm text-blue-600 hover:underline">
            View All Time leaderboard for {catName}
          </a>
        </div>
      </div>
    </div>
  );
}
