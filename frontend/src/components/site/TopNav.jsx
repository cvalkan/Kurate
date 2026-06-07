import { Link } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen, Trophy } from "lucide-react";

const NAV = [
  { to: "#rankings", label: "Rankings", external: false },
  { to: "#categories", label: "Categories", external: false },
  { to: "/methodology", label: "Methodology", external: false },
  { to: "#faq", label: "FAQ", external: false },
  { to: "#about", label: "About", external: false },
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
    <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-[10px] hover:opacity-80 transition-opacity" data-testid="topnav-logo">
          <Trophy className="h-5 w-5 text-blue-600 shrink-0 -translate-y-[2px]" />
          <img src="/kurate-logo.png" alt="Kurate.org" className="h-6 shrink-0" />
        </Link>

        {/* Desktop nav + social */}
        <div className="hidden md:flex items-center gap-6">
          <nav className="flex items-center gap-6 text-sm font-medium text-slate-600">
            {NAV.map((n) =>
              n.to.startsWith("#") ? (
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

          {/* Social icons */}
          <div className="flex items-center gap-3 border-l border-slate-200 pl-5">
            {SOCIAL.map(({ href, label, Icon, key }) => (
              <a
                key={key}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={label}
                className="text-slate-400 hover:text-slate-600 transition-colors"
                data-testid={`topnav-social-${key}`}
              >
                <Icon className="h-4 w-4" />
              </a>
            ))}
          </div>
        </div>

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
