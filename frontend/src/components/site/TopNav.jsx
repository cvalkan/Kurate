import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen, Trophy, Menu, X, LogIn, LogOut, User, Bookmark as BookmarkIcon } from "lucide-react";
import { useBasePath } from "@/contexts/BasePathContext";
import { useAuth } from "@/contexts/AuthContext";

function XIcon({ className, strokeWidth }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth || 2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4l6.5 7.5M20 4l-6.5 7.5m0 0L20 20m-6.5-8.5L4 20" />
    </svg>
  );
}

const SOCIAL = [
  { href: "https://www.linkedin.com/company/kurate-org", label: "LinkedIn", Icon: Linkedin, key: "linkedin" },
  { href: "https://x.com/kurateorg", label: "X", Icon: XIcon, key: "x" },
  { href: "https://www.instagram.com/kurate2026/", label: "Instagram", Icon: Instagram, key: "instagram" },
  { href: "https://github.com/cvalkan/PaperSumo", label: "GitHub", Icon: Github, key: "github" },
  { href: "https://www.facebook.com/Kurate/", label: "Facebook", Icon: Facebook, key: "facebook" },
  { href: "https://medium.com/kurate", label: "Medium", Icon: BookOpen, key: "medium" },
];

const requireAuth = () => window.dispatchEvent(new Event("open-auth-modal"));

export default function TopNav() {
  const basePath = useBasePath();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuth();
  const isLoggedIn = !!user;

  // Context-aware nav: homepage gets section anchors, other pages get full page links
  const isHomepage = location.pathname === basePath || location.pathname === `${basePath}/`;
  const NAV = isHomepage
    ? [
        { to: "#rankings", label: "Rankings" },
        { to: "#categories", label: "Categories" },
        { to: "#methodology", label: "Methodology" },
        { to: "#faq", label: "FAQ" },
        { to: "#about", label: "About" },
      ]
    : [
        { to: basePath || "/", label: "Home" },
        { to: `${basePath}/methodology`, label: "Methodology" },
        { to: `${basePath}/correlation`, label: "Model Analysis" },
        { to: `${basePath}/validation`, label: "Validation" },
      ];

  const renderNavLink = (item, onClick) => {
    if (item.to.startsWith("#")) {
      return (
        <a key={item.label} href={item.to} onClick={onClick}
          className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm transition-colors lg:px-0 lg:py-0 lg:hover:bg-transparent">
          {item.label}
        </a>
      );
    }
    return (
      <Link key={item.label} to={item.to} onClick={onClick}
        className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm transition-colors lg:px-0 lg:py-0 lg:hover:bg-transparent">
        {item.label}
      </Link>
    );
  };

  return (
    <header
      data-testid="top-nav"
      className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur-md supports-[backdrop-filter]:bg-white/80"
    >
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
        <div className="flex h-14 sm:h-16 items-center justify-between">
          {/* Logo */}
          <Link to={basePath || "/"} className="flex items-center gap-2 sm:gap-[10px] group" data-testid="brand-link" aria-label="Kurate.org home">
            <Trophy className="h-5 w-5 sm:h-6 sm:w-6 text-blue-600 shrink-0 -translate-y-[1px] sm:-translate-y-[2px]" strokeWidth={1.8} />
            <img src="/kurate-logo.png" alt="Kurate.org" className="h-5 sm:h-[29px] w-auto" draggable={false} />
          </Link>

          {/* Desktop nav */}
          <nav className="hidden lg:flex items-center gap-7" aria-label="Primary">
            {NAV.map((item) => renderNavLink(item))}
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Social icons — desktop only */}
            <div className="hidden md:flex items-center gap-0.5 pr-3 border-r border-slate-200">
              {SOCIAL.map(({ href, label, Icon, key }) => (
                <a key={key} href={href} target="_blank" rel="noopener noreferrer" aria-label={label}
                  className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                  <Icon className="h-4 w-4" strokeWidth={1.5} />
                </a>
              ))}
            </div>

            {/* Auth section */}
            {isLoggedIn ? (
              <div className="hidden sm:flex items-center gap-1">
                <Link to="/bookmarks" className="p-2 text-slate-500 hover:text-blue-600 transition-colors" title="Bookmarks">
                  <BookmarkIcon className="h-4 w-4" />
                </Link>
                <Link to="/profile" className="p-2 text-slate-500 hover:text-blue-600 transition-colors" title="Profile">
                  <User className="h-4 w-4" />
                </Link>
                <button onClick={logout} className="p-2 text-slate-500 hover:text-red-500 transition-colors" title="Sign out">
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <button onClick={requireAuth}
                className="hidden sm:inline-flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors">
                <LogIn className="h-4 w-4" /> Sign in
              </button>
            )}

            {/* CTA */}
            <Link
              to={`${basePath}/leaderboard`}
              data-testid="explore-rankings-button"
              className="inline-flex items-center justify-center gap-1.5 rounded-sm bg-blue-600 px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <span className="sm:hidden">Rankings</span>
              <span className="hidden sm:inline">Explore Rankings</span>
            </Link>

            {/* Hamburger */}
            <button onClick={() => setMobileOpen(v => !v)} className="lg:hidden p-1.5 text-slate-600 hover:text-slate-900 transition-colors" aria-label="Toggle menu">
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden border-t border-slate-100 bg-white">
          <div className="mx-auto max-w-7xl px-5 sm:px-6 py-4 space-y-3">
            <nav className="flex flex-col gap-1">
              {NAV.map((item) => renderNavLink(item, () => setMobileOpen(false)))}
            </nav>
            <div className="border-t border-slate-100 pt-3">
              {isLoggedIn ? (
                <div className="flex flex-col gap-1">
                  <Link to="/profile" onClick={() => setMobileOpen(false)} className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm flex items-center gap-2">
                    <User className="h-4 w-4" /> Profile
                  </Link>
                  <Link to="/bookmarks" onClick={() => setMobileOpen(false)} className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm flex items-center gap-2">
                    <BookmarkIcon className="h-4 w-4" /> Bookmarks
                  </Link>
                  <button onClick={() => { logout(); setMobileOpen(false); }} className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm text-left">
                    Sign out
                  </button>
                </div>
              ) : (
                <button onClick={() => { requireAuth(); setMobileOpen(false); }}
                  className="w-full inline-flex items-center justify-center gap-1.5 rounded-sm border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                  <LogIn className="h-4 w-4" /> Sign in
                </button>
              )}
            </div>
            <div className="border-t border-slate-100 pt-3">
              <div className="flex items-center gap-3">
                {SOCIAL.map(({ href, label, Icon, key }) => (
                  <a key={key} href={href} target="_blank" rel="noopener noreferrer" aria-label={label}
                    className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                    <Icon className="h-4 w-4" strokeWidth={1.5} />
                  </a>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
