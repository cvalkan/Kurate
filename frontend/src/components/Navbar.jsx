import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Trophy, Shield, BarChart3, BookOpen, LogIn, LogOut, User, Menu, X, FlaskConical, Bookmark } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { AuthModal } from "@/components/AuthModal";

const API = process.env.REACT_APP_BACKEND_URL;

const NAV_LINKS = [
  { path: "/", label: "Leaderboard", icon: Trophy, exact: true },
  { path: "/correlation", label: "Model Analysis", icon: BarChart3 },
  { path: "/methodology", label: "Methodology", icon: BookOpen },
  { path: "/validation", label: "Validation", icon: FlaskConical },
  { path: "/admin", label: "Admin", icon: Shield, prefix: true },
];

export default function Navbar() {
  const location = useLocation();
  const { user, loading: authLoading, logout } = useAuth();
  const [activeLabel, setActiveLabel] = useState("");
  const [showAuth, setShowAuth] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

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

  useEffect(() => {
    const handler = () => setShowAuth(true);
    window.addEventListener("open-auth-modal", handler);
    return () => window.removeEventListener("open-auth-modal", handler);
  }, []);

  // Close mobile menu on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const isActive = (link) => {
    if (link.exact) return location.pathname === link.path;
    if (link.prefix) return location.pathname.startsWith(link.path);
    return location.pathname === link.path;
  };

  return (
    <>
    <nav className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <div className="flex h-14 items-center justify-between">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity min-w-0" data-testid="navbar-logo">
            <Trophy className="h-6 w-6 text-accent shrink-0" />
            <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 shrink-0 translate-y-[2px]" />
            {activeLabel && (
              <span className="hidden sm:inline text-xs text-muted-foreground font-mono border border-border rounded px-1.5 py-0.5">
                {activeLabel.toUpperCase()}
              </span>
            )}
          </Link>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-1">
            {NAV_LINKS.map(link => {
              const Icon = link.icon;
              return (
                <Button key={link.path} variant={isActive(link) ? "secondary" : "ghost"} size="sm" asChild data-testid={`nav-${link.label.toLowerCase().replace(" ", "-")}`}>
                  <Link to={link.path} className="flex items-center gap-2">
                    <Icon className="h-4 w-4" />
                    {link.label}
                  </Link>
                </Button>
              );
            })}

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
                <span className="hidden lg:inline text-xs text-muted-foreground max-w-[100px] truncate">{user.name || user.email}</span>
                <Link to="/profile" className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground flex items-center" data-testid="nav-profile">
                  <User className="h-3.5 w-3.5" />
                </Link>
                <Link to="/bookmarks" onClick={() => sessionStorage.setItem("bk_tab", '"bookmarks"')} className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground flex items-center" data-testid="nav-bookmarks">
                  <Bookmark className="h-3.5 w-3.5" />
                </Link>
                <Button variant="ghost" size="sm" onClick={logout} className="h-7 px-2 text-xs" data-testid="nav-logout">
                  <LogOut className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : (
              <Button size="sm" onClick={() => setShowAuth(true)} className="gap-1.5 h-8 text-xs" data-testid="nav-login-btn">
                <LogIn className="h-3.5 w-3.5" />
                Sign in
              </Button>
            )}
          </div>

          {/* Mobile: hamburger (left) + auth (right) */}
          <div className="flex md:hidden items-center gap-2 order-first">
            <Button variant="ghost" size="sm" onClick={() => setMobileOpen(!mobileOpen)} className="h-8 w-8 p-0" data-testid="mobile-menu-toggle">
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </Button>
          </div>

          {/* Mobile: auth button (right side) */}
          <div className="flex md:hidden items-center gap-2">
            {!authLoading && !user && (
              <Button size="sm" onClick={() => setShowAuth(true)} className="gap-1 h-8 text-xs" data-testid="nav-login-btn-mobile">
                <LogIn className="h-3.5 w-3.5" />
              </Button>
            )}
            {!authLoading && user && (
              <>
                {user.picture ? (
                  <img src={user.picture} alt="" className="h-7 w-7 rounded-full border border-border" referrerPolicy="no-referrer" />
                ) : (
                  <div className="h-7 w-7 rounded-full bg-accent/10 flex items-center justify-center">
                    <User className="h-3.5 w-3.5 text-accent" />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Mobile dropdown */}
      {mobileOpen && (
        <div className="md:hidden border-t border-border bg-background" data-testid="mobile-menu">
          <div className="container mx-auto px-4 py-2 space-y-1">
            {NAV_LINKS.map(link => {
              const Icon = link.icon;
              return (
                <Link
                  key={link.path}
                  to={link.path}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                    isActive(link) ? "bg-secondary font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                  }`}
                  data-testid={`mobile-nav-${link.label.toLowerCase().replace(" ", "-")}`}
                >
                  <Icon className="h-4 w-4" />
                  {link.label}
                </Link>
              );
            })}
            {user && (
              <button
                onClick={() => { logout(); setMobileOpen(false); }}
                className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground hover:bg-secondary/50 hover:text-foreground w-full text-left"
                data-testid="mobile-nav-logout"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            )}
          </div>
        </div>
      )}
    </nav>
    <AuthModal open={showAuth} onClose={() => setShowAuth(false)} />
    </>
  );
}
