import { Link } from "react-router-dom";
import { Trophy } from "lucide-react";

const COLS = [
  {
    h: "Platform",
    links: [
      { l: "Rankings", to: "#rankings" },
      { l: "Categories", to: "#categories" },
      { l: "Full Leaderboard", to: "/leaderboard" },
      { l: "FAQ", to: "#faq" },
    ],
  },
  {
    h: "Research",
    links: [
      { l: "Methodology", to: "/methodology" },
      { l: "Validation", to: "/validation" },
      { l: "Model Analysis", to: "/correlation" },
    ],
  },
  {
    h: "Company",
    links: [
      { l: "About", to: "#about" },
      { l: "Privacy", to: "/privacy" },
      { l: "Impressum", to: "/impressum" },
      { l: "Contact", to: "/contact" },
    ],
  },
];

export default function SiteFooter() {
  return (
    <footer className="w-full border-t border-slate-200 bg-white" data-testid="site-footer">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-8">
          {/* Brand */}
          <div className="col-span-2 sm:col-span-1">
            <Link to="/" className="flex items-center gap-[10px] hover:opacity-80 transition-opacity" data-testid="footer-logo">
              <Trophy className="h-5 w-5 text-blue-600 shrink-0 -translate-y-[2px]" />
              <img src="/kurate-logo.png" alt="Kurate.org" className="h-5 shrink-0" />
            </Link>
            <p className="text-xs text-slate-500 mt-3 leading-relaxed max-w-[200px]">
              AI-assisted scientific paper rankings across live arXiv categories.
            </p>
          </div>

          {/* Link columns */}
          {COLS.map((col) => (
            <div key={col.h}>
              <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">{col.h}</h4>
              <ul className="mt-3 space-y-2">
                {col.links.map((link) => (
                  <li key={link.l}>
                    {link.to.startsWith("#") ? (
                      <a href={link.to} className="text-xs text-slate-500 hover:text-slate-900 transition-colors">
                        {link.l}
                      </a>
                    ) : (
                      <Link to={link.to} className="text-xs text-slate-500 hover:text-slate-900 transition-colors">
                        {link.l}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-between pt-8 mt-8 border-t border-slate-100 text-[11px] text-slate-400">
          <span>&copy; {new Date().getFullYear()} Kurate.org. All rights reserved.</span>
          <span className="mt-2 sm:mt-0">Scientific preprint rankings powered by AI-assisted comparison.</span>
        </div>
      </div>
    </footer>
  );
}
