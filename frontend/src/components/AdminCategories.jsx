import { useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Plus, X, Search, Loader2, DollarSign, FileText, Swords, ChevronDown,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export function AdminCategories({ onCategoriesChanged }) {
  const [allCategories, setAllCategories] = useState([]);
  const [activeIds, setActiveIds] = useState([]);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [estimating, setEstimating] = useState(null);
  const [estimates, setEstimates] = useState({});
  const [removing, setRemoving] = useState(null);
  const [adding, setAdding] = useState(null);
  const dropdownRef = useRef(null);

  const fetchCategories = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/arxiv-categories`, { headers: getAdminHeaders() });
      setAllCategories(res.data.categories || []);
      setActiveIds(res.data.active || []);
    } catch {
      toast.error("Failed to load categories");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchCategories(); }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const activeCats = useMemo(
    () => allCategories.filter(c => activeIds.includes(c.id)),
    [allCategories, activeIds]
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return allCategories.filter(c => !activeIds.includes(c.id));
    const q = search.toLowerCase();
    return allCategories.filter(c =>
      !activeIds.includes(c.id) &&
      (c.id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q))
    );
  }, [allCategories, activeIds, search]);

  // Group the filtered results
  const grouped = useMemo(() => {
    const groups = {};
    for (const c of filtered) {
      if (!groups[c.group]) groups[c.group] = [];
      groups[c.group].push(c);
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);

  const handleAdd = async (catId) => {
    setAdding(catId);
    try {
      await axios.post(`${API}/api/admin/categories/add`, { category_id: catId }, { headers: getAdminHeaders() });
      toast.success(`Added ${catId}`);
      setSearch("");
      setOpen(false);
      await fetchCategories();
      if (onCategoriesChanged) onCategoriesChanged();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to add category");
    } finally {
      setAdding(null);
    }
  };

  const handleRemove = async (catId) => {
    setRemoving(catId);
    try {
      await axios.post(`${API}/api/admin/categories/remove`, { category_id: catId }, { headers: getAdminHeaders() });
      toast.success(`Removed ${catId}`);
      await fetchCategories();
      if (onCategoriesChanged) onCategoriesChanged();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to remove category");
    } finally {
      setRemoving(null);
    }
  };

  const handleEstimate = async (catId) => {
    if (estimates[catId]) return; // already fetched
    setEstimating(catId);
    try {
      const res = await axios.get(`${API}/api/admin/category-estimate/${catId}`, { headers: getAdminHeaders() });
      setEstimates(prev => ({ ...prev, [catId]: res.data }));
    } catch {
      toast.error("Failed to estimate");
    } finally {
      setEstimating(null);
    }
  };

  if (loading) return <div className="h-20 bg-secondary/30 rounded-lg animate-pulse" />;

  return (
    <div className="space-y-4" data-testid="admin-categories">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Tournament Categories</h3>
        <span className="text-xs text-muted-foreground">{activeIds.length} active</span>
      </div>

      {/* Active categories */}
      <div className="space-y-2">
        {activeCats.map(c => {
          const est = estimates[c.id];
          return (
            <div key={c.id} className="flex items-center gap-3 p-3 bg-secondary/30 rounded-lg border border-border group" data-testid={`active-cat-${c.id}`}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-accent">{c.id}</span>
                  <span className="text-sm font-medium truncate">{c.name}</span>
                  <span className="text-[10px] text-muted-foreground">{c.group}</span>
                </div>
                {est && (
                  <div className="flex items-center gap-4 mt-1.5 text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1"><FileText className="h-3 w-3" /> ~{est.estimated_weekly_papers}/wk</span>
                    <span className="flex items-center gap-1"><Swords className="h-3 w-3" /> ~{est.estimated_weekly_matches} matches</span>
                    <span className="flex items-center gap-1"><DollarSign className="h-3 w-3" /> ~${est.estimated_weekly_cost}/wk</span>
                    {est.existing_papers > 0 && (
                      <span className="text-foreground">{est.existing_papers} papers, {est.existing_matches} matches in DB</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {!est && (
                  <Button variant="ghost" size="sm" className="h-7 text-[10px] text-muted-foreground"
                    onClick={() => handleEstimate(c.id)} disabled={estimating === c.id}
                    data-testid={`estimate-${c.id}`}
                  >
                    {estimating === c.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <DollarSign className="h-3 w-3" />}
                    {estimating === c.id ? "" : "Estimate"}
                  </Button>
                )}
                <Button variant="ghost" size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => handleRemove(c.id)} disabled={removing === c.id || activeIds.length <= 1}
                  data-testid={`remove-${c.id}`}
                >
                  {removing === c.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add category dropdown */}
      <div className="relative" ref={dropdownRef}>
        <div
          className="flex items-center gap-2 p-2.5 border border-dashed border-border rounded-lg cursor-pointer hover:border-accent/50 hover:bg-accent/5 transition-colors"
          onClick={() => setOpen(!open)}
          data-testid="add-category-trigger"
        >
          <Plus className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Add category...</span>
          <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
        </div>

        {open && (
          <div className="absolute z-50 mt-1 w-full bg-background border border-border rounded-lg shadow-lg max-h-80 flex flex-col" data-testid="category-dropdown">
            <div className="p-2 border-b border-border">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search categories..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-8 h-8 text-sm"
                  autoFocus
                  data-testid="category-search"
                />
              </div>
            </div>
            <div className="overflow-y-auto flex-1 p-1">
              {grouped.length === 0 ? (
                <div className="p-4 text-center text-xs text-muted-foreground">
                  {search ? "No matching categories" : "All categories are active"}
                </div>
              ) : (
                grouped.map(([group, cats]) => (
                  <div key={group}>
                    <div className="px-2 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wide sticky top-0 bg-background">
                      {group}
                    </div>
                    {cats.map(c => (
                      <button
                        key={c.id}
                        className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm rounded hover:bg-accent/10 transition-colors disabled:opacity-50"
                        onClick={() => handleAdd(c.id)}
                        disabled={adding === c.id}
                        data-testid={`add-cat-${c.id}`}
                      >
                        <span className="font-mono text-[11px] text-accent shrink-0 w-28">{c.id}</span>
                        <span className="truncate">{c.name}</span>
                        {adding === c.id && <Loader2 className="h-3 w-3 animate-spin ml-auto" />}
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
