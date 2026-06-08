import { Link } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen, Trophy } from "lucide-react";
import { useBasePath } from "@/contexts/BasePathContext";

// X (Twitter) icon — not in lucide-react
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
  return (
    <header
      data-testid="top-nav"
      className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur-md supports-[backdrop-filter]:bg-white/80"
    >
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link to={basePath || "/"} className="flex items-center gap-[10px] group" data-testid="brand-link" aria-label="Kurate.org home">
            <Trophy className="h-6 w-6 text-blue-600 shrink-0 -translate-y-[2px]" strokeWidth={1.8} />
            <img
              src="/kurate-logo.png"
              alt="Kurate.org"
              className="h-[29px] w-auto"
              draggable={false}
            />
          </Link>

          <nav className="hidden lg:flex items-center gap-7" aria-label="Primary">
            {NAV.map((item) =>
              item.internal ? (
                <Link
                  key={item.label}
                  to={item.to}
                  data-testid={`nav-link-${item.label.toLowerCase()}`}
                  className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
                >
                  {item.label}
                </Link>
              ) : (
                <a
                  key={item.label}
                  href={item.to}
                  data-testid={`nav-link-${item.label.toLowerCase()}`}
                  className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
                >
                  {item.label}
                </a>
              )
            )}
          </nav>

          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-0.5 pr-3 border-r border-slate-200">
              {SOCIAL.map(({ href, label, Icon, key }) => (
                <a
                  key={key}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid={`social-${key}`}
                  aria-label={label}
                  className="p-2 text-slate-500 hover:text-blue-600 transition-colors"
                >
                  <Icon className="h-4 w-4" strokeWidth={1.5} />
                </a>
              ))}
            </div>
            <Link
              to={`${basePath}/leaderboard`}
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
