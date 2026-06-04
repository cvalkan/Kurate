import { Linkedin, Twitter, BookOpen, FlaskConical } from "lucide-react";

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
    <footer className="bg-slate-950 text-slate-300 border-t border-slate-900">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-10">
          <div className="lg:col-span-2 lg:pr-6">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-sm border border-slate-700 bg-slate-900">
                <FlaskConical className="h-4 w-4 text-blue-400" strokeWidth={1.5} />
              </span>
              <span className="font-serif text-2xl font-semibold tracking-tight text-white">
                Kurate<span className="text-blue-400">.</span><span className="text-slate-500 text-base font-normal">org</span>
              </span>
            </div>
            <p className="mt-4 text-sm leading-relaxed text-slate-400 max-w-sm">
              Scientific paper rankings, category leaderboards, and research intelligence signals for discovering important preprints earlier.
            </p>
            <p className="mt-4 text-xs leading-relaxed text-slate-500 max-w-sm">
              Kurate provides AI-assisted research discovery signals. Rankings are intended to support exploration and prioritisation, not replace peer review.
            </p>
          </div>

          {COLS.map((c) => (
            <div key={c.h}>
              <h4 className="text-white font-sans font-semibold text-xs tracking-[0.12em] uppercase mb-4">{c.h}</h4>
              <ul className="space-y-2.5">
                {c.links.map((l) => (
                  <li key={l.l}>
                    <a href={l.to} data-testid={`footer-${c.h.toLowerCase()}-${l.l.toLowerCase().replace(/\s+/g, "-")}`} className="text-sm text-slate-400 hover:text-white transition-colors">{l.l}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <div>
            <h4 className="text-white font-sans font-semibold text-xs tracking-[0.12em] uppercase mb-4">Social</h4>
            <ul className="space-y-2.5">
              <li><a href="#" data-testid="footer-social-linkedin" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"><Linkedin className="h-3.5 w-3.5" /> LinkedIn</a></li>
              <li><a href="#" data-testid="footer-social-twitter" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"><Twitter className="h-3.5 w-3.5" /> X / Twitter</a></li>
              <li><a href="#" data-testid="footer-social-medium" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"><BookOpen className="h-3.5 w-3.5" /> Medium / Articles</a></li>
            </ul>
          </div>
        </div>

        <div className="mt-14 pt-6 border-t border-slate-900 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500">
          <span>© Kurate.org. All rights reserved.</span>
          <span className="font-serif italic">Discovery layer for fast-moving scientific work.</span>
        </div>
      </div>
    </footer>
  );
}
