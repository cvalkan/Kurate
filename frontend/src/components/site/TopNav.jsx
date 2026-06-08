import { useState } from "react";
import { Link } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen, Trophy, Menu, X } from "lucide-react";
import { useBasePath } from "@/contexts/BasePathContext";

function XIcon({ className, strokeWidth }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth || 2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4l6.5 7.5M20 4l-6.5 7.5m0 0L20 20m-6.5-8.5L4 20" />
    </svg>
  );
}

const NAV = [
  { to: "#rankings", label: "Rankings" },
  { to: "#categories", label: "Categories" },
  { to: "#methodology", label: "Methodology" },
  { to: "#faq", label: "FAQ" },
  { to: "#about", label: "About" },
];

const SOCIAL = [
  { href: "https://www.linkedin.com/company/kurate-org", label: "LinkedIn", Icon: Linkedin, key: "linkedin" },
  { href: "https://x.com/kurateorg", label: "X", Icon: XIcon, key: "x" },
  { href: "https://www.instagram.com/kurate2026/", label: "Instagram", Icon: Instagram, key: "instagram" },
  { href: "https://github.com/cvalkan/PaperSumo", label: "GitHub", Icon: Github, key: "github" },
  { href: "https://www.facebook.com/Kurate/", label: "Facebook", Icon: Facebook, key: "facebook" },
  { href: "https://medium.com/kurate", label: "Medium", Icon: BookOpen, key: "medium" },
];

export default function TopNav() {
  const basePath = useBasePath();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header
      data-testid="top-nav"
      className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur-md supports-[backdrop-filter]:bg-white/80"
    >
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
        <div className="flex h-14 sm:h-16 items-center justify-between">
          {/* Logo — smaller on mobile */}
          <Link to={basePath || "/"} className="flex items-center gap-2 sm:gap-[10px] group" data-testid="brand-link" aria-label="Kurate.org home">
            <Trophy className="h-5 w-5 sm:h-6 sm:w-6 text-blue-600 shrink-0 -translate-y-[1px] sm:-translate-y-[2px]" strokeWidth={1.8} />
            <img
              src="/kurate-logo.png"
              alt="Kurate.org"
              className="h-5 sm:h-[29px] w-auto"
              draggable={false}
            />
          </Link>

          {/* Desktop nav */}
          <nav className="hidden lg:flex items-center gap-7" aria-label="Primary">
            {NAV.map((item) =>
              item.to.startsWith("#") ? (
                <a key={item.label} href={item.to} data-testid={`nav-link-${item.label.toLowerCase()}`}
                  className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors">{item.label}</a>
              ) : (
                <Link key={item.label} to={item.to} data-testid={`nav-link-${item.label.toLowerCase()}`}
                  className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors">{item.label}</Link>
              )
            )}
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Social icons — desktop only */}
            <div className="hidden md:flex items-center gap-0.5 pr-3 border-r border-slate-200">
              {SOCIAL.map(({ href, label, Icon, key }) => (
                <a key={key} href={href} target="_blank" rel="noopener noreferrer" data-testid={`social-${key}`}
                  aria-label={label} className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                  <Icon className="h-4 w-4" strokeWidth={1.5} />
                </a>
              ))}
            </div>

            {/* CTA — full text on desktop, icon on mobile */}
            <Link
              to={`${basePath}/leaderboard`}
              data-testid="explore-rankings-button"
              className="inline-flex items-center justify-center gap-1.5 rounded-sm bg-blue-600 px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <span className="sm:hidden">Rankings</span>
              <span className="hidden sm:inline">Explore Rankings</span>
            </Link>

            {/* Hamburger — mobile/tablet only */}
            <button
              onClick={() => setMobileOpen(v => !v)}
              className="lg:hidden p-1.5 text-slate-600 hover:text-slate-900 transition-colors"
              aria-label="Toggle menu"
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden border-t border-slate-100 bg-white">
          <div className="mx-auto max-w-7xl px-5 sm:px-6 py-4 space-y-4">
            <nav className="flex flex-col gap-1">
              {NAV.map((item) =>
                item.to.startsWith("#") ? (
                  <a key={item.label} href={item.to} onClick={() => setMobileOpen(false)}
                    className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm transition-colors">{item.label}</a>
                ) : (
                  <Link key={item.label} to={item.to} onClick={() => setMobileOpen(false)}
                    className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-sm transition-colors">{item.label}</Link>
                )
              )}
            </nav>
            <div className="border-t border-slate-100 pt-3">
              <div className="flex items-center gap-3">
                {SOCIAL.map(({ href, label, Icon, key }) => (
                  <a key={key} href={href} target="_blank" rel="noopener noreferrer"
                    aria-label={label} className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
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
