import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Trophy, Shield, BarChart3, BookOpen } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function Navbar() {
  const location = useLocation();
  const [categories, setCategories] = useState([]);
  const [activeLabel, setActiveLabel] = useState("");

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      const cats = res.data.categories || [];
      setCategories(cats);
      if (cats.length > 0) setActiveLabel(cats[0].name);
    }).catch(() => {});
  }, []);

  // Listen for category changes from the leaderboard page via custom event
  useEffect(() => {
    const handler = (e) => {
      if (e.detail?.name) setActiveLabel(e.detail.name);
      else if (e.detail?.tags) setActiveLabel(e.detail.tags.join(" + "));
    };
    window.addEventListener("category-change", handler);
    return () => window.removeEventListener("category-change", handler);
  }, []);

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <div className="flex h-14 items-center justify-between">
          <Link
            to="/"
            className="flex items-center gap-2.5 hover:opacity-80 transition-opacity min-w-0"
            data-testid="navbar-logo"
          >
            <Trophy className="h-5 w-5 text-accent shrink-0" />
            <span className="font-heading font-semibold text-lg tracking-tight shrink-0">
              Paper<span className="text-accent">Sumo</span>
            </span>
            {activeLabel && (
              <span className="hidden sm:inline text-xs text-muted-foreground font-mono border border-border rounded px-1.5 py-0.5">
                {activeLabel.toUpperCase()}
              </span>
            )}
          </Link>

          <div className="flex items-center gap-1">
            <Button
              variant={location.pathname === "/" ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-leaderboard"
            >
              <Link to="/" className="flex items-center gap-2">
                <Trophy className="h-4 w-4" />
                <span className="hidden sm:inline">Leaderboard</span>
              </Link>
            </Button>

            <Button
              variant={location.pathname === "/correlation" ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-correlation"
            >
              <Link to="/correlation" className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                <span className="hidden sm:inline">Model Analysis</span>
              </Link>
            </Button>

            <Button
              variant={location.pathname === "/methodology" ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-methodology"
            >
              <Link to="/methodology" className="flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                <span className="hidden sm:inline">Methodology</span>
              </Link>
            </Button>

            <Button
              variant={location.pathname.startsWith("/admin") ? "secondary" : "ghost"}
              size="sm"
              asChild
              data-testid="nav-admin"
            >
              <Link to="/admin" className="flex items-center gap-2">
                <Shield className="h-4 w-4" />
                <span className="hidden sm:inline">Admin</span>
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </nav>
  );
}
