import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Archive, Calendar, ChevronRight } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export function ArchiveList({ category }) {
  const [archives, setArchives] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = category ? { category } : {};
    axios.get(`${API}/api/archive/list`, { params })
      .then(res => setArchives(res.data.archives || []))
      .catch(() => setArchives([]))
      .finally(() => setLoading(false));
  }, [category]);

  if (loading) return <div className="h-32 bg-secondary/20 rounded-lg animate-pulse" />;

  if (!archives.length) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Archive className="h-8 w-8 mx-auto mb-2 opacity-30" />
        <p className="text-sm">No archived snapshots yet.</p>
        <p className="text-xs mt-1">Weekly snapshots are created automatically every Monday at 00:00 UTC.</p>
      </div>
    );
  }

  // Group by year
  const byYear = {};
  for (const a of archives) {
    if (!byYear[a.year]) byYear[a.year] = [];
    byYear[a.year].push(a);
  }

  return (
    <div className="space-y-4" data-testid="archive-list">
      {Object.entries(byYear).sort((a, b) => b[0] - a[0]).map(([year, items]) => (
        <div key={year}>
          <h3 className="text-sm font-semibold text-muted-foreground mb-2">{year}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
            {items.map(a => {
              const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
              const href = `/leaderboard/${a.category}/${a.year}/${slug}`;
              return (
                <Link key={`${a.category}-${a.year}-${slug}`} to={href}
                  className="p-2.5 border border-border rounded-lg hover:border-accent/40 hover:bg-accent/5 transition-colors group"
                  data-testid={`archive-${a.category}-${slug}`}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <Calendar className="h-3 w-3 text-muted-foreground group-hover:text-accent" />
                    <span className="text-xs font-medium">{a.label}</span>
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {a.paper_count} papers
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
