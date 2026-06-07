import { Linkedin, Instagram, Github, Facebook, BookOpen } from "lucide-react";

const SOCIAL = [
  { href: "https://www.linkedin.com/company/kurate-org", label: "LinkedIn", Icon: Linkedin, key: "linkedin" },
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
      { l: "Full Leaderboard", to: "/leaderboard" },
      { l: "FAQ", to: "#faq" },
    ],
  },
  {
    h: "Research",
    links: [
      { l: "Methodology", to: "#methodology" },
      { l: "Validation", to: "#validation" },
      { l: "Model Agreement", to: "#methodology" },
      { l: "Research Signals", to: "#methodology" },
    ],
  },
  {
    h: "Company",
    links: [
      { l: "About", to: "#about" },
      { l: "Privacy", to: "#" },
      { l: "Terms", to: "#" },
      { l: "Impressum", to: "#" },
      { l: "Contact", to: "#" },
    ],
  },
];

export default function SiteFooter() {
  return (
    <footer className="bg-slate-50 text-slate-600 border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-10">
          <div className="lg:col-span-2 lg:pr-6">
            <div className="flex items-center">
              <img src="/kurate-logo.png" alt="Kurate.org" className="h-7 w-auto" draggable={false} />
            </div>
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
                    <a href={l.to} data-testid={`footer-${c.h.toLowerCase()}-${l.l.toLowerCase().replace(/\s+/g, "-")}`} className="text-sm text-slate-600 hover:text-blue-600 transition-colors">{l.l}</a>
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
          <span>© Kurate.org. All rights reserved.</span>
          <span className="font-serif italic">Discovery layer for fast-moving scientific work.</span>
        </div>
      </div>
    </footer>
  );
}
