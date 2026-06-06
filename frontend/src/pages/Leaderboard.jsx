import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Search } from "lucide-react";
import TopNav from "@/components/site/TopNav";
import SiteFooter from "@/components/site/SiteFooter";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, accentFor, PERIODS, RANK_TYPES } from "@/lib/api";

export default function Leaderboard() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [categories, setCategories] = useState([]);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState(searchParams.get("q") || "");
  const [category, setCategory] = useState(searchParams.get("category") || "all");
  const [period, setPeriod] = useState(searchParams.get("period") || "all");
  const [rankType, setRankType] = useState(searchParams.get("rank_type") || "score");

  useEffect(() => {
    api.categories().then(setCategories);
  }, []);

  useEffect(() => {
    setLoading(true);
    api.papers({ category, period, rank_type: rankType, q, limit: 50 })
      .then((res) => setPapers(res.results))
      .finally(() => setLoading(false));
    setSearchParams({ category, period, rank_type: rankType, q });
  }, [category, period, rankType, q, setSearchParams]);

  return (
    <div className="min-h-screen bg-white">
      <TopNav />
      <section className="bg-white border-b border-slate-200">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-10 pb-8">
          <Link to="/" data-testid="back-home" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 mb-5">
            <ArrowLeft className="h-3.5 w-3.5" /> Home
          </Link>
          <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Full Leaderboard</div>
          <h1 className="font-serif text-4xl sm:text-5xl font-medium text-slate-900 tracking-tight">Paper Rankings</h1>
          <p className="mt-3 text-base text-slate-600 max-w-2xl leading-relaxed">All ranked preprints across categories, filtered by your selection. Updated continuously from the live Kurate data layer.</p>

          <div className="mt-7 border border-slate-200 bg-white p-5 rounded-sm">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search papers, authors, topics…" data-testid="lb-search" className="pl-9 h-10 rounded-sm border-slate-200" />
            </div>
            <div className="mt-4 grid grid-cols-2 lg:grid-cols-3 gap-3">
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger data-testid="lb-category" className="h-10 rounded-sm border-slate-200"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Categories</SelectItem>
                  {categories.map((c) => <SelectItem key={c.code} value={c.code}>{c.code} · {c.name}</SelectItem>)}
                </SelectContent>
              </Select>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger data-testid="lb-period" className="h-10 rounded-sm border-slate-200"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PERIODS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <Select value={rankType} onValueChange={setRankType}>
                <SelectTrigger data-testid="lb-rank" className="h-10 rounded-sm border-slate-200"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {RANK_TYPES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </section>

      <section className="bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10">
          <div className="border border-slate-200 bg-white rounded-sm overflow-hidden">
            <table className="w-full" data-testid="lb-table">
              <thead>
                <tr className="text-[10px] font-medium uppercase tracking-wider text-slate-500 bg-slate-50 border-b border-slate-200">
                  <th className="pl-6 pr-2 py-3 text-left w-12">#</th>
                  <th className="px-2 py-3 text-left">Paper</th>
                  <th className="px-2 py-3 text-left hidden md:table-cell">Authors</th>
                  <th className="px-2 py-3 text-left hidden lg:table-cell">Signal</th>
                  <th className="px-2 py-3 text-right">Score</th>
                  <th className="pl-2 pr-6 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {loading && papers.length === 0 && (
                  <tr><td colSpan={6} className="px-6 py-16 text-center text-sm text-slate-500">Loading rankings…</td></tr>
                )}
                {!loading && papers.length === 0 && (
                  <tr><td colSpan={6} className="px-6 py-16 text-center text-sm text-slate-500">No papers match these filters.</td></tr>
                )}
                {papers.map((p) => {
                  const a = accentFor(p.field);
                  return (
                    <tr key={p.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 transition-colors" data-testid={`lb-row-${p.id}`}>
                      <td className="pl-6 pr-2 py-4 align-top"><span className="font-serif text-lg text-slate-900">{p.rank}</span></td>
                      <td className="px-2 py-4 align-top">
                        <div className="text-sm font-medium text-slate-900 leading-snug">{p.title}</div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[10px] font-medium ${a.bg} ${a.text} ${a.border}`}>{p.category_code}</span>
                          <span>{p.arxiv_id}</span>
                          <span className="text-slate-300">·</span>
                          <span>{p.year}</span>
                        </div>
                      </td>
                      <td className="px-2 py-4 align-top hidden md:table-cell text-xs text-slate-600">{p.authors.slice(0, 3).join(", ")}{p.authors.length > 3 ? ` +${p.authors.length - 3}` : ""}</td>
                      <td className="px-2 py-4 align-top hidden lg:table-cell text-xs text-slate-600">{p.signal_badge}</td>
                      <td className="px-2 py-4 align-top text-right font-serif text-base text-slate-900">{p.score}</td>
                      <td className="pl-2 pr-6 py-4 align-top text-right">
                        <a href="#" data-testid={`lb-view-${p.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 whitespace-nowrap">View <ArrowRight className="h-3 w-3" /></a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-4 text-xs text-slate-500 text-right">{papers.length} results</div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
