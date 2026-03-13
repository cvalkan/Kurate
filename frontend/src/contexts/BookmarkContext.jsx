import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL || "";
const BookmarkContext = createContext(null);

export function BookmarkProvider({ children }) {
  const { user, getAuthHeaders } = useAuth();
  const [bookmarkedIds, setBookmarkedIds] = useState(new Set());

  useEffect(() => {
    if (!user) { setBookmarkedIds(new Set()); return; }
    axios.get(`${API}/api/bookmarks/ids`, { withCredentials: true, headers: getAuthHeaders() })
      .then(res => setBookmarkedIds(new Set(res.data.paper_ids || [])))
      .catch(() => {});
  }, [user, getAuthHeaders]);

  const toggleBookmark = useCallback(async (paperId) => {
    if (!user) { toast.error("Sign in to bookmark papers"); return; }
    const headers = { ...getAuthHeaders(), "Content-Type": "application/json" };
    const isBookmarked = bookmarkedIds.has(paperId);
    // Optimistic update
    setBookmarkedIds(prev => {
      const next = new Set(prev);
      if (isBookmarked) next.delete(paperId); else next.add(paperId);
      return next;
    });
    try {
      if (isBookmarked) {
        await axios.delete(`${API}/api/bookmarks/${paperId}`, { withCredentials: true, headers });
      } else {
        await axios.post(`${API}/api/bookmarks`, { paper_id: paperId }, { withCredentials: true, headers });
        toast.success("Bookmarked");
      }
    } catch {
      // Revert on error
      setBookmarkedIds(prev => {
        const next = new Set(prev);
        if (isBookmarked) next.add(paperId); else next.delete(paperId);
        return next;
      });
      toast.error("Failed to update bookmark");
    }
  }, [user, getAuthHeaders, bookmarkedIds]);

  return (
    <BookmarkContext.Provider value={{ bookmarkedIds, toggleBookmark }}>
      {children}
    </BookmarkContext.Provider>
  );
}

export function useBookmarks() {
  const ctx = useContext(BookmarkContext);
  if (!ctx) throw new Error("useBookmarks must be used within BookmarkProvider");
  return ctx;
}
