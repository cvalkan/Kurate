import { useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Plus, X, Search, Loader2, DollarSign, FileText, Swords, ChevronDown, Save, Undo2, GripVertical,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  return { "X-Admin-Token": sessionStorage.getItem("admin_token") || "" };
}

export function AdminCategories({ onCategoriesChanged }) {
  const [allCategories, setAllCategories] = useState([]);
  const [activeIds, setActiveIds] = useState([]);  // Server state
  const [pendingAdds, setPendingAdds] = useState(new Set());
  const [pendingRemoves, setPendingRemoves] = useState(new Set());
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [estimating, setEstimating] = useState(null);
  const [estimates, setEstimates] = useState({});
  const [archiveFreq, setArchiveFreq] = useState({});
  const dropdownRef = useRef(null);
  const [dragIdx, setDragIdx] = useState(null);
  const [dragOverIdx, setDragOverIdx] = useState(null);
  const [reordering, setReordering] = useState(false);

  const hasChanges = pendingAdds.size > 0 || pendingRemoves.size > 0;

  const fetchCategories = async () => {
    try {
      const res = await axios.get(`${API}/api/admin/arxiv-categories`, { headers: getAdminHeaders() });
      setAllCategories(res.data.categories || []);
      setActiveIds(res.data.active || []);
      // Load archive frequency
      const freqRes = await axios.get(`${API}/api/admin/archive/frequency`, { headers: getAdminHeaders() }).catch(() => ({ data: {} }));
      setArchiveFreq(freqRes.data || {});
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

  // Effective active list = server active + pending adds - pending removes (preserves order)
  const effectiveActive = useMemo(() => {
    const result = activeIds.filter(id => !pendingRemoves.has(id));
    for (const id of pendingAdds) {
      if (!result.includes(id)) result.push(id);
    }
    return result;
  }, [activeIds, pendingAdds, pendingRemoves]);

  const activeCats = useMemo(
    () => effectiveActive.map(id => allCategories.find(c => c.id === id)).filter(Boolean),
    [allCategories, effectiveActive]
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return allCategories.filter(c => !effectiveActive.includes(c.id));
    const q = search.toLowerCase();
    return allCategories.filter(c =>
      !effectiveActive.includes(c.id) &&
      (c.id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q))
    );
  }, [allCategories, effectiveActive, search]);

  const grouped = useMemo(() => {
    const groups = {};
    for (const c of filtered) {
      if (!groups[c.group]) groups[c.group] = [];
      groups[c.group].push(c);
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);

  const stageAdd = (catId) => {
    if (pendingRemoves.has(catId)) {
      // Undo a pending remove
      setPendingRemoves(prev => { const n = new Set(prev); n.delete(catId); return n; });
    } else {
      setPendingAdds(prev => new Set(prev).add(catId));
    }
    setSearch("");
    setOpen(false);
  };

  const stageRemove = (catId) => {
    if (pendingAdds.has(catId)) {
      // Undo a pending add
      setPendingAdds(prev => { const n = new Set(prev); n.delete(catId); return n; });
    } else if (effectiveActive.length > 1) {
      setPendingRemoves(prev => new Set(prev).add(catId));
    }
  };

  const discardChanges = () => {
    setPendingAdds(new Set());
    setPendingRemoves(new Set());
  };

  // Drag-and-drop reorder
  const handleDragStart = (idx) => setDragIdx(idx);
  const handleDragOver = (e, idx) => { e.preventDefault(); setDragOverIdx(idx); };
  const handleDragEnd = async () => {
    if (dragIdx !== null && dragOverIdx !== null && dragIdx !== dragOverIdx) {
      const newOrder = [...activeIds];
      const [moved] = newOrder.splice(dragIdx, 1);
      newOrder.splice(dragOverIdx, 0, moved);
      setActiveIds(newOrder);
      // Persist to backend
      setReordering(true);
      try {
        await axios.post(`${API}/api/admin/categories/reorder`, { category_ids: newOrder }, { headers: getAdminHeaders() });
        if (onCategoriesChanged) onCategoriesChanged();
      } catch (err) {
        toast.error("Failed to save order");
        await fetchCategories(); // Revert on failure
      } finally {
        setReordering(false);
      }
    }
    setDragIdx(null);
    setDragOverIdx(null);
  };

  const saveChanges = async () => {
    setSaving(true);
    try {
      // Process removals first, then additions
      for (const catId of pendingRemoves) {
        await axios.post(`${API}/api/admin/categories/remove`, { category_id: catId }, { headers: getAdminHeaders() });
      }
      for (const catId of pendingAdds) {
        await axios.post(`${API}/api/admin/categories/add`, { category_id: catId }, { headers: getAdminHeaders() });
      }
      const totalChanges = pendingAdds.size + pendingRemoves.size;
      toast.success(`Saved ${totalChanges} category change${totalChanges > 1 ? "s" : ""}`);
      setPendingAdds(new Set());
      setPendingRemoves(new Set());
      await fetchCategories();
      if (onCategoriesChanged) onCategoriesChanged();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save changes");
    } finally {
      setSaving(false);
    }
  };

  const handleEstimate = async (catId) => {
    if (estimates[catId]) return;
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
        <span className="text-xs text-muted-foreground">
          {effectiveActive.length} active
          {hasChanges && <span className="text-amber-500 ml-1">(unsaved changes)</span>}
        </span>
      </div>

      {/* Active categories */}
      <div className="space-y-2">
        {activeCats.map((c, idx) => {
          const est = estimates[c.id];
          const isPendingAdd = pendingAdds.has(c.id);
          const isPendingRemove = pendingRemoves.has(c.id);
          return (
            <div
              key={c.id}
              draggable={!hasChanges}
              onDragStart={() => handleDragStart(idx)}
              onDragOver={(e) => handleDragOver(e, idx)}
              onDragEnd={handleDragEnd}
              className={`flex items-center gap-2 p-3 rounded-lg border group transition-colors ${
                isPendingAdd ? "bg-green-50 border-green-200" :
                isPendingRemove ? "bg-red-50 border-red-200 opacity-60" :
                dragOverIdx === idx && dragIdx !== null && dragIdx !== idx ? "border-accent bg-accent/5" :
                "bg-secondary/30 border-border"
              }`}
              data-testid={`active-cat-${c.id}`}
            >
              {/* Drag handle */}
              {!hasChanges && (
                <GripVertical className="h-4 w-4 text-muted-foreground/60 cursor-grab shrink-0 hover:text-foreground" data-testid={`drag-handle-${c.id}`} />
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-accent">{c.id}</span>
                  <span className={`text-sm font-medium truncate ${isPendingRemove ? "line-through" : ""}`}>{c.name}</span>
                  <span className="text-[10px] text-muted-foreground">{c.group}</span>
                  {isPendingAdd && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium">new</span>}
                  {isPendingRemove && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">removing</span>}
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
                {!isPendingRemove && (
                  <select
                    value={archiveFreq[c.id] || archiveFreq.default || "weekly"}
                    onChange={async (e) => {
                      const freq = e.target.value;
                      try {
                        await axios.post(`${API}/api/admin/archive/set-frequency`,
                          { category: c.id, frequency: freq },
                          { headers: { ...getAdminHeaders(), "Content-Type": "application/json" } }
                        );
                        setArchiveFreq(prev => ({ ...prev, [c.id]: freq }));
                      } catch { toast.error("Failed to save"); }
                    }}
                    className="h-7 text-[10px] px-1.5 rounded border border-border bg-background text-muted-foreground cursor-pointer"
                    data-testid={`freq-${c.id}`}
                  >
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                )}
                {!est && !isPendingRemove && (
                  <Button variant="ghost" size="sm" className="h-7 text-[10px] text-muted-foreground"
                    onClick={() => handleEstimate(c.id)} disabled={estimating === c.id}
                    data-testid={`estimate-${c.id}`}
                  >
                    {estimating === c.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <DollarSign className="h-3 w-3" />}
                    {estimating === c.id ? "" : "Estimate"}
                  </Button>
                )}
                {isPendingRemove || isPendingAdd ? (
                  <Button variant="ghost" size="sm"
                    className="h-7 text-[10px] text-muted-foreground hover:text-foreground"
                    onClick={() => isPendingAdd ? stageRemove(c.id) : stageAdd(c.id)}
                  >
                    <Undo2 className="h-3 w-3 mr-1" /> Undo
                  </Button>
                ) : (
                  <Button variant="ghost" size="sm"
                    className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => stageRemove(c.id)} disabled={effectiveActive.length <= 1}
                    data-testid={`remove-${c.id}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Save / Discard bar */}
      {hasChanges && (
        <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg" data-testid="save-categories-bar">
          <span className="text-xs text-amber-700 flex-1">
            {pendingAdds.size > 0 && `${pendingAdds.size} to add`}
            {pendingAdds.size > 0 && pendingRemoves.size > 0 && ", "}
            {pendingRemoves.size > 0 && `${pendingRemoves.size} to remove`}
            {" — review cost estimates before saving"}
          </span>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={discardChanges}>
            Discard
          </Button>
          <Button size="sm" className="h-7 text-xs gap-1" onClick={saveChanges} disabled={saving}>
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            Save Changes
          </Button>
        </div>
      )}

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
                        className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm rounded hover:bg-accent/10 transition-colors"
                        onClick={() => stageAdd(c.id)}
                        data-testid={`add-cat-${c.id}`}
                      >
                        <span className="font-mono text-[11px] text-accent shrink-0 w-28">{c.id}</span>
                        <span className="truncate">{c.name}</span>
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
