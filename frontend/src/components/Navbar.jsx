import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Trophy, Shield, BarChart3, BookOpen, LogIn, LogOut, User } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { AuthModal } from "@/components/AuthModal";

const API = process.env.REACT_APP_BACKEND_URL;

export default function Navbar() {
  const location = useLocation();
  const { user, loading: authLoading, logout } = useAuth();
  const [activeLabel, setActiveLabel] = useState("");
  const [showAuth, setShowAuth] = useState(false);

  useEffect(() => {
    axios.get(`${API}/api/categories`).then(res => {
      const cats = res.data.categories || [];
      if (cats.length > 0) setActiveLabel(cats[0].name);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if (e.detail?.name) setActiveLabel(e.detail.name);
      else if (e.detail?.tags) setActiveLabel(e.detail.tags.join(" + "));
    };
    window.addEventListener("category-change", handler);
    return () => window.removeEventListener("category-change", handler);
  }, []);

  // Listen for auth-modal-open events from gated features
  useEffect(() => {
    const handler = () => setShowAuth(true);
    window.addEventListener("open-auth-modal", handler);
    return () => window.removeEventListener("open-auth-modal", handler);
  }, []);

  return (
    <>
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
            <Button variant={location.pathname === "/" ? "secondary" : "ghost"} size="sm" asChild data-testid="nav-leaderboard">
              <Link to="/" className="flex items-center gap-2">
                <Trophy className="h-4 w-4" />
                <span className="hidden sm:inline">Leaderboard</span>
              </Link>
            </Button>

            <Button variant={location.pathname === "/correlation" ? "secondary" : "ghost"} size="sm" asChild data-testid="nav-correlation">
              <Link to="/correlation" className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                <span className="hidden sm:inline">Model Analysis</span>
              </Link>
            </Button>

            <Button variant={location.pathname === "/methodology" ? "secondary" : "ghost"} size="sm" asChild data-testid="nav-methodology">
              <Link to="/methodology" className="flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                <span className="hidden sm:inline">Methodology</span>
              </Link>
            </Button>

            <Button variant={location.pathname.startsWith("/admin") ? "secondary" : "ghost"} size="sm" asChild data-testid="nav-admin">
              <Link to="/admin" className="flex items-center gap-2">
                <Shield className="h-4 w-4" />
                <span className="hidden sm:inline">Admin</span>
              </Link>
            </Button>

            <div className="w-px h-5 bg-border mx-1" />

            {authLoading ? (
              <div className="h-8 w-8 rounded-full bg-secondary animate-pulse" />
            ) : user ? (
              <div className="flex items-center gap-1.5">
                {user.picture ? (
                  <img src={user.picture} alt="" className="h-7 w-7 rounded-full border border-border" referrerPolicy="no-referrer" />
                ) : (
                  <div className="h-7 w-7 rounded-full bg-accent/10 flex items-center justify-center">
                    <User className="h-3.5 w-3.5 text-accent" />
                  </div>
                )}
                <span className="hidden md:inline text-xs text-muted-foreground max-w-[100px] truncate">{user.name || user.email}</span>
                <Button variant="ghost" size="sm" onClick={logout} className="h-7 px-2 text-xs" data-testid="nav-logout">
                  <LogOut className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : (
              <Button size="sm" onClick={() => setShowAuth(true)} className="gap-1.5 h-8 text-xs" data-testid="nav-login-btn">
                <LogIn className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Sign in</span>
              </Button>
            )}
          </div>
        </div>
      </div>
    </nav>
    <AuthModal open={showAuth} onClose={() => setShowAuth(false)} />
    </>
  );
}
