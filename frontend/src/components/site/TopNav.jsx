import { Link } from "react-router-dom";
import { Linkedin, Twitter, BookOpen, FlaskConical } from "lucide-react";

const NAV = [
  { to: "#rankings", label: "Rankings" },
  { to: "#categories", label: "Categories" },
  { to: "#methodology", label: "Methodology" },
  { to: "#validation", label: "Validation" },
  { to: "#recent", label: "Recent Papers" },
  { to: "#about", label: "About" },
];

export default function TopNav() {
  return (
    <header
      data-testid="top-nav"
      className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link to="/" className="flex items-center gap-2 group" data-testid="brand-link">
            <span className="flex h-7 w-7 items-center justify-center rounded-sm border border-slate-200 bg-white">
              <FlaskConical className="h-4 w-4 text-blue-600" strokeWidth={1.5} />
            </span>
            <span className="font-serif text-2xl font-semibold tracking-tight text-slate-900">
              Kurate
              <span className="text-blue-600">.</span>
              <span className="text-slate-500 text-base font-normal">org</span>
            </span>
          </Link>

          <nav className="hidden lg:flex items-center gap-7" aria-label="Primary">
            {NAV.map((item) => (
              <a
                key={item.label}
                href={item.to}
                data-testid={`nav-link-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
              >
                {item.label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-1 pr-3 border-r border-slate-200">
              <a href="#" data-testid="social-linkedin" aria-label="LinkedIn" className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                <Linkedin className="h-4 w-4" strokeWidth={1.5} />
              </a>
              <a href="#" data-testid="social-twitter" aria-label="X / Twitter" className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                <Twitter className="h-4 w-4" strokeWidth={1.5} />
              </a>
              <a href="#" data-testid="social-medium" aria-label="Medium / Articles" className="p-2 text-slate-500 hover:text-blue-600 transition-colors">
                <BookOpen className="h-4 w-4" strokeWidth={1.5} />
              </a>
            </div>
            <Link
              to="/leaderboard"
              data-testid="explore-rankings-button"
              className="inline-flex items-center justify-center rounded-sm bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              Explore Rankings
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
