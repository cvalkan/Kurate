import { Link } from "react-router-dom";
import { Trophy } from "lucide-react";

const NAV = [
  { to: "#rankings", label: "Rankings", external: false },
  { to: "#categories", label: "Categories", external: false },
  { to: "/methodology", label: "Methodology", external: false },
  { to: "#faq", label: "FAQ", external: false },
  { to: "#about", label: "About", external: false },
];

export default function TopNav() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-[10px] hover:opacity-80 transition-opacity" data-testid="topnav-logo">
          <Trophy className="h-5 w-5 text-blue-600 shrink-0 -translate-y-[2px]" />
          <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 shrink-0" />
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-600">
          {NAV.map((n) =>
            n.external ? (
              <a key={n.to} href={n.to} className="hover:text-slate-900 transition-colors" data-testid={`topnav-${n.label.toLowerCase()}`}>
                {n.label}
              </a>
            ) : n.to.startsWith("#") ? (
              <a key={n.to} href={n.to} className="hover:text-slate-900 transition-colors" data-testid={`topnav-${n.label.toLowerCase()}`}>
                {n.label}
              </a>
            ) : (
              <Link key={n.to} to={n.to} className="hover:text-slate-900 transition-colors" data-testid={`topnav-${n.label.toLowerCase()}`}>
                {n.label}
              </Link>
            )
          )}
        </nav>

        {/* CTA */}
        <Link
          to="/leaderboard"
          className="hidden sm:inline-flex items-center gap-1.5 rounded-sm border border-slate-900 bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 transition-colors"
          data-testid="topnav-explore-btn"
        >
          <Trophy className="h-3.5 w-3.5" />
          Explore Rankings
        </Link>
      </div>
    </header>
  );
}
