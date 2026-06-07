import { Link } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen } from "lucide-react";

const NAV = [
  { to: "#rankings", label: "Rankings" },
  { to: "#categories", label: "Categories" },
  { to: "#methodology", label: "Methodology" },
  { to: "#faq", label: "FAQ" },
  { to: "#about", label: "About" },
];

const SOCIAL = [
  { href: "https://www.linkedin.com/company/kurate-org", label: "LinkedIn", Icon: Linkedin, key: "linkedin" },
  { href: "https://www.instagram.com/kurate2026/", label: "Instagram", Icon: Instagram, key: "instagram" },
  { href: "https://github.com/cvalkan/PaperSumo", label: "GitHub", Icon: Github, key: "github" },
  { href: "https://www.facebook.com/Kurate/", label: "Facebook", Icon: Facebook, key: "facebook" },
  { href: "https://medium.com/kurate", label: "Medium", Icon: BookOpen, key: "medium" },
];

export default function TopNav() {
  return (
    <header
      data-testid="top-nav"
      className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link to="/" className="flex items-center group" data-testid="brand-link" aria-label="Kurate.org home">
            <img
              src="/kurate-logo.png"
              alt="Kurate.org"
              className="h-7 w-auto"
              draggable={false}
            />
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
