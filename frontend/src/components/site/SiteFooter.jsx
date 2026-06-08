import { Link } from "react-router-dom";
import { Linkedin, Instagram, Github, Facebook, BookOpen, Trophy } from "lucide-react";

function XIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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

const COLS = [
  {
    h: "Platform",
    links: [
      { l: "Rankings", to: "#rankings" },
      { l: "Categories", to: "#categories" },
      { l: "Recent Papers", to: "#recent" },
      { l: "Full Leaderboard", to: "/leaderboard", internal: true },
      { l: "FAQ", to: "#faq" },
    ],
  },
  {
    h: "Research",
    links: [
      { l: "Methodology", to: "/methodology", internal: true },
      { l: "Validation", to: "/validation", internal: true },
      { l: "Model Analysis", to: "/correlation", internal: true },
    ],
  },
  {
    h: "Company",
    links: [
      { l: "About", to: "#about" },
      { l: "Privacy", to: "/privacy", internal: true },
      { l: "Impressum", to: "/impressum", internal: true },
      { l: "Contact", to: "/contact", internal: true },
    ],
  },
];

export default function SiteFooter() {
  return (
    <footer className="bg-slate-50 text-slate-600 border-t border-slate-200" data-testid="site-footer">
      <div className="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-10">
          <div className="lg:col-span-2 lg:pr-6">
            <Link to="/" className="flex items-center gap-[10px]">
              <Trophy className="h-6 w-6 text-blue-600 shrink-0 -translate-y-[2px]" strokeWidth={1.8} />
              <img src="/kurate-logo.png" alt="Kurate.org" className="h-[29px] w-auto" draggable={false} />
            </Link>
            <p className="mt-5 text-sm leading-relaxed text-slate-600 max-w-sm">
              Scientific paper rankings, category leaderboards, and research intelligence signals for discovering important preprints earlier.
            </p>
            <p className="mt-4 text-xs leading-relaxed text-slate-500 max-w-sm">
              Kurate provides AI-assisted research discovery signals. Rankings are intended to support exploration and prioritisation, not replace peer review.
            </p>
          </div>

          {COLS.map((c) => (
            <div key={c.h}>
              <h4 className="text-slate-900 font-sans font-semibold text-xs tracking-[0.12em] uppercase mb-4">{c.h}</h4>
              <ul className="space-y-2.5">
                {c.links.map((l) => (
                  <li key={l.l}>
                    {l.internal ? (
                      <Link to={l.to} className="text-sm text-slate-600 hover:text-blue-600 transition-colors">
                        {l.l}
                      </Link>
                    ) : (
                      <a href={l.to} className="text-sm text-slate-600 hover:text-blue-600 transition-colors">
                        {l.l}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <div>
            <h4 className="text-slate-900 font-sans font-semibold text-xs tracking-[0.12em] uppercase mb-4">Social</h4>
            <ul className="space-y-2.5">
              {SOCIAL.map(({ href, label, Icon, key }) => (
                <li key={key}>
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid={`footer-social-${key}`}
                    className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-blue-600 transition-colors"
                  >
                    <Icon className="h-3.5 w-3.5" /> {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-14 pt-6 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500">
          <span>&copy; Kurate.org. All rights reserved.</span>
          <span className="font-serif italic">Discovery layer for fast-moving scientific work.</span>
        </div>
      </div>
    </footer>
  );
}
