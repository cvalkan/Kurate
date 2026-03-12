import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Archive, Calendar, ChevronDown } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export function ArchiveList({ category }) {
  const [archives, setArchives] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const params = category ? { category } : {};
    axios.get(`${API}/api/archive/list`, { params })
      .then(res => {
        const list = res.data.archives || [];
        setArchives(list);
        if (list.length > 0) setSelected(list[0]);
      })
      .catch(() => setArchives([]))
      .finally(() => setLoading(false));
  }, [category]);

  useEffect(() => {
    const handler = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setDropdownOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (loading) return <div className="h-32 bg-secondary/20 rounded-lg animate-pulse" />;

  if (!archives.length) {
    return (
      <div className="text-center py-16 text-muted-foreground">
        <Archive className="h-8 w-8 mx-auto mb-3 opacity-30" />
        <p className="text-sm font-medium">No archived snapshots yet</p>
        <p className="text-xs mt-1 max-w-md mx-auto">
          Weekly snapshots are created automatically every Monday at 00:00 UTC.
          Each snapshot freezes the current leaderboard as a permanent, linkable record.
        </p>
      </div>
    );
  }

  const selectedSlug = selected
    ? (selected.period_type === "weekly" ? `w${selected.week}` : `m${selected.month}`)
    : null;
  const selectedHref = selected
    ? `/leaderboard/${selected.category}/${selected.year}/${selectedSlug}`
    : null;

  return (
    <div className="space-y-4" data-testid="archive-list">
      {/* Dropdown selector */}
      <div className="flex items-center gap-3">
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="flex items-center gap-2 px-3 py-2 border border-border rounded-lg bg-background hover:bg-secondary/30 transition-colors min-w-[200px]"
            data-testid="archive-dropdown"
          >
            <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-sm font-medium flex-1 text-left">
              {selected ? selected.label : "Select week..."}
            </span>
            <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
          </button>
          {dropdownOpen && (
            <div className="absolute z-50 top-full mt-1 left-0 bg-background border border-border rounded-lg shadow-lg min-w-[240px] max-h-[320px] overflow-y-auto py-1">
              {archives.map(a => {
                const slug = a.period_type === "weekly" ? `w${a.week}` : `m${a.month}`;
                const isSelected = selected?.label === a.label && selected?.category === a.category;
                return (
                  <button
                    key={`${a.category}-${a.year}-${slug}`}
                    onClick={() => { setSelected(a); setDropdownOpen(false); }}
                    className={`w-full text-left px-3 py-2 text-sm hover:bg-secondary/30 transition-colors flex items-center justify-between ${
                      isSelected ? "bg-accent/10 text-accent font-medium" : ""
                    }`}
                  >
                    <span>{a.label}</span>
                    <span className="text-[10px] text-muted-foreground">{a.paper_count} papers</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {selected && (
          <Link
            to={selectedHref}
            className="px-4 py-2 bg-accent text-accent-foreground rounded-lg text-sm font-medium hover:bg-accent/90 transition-colors"
            data-testid="archive-view-btn"
          >
            View snapshot
          </Link>
        )}
      </div>

      {/* Preview of selected archive */}
      {selected && (
        <div className="border border-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold">{selected.label}</h3>
              <p className="text-[10px] text-muted-foreground">
                {selected.paper_count} papers, {selected.match_count?.toLocaleString()} matches
              </p>
            </div>
            <Link to={selectedHref} className="text-xs text-accent hover:underline flex items-center gap-1">
              Full leaderboard →
            </Link>
          </div>
          <p className="text-xs text-muted-foreground">
            Frozen snapshot of the {category || "all"} leaderboard. Rankings are permanent and can be referenced by badges and citations.
          </p>
        </div>
      )}
    </div>
  );
}
