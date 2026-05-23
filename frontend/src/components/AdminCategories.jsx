import { useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Plus, X, Search, Loader2, GripVertical, Save, Star, Check, ChevronDown,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export function AdminCategories({ onCategoriesChanged }) {
  const [allCategories, setAllCategories] = useState([]);
  const [activeIds, setActiveIds] = useState([]);
  const [featuredIds, setFeaturedIds] = useState([]);
  const [newCats, setNewCats] = useState(new Set());
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dragIdx, setDragIdx] = useState(null);
  const [dragOverIdx, setDragOverIdx] = useState(null);
  const dropdownRef = useRef(null);

  const fetchCategories = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/arxiv-categories`, { headers: getAdminHeaders() });
      setAllCategories(res.data.categories || []);
      setActiveIds(res.data.active || []);
      setFeaturedIds(res.data.featured || []);
      setNewCats(new Set(res.data.new_categories || []));
    } catch {
      toast.error("Failed to load categories");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchCategories(); }, []);

  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const activeSet = useMemo(() => new Set(activeIds), [activeIds]);
  const featuredSet = useMemo(() => new Set(featuredIds), [featuredIds]);

  const featuredCats = useMemo(
    () => featuredIds.map(id => allCategories.find(c => c.id === id)).filter(Boolean),
    [allCategories, featuredIds]
  );

  // Dropdown: all arXiv categories, filterable
  const filtered = useMemo(() => {
    if (!search.trim()) return allCategories;
    const q = search.toLowerCase();
    return allCategories.filter(c =>
      c.id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q)
    );
  }, [allCategories, search]);

  const grouped = useMemo(() => {
    const groups = {};
    for (const c of filtered) {
      if (!groups[c.group]) groups[c.group] = [];
      groups[c.group].push(c);
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);

  // --- Actions ---

  const toggleActive = async (catId) => {
    try {
      if (activeSet.has(catId)) {
        await axios.post(`${API}/api/admin/categories/remove`, { category_id: catId }, { headers: getAdminHeaders() });
        toast.success(`Deactivated ${catId}`);
      } else {
        await axios.post(`${API}/api/admin/categories/add`, { category_id: catId }, { headers: getAdminHeaders() });
        toast.success(`Activated ${catId}`);
      }
      await fetchCategories();
      if (onCategoriesChanged) onCategoriesChanged();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const toggleFeatured = async (catId) => {
    try {
      const res = await axios.post(`${API}/api/admin/categories/toggle-featured`, { category_id: catId }, { headers: getAdminHeaders() });
      setFeaturedIds(res.data.featured);
      if (onCategoriesChanged) onCategoriesChanged();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    }
  };

  const toggleNew = async (catId) => {
    try {
      const res = await axios.post(`${API}/api/admin/categories/toggle-new`, { category_id: catId }, { headers: { ...getAdminHeaders(), "Content-Type": "application/json" } });
      setNewCats(new Set(res.data.new_categories || []));
    } catch { toast.error("Failed to toggle"); }
  };

  // Drag-and-drop for featured order
  const handleDragEnd = async () => {
    if (dragIdx !== null && dragOverIdx !== null && dragIdx !== dragOverIdx) {
      const newOrder = [...featuredIds];
      const [moved] = newOrder.splice(dragIdx, 1);
      newOrder.splice(dragOverIdx, 0, moved);
      setFeaturedIds(newOrder);
      try {
        await axios.post(`${API}/api/admin/categories/reorder-featured`, { featured: newOrder }, { headers: getAdminHeaders() });
        if (onCategoriesChanged) onCategoriesChanged();
      } catch {
        toast.error("Failed to save order");
        await fetchCategories();
      }
    }
    setDragIdx(null);
    setDragOverIdx(null);
  };

  if (loading) return <div className="h-20 bg-secondary/30 rounded-lg animate-pulse" />;

  return (
    <div className="space-y-6" data-testid="admin-categories">
      {/* Active categories dropdown */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium">Active Categories</h3>
          <span className="text-[10px] text-muted-foreground">{activeIds.length} active</span>
        </div>
        <div className="relative" ref={dropdownRef}>
          <div
            className="flex items-center gap-2 p-2.5 border border-dashed border-border rounded-lg cursor-pointer hover:border-accent/50 hover:bg-accent/5 transition-colors"
            onClick={() => setOpen(!open)}
            data-testid="category-dropdown-trigger"
          >
            <Search className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">
              Add or remove categories...
            </span>
            <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
          </div>

          {open && (
            <div className="absolute z-50 mt-1 w-full bg-background border border-border rounded-lg shadow-lg max-h-96 flex flex-col" data-testid="category-dropdown">
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
                  <div className="p-4 text-center text-xs text-muted-foreground">No matching categories</div>
                ) : (
                  grouped.map(([group, cats]) => (
                    <div key={group}>
                      <div className="px-2 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wide sticky top-0 bg-background z-10">
                        {group}
                      </div>
                      {cats.map(c => {
                        const isActive = activeSet.has(c.id);
                        const isFeatured = featuredSet.has(c.id);
                        return (
                          <div
                            key={c.id}
                            className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-accent/10 transition-colors"
                            data-testid={`dropdown-cat-${c.id}`}
                          >
                            <button
                              className={`h-5 w-5 rounded border flex items-center justify-center shrink-0 transition-colors ${
                                isActive ? "bg-accent border-accent text-background" : "border-border hover:border-accent/50"
                              }`}
                              onClick={() => toggleActive(c.id)}
                              title={isActive ? "Deactivate" : "Activate"}
                              data-testid={`toggle-active-${c.id}`}
                            >
                              {isActive && <Check className="h-3 w-3" />}
                            </button>
                            <span className="font-mono text-[11px] text-accent shrink-0 w-28">{c.id}</span>
                            <span className={`text-sm truncate flex-1 ${!isActive ? "text-muted-foreground" : ""}`}>{c.name}</span>
                            {isActive && (
                              <button
                                className={`h-5 w-5 flex items-center justify-center shrink-0 rounded transition-colors ${
                                  isFeatured ? "text-amber-500" : "text-muted-foreground/30 hover:text-amber-400"
                                }`}
                                onClick={() => toggleFeatured(c.id)}
                                title={isFeatured ? "Unfeature" : "Feature on homepage"}
                                data-testid={`toggle-featured-${c.id}`}
                              >
                                <Star className={`h-3.5 w-3.5 ${isFeatured ? "fill-amber-500" : ""}`} />
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Featured categories (homepage tabs) */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium">Featured Categories</h3>
          <span className="text-[10px] text-muted-foreground">{featuredCats.length} homepage tabs</span>
        </div>
        <div className="space-y-1.5">
          {featuredCats.map((c, idx) => (
            <div
              key={c.id}
              draggable
              onDragStart={() => setDragIdx(idx)}
              onDragOver={(e) => { e.preventDefault(); setDragOverIdx(idx); }}
              onDragEnd={handleDragEnd}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors ${
                dragOverIdx === idx && dragIdx !== null && dragIdx !== idx
                  ? "border-accent bg-accent/5"
                  : "bg-secondary/30 border-border"
              }`}
              data-testid={`featured-cat-${c.id}`}
            >
              <GripVertical className="h-3.5 w-3.5 text-muted-foreground/50 cursor-grab shrink-0" />
              <span className="font-mono text-xs text-accent">{c.id}</span>
              <span className="text-sm font-medium truncate">{c.name}</span>
              <div className="ml-auto flex items-center gap-1 shrink-0">
                <button
                  className={`h-6 px-1.5 text-[10px] font-medium rounded transition-colors ${
                    newCats.has(c.id)
                      ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                      : "bg-secondary/50 text-muted-foreground/50 hover:text-muted-foreground hover:bg-secondary"
                  }`}
                  onClick={() => toggleNew(c.id)}
                  title={newCats.has(c.id) ? "Remove 'New' badge" : "Show as 'New' on homepage"}
                >
                  New
                </button>
                <Button
                  variant="ghost" size="sm"
                  className="h-6 w-6 p-0 text-amber-500 hover:text-muted-foreground hover:bg-secondary"
                  onClick={() => toggleFeatured(c.id)}
                  title="Remove from featured"
                  data-testid={`unfeature-${c.id}`}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </div>
          ))}
          {featuredCats.length === 0 && (
            <div className="text-xs text-muted-foreground py-3 text-center border border-dashed rounded-lg">
              No featured categories. Use the dropdown below to feature some.
            </div>
          )}
        </div>
      </div>

      {/* Category dropdown - add/remove/feature */}
      <div className="relative" ref={dropdownRef}>
        <div
          className="flex items-center gap-2 p-2.5 border border-dashed border-border rounded-lg cursor-pointer hover:border-accent/50 hover:bg-accent/5 transition-colors"
          onClick={() => setOpen(!open)}
          data-testid="category-dropdown-trigger"
        >
          <Search className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            Manage categories... <span className="text-[10px]">({activeIds.length} active)</span>
          </span>
          <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
        </div>

        {open && (
          <div className="absolute z-50 mt-1 w-full bg-background border border-border rounded-lg shadow-lg max-h-96 flex flex-col" data-testid="category-dropdown">
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
                <div className="p-4 text-center text-xs text-muted-foreground">No matching categories</div>
              ) : (
                grouped.map(([group, cats]) => (
                  <div key={group}>
                    <div className="px-2 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wide sticky top-0 bg-background z-10">
                      {group}
                    </div>
                    {cats.map(c => {
                      const isActive = activeSet.has(c.id);
                      const isFeatured = featuredSet.has(c.id);
                      return (
                        <div
                          key={c.id}
                          className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-accent/10 transition-colors"
                          data-testid={`dropdown-cat-${c.id}`}
                        >
                          {/* Active toggle */}
                          <button
                            className={`h-5 w-5 rounded border flex items-center justify-center shrink-0 transition-colors ${
                              isActive ? "bg-accent border-accent text-background" : "border-border hover:border-accent/50"
                            }`}
                            onClick={() => toggleActive(c.id)}
                            title={isActive ? "Deactivate" : "Activate"}
                            data-testid={`toggle-active-${c.id}`}
                          >
                            {isActive && <Check className="h-3 w-3" />}
                          </button>
                          {/* Info */}
                          <span className="font-mono text-[11px] text-accent shrink-0 w-28">{c.id}</span>
                          <span className={`text-sm truncate flex-1 ${!isActive ? "text-muted-foreground" : ""}`}>{c.name}</span>
                          {/* Feature toggle */}
                          {isActive && (
                            <button
                              className={`h-5 w-5 flex items-center justify-center shrink-0 rounded transition-colors ${
                                isFeatured ? "text-amber-500" : "text-muted-foreground/30 hover:text-amber-400"
                              }`}
                              onClick={() => toggleFeatured(c.id)}
                              title={isFeatured ? "Unfeature" : "Feature on homepage"}
                              data-testid={`toggle-featured-${c.id}`}
                            >
                              <Star className={`h-3.5 w-3.5 ${isFeatured ? "fill-amber-500" : ""}`} />
                            </button>
                          )}
                        </div>
                      );
                    })}
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
