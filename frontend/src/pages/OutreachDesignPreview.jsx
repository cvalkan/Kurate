import React, { useState, useEffect } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { ArrowLeft, Twitter, Heart, Repeat2, MessageSquare, Quote, ExternalLink } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL || "";

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

const CONFIDENCE_COLORS = {
  high: "bg-green-100 text-green-800 border-green-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-600 border-gray-200",
};

const MEDAL = ["🥇", "🥈", "🥉"];

export default function OutreachDesignPreview() {
  const [categories, setCategories] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await axios.get(`${API}/api/admin/outreach/medalists`, {
          headers: getAdminHeaders(),
          params: { period: "monthly:2026-3", top_n: 3 },
        });

        const cats = res.data?.categories || [];
        setCategories(cats);

        const allCandidates = [];
        for (const cat of cats) {
          for (const paper of cat.papers || []) {
            if (paper.candidates?.length > 0) allCandidates.push(...paper.candidates);
          }
        }

        if (allCandidates.length === 0) {
          // Fallback sample (dev only)
          allCandidates.push(
            {
              handle: "DrAI_Researcher", name: "Dr. Jane Smith", confidence: "high",
              tweet_url: "https://x.com/fake",
              tweet_text: "Our new paper on LLM reasoning is out! SOTA on GSM8K via self-correction.",
              tweet_likes: 1245, tweet_retweets: 340, liked: false, quote_tweeted: false,
            },
            {
              handle: "ML_Student99", name: "John Doe", confidence: "medium",
              tweet_url: "https://x.com/fake2",
              tweet_text: "finally published the multimodal dataset we've been working on for 2 years",
              tweet_likes: 12, tweet_retweets: 2, liked: true, quote_tweeted: false,
            },
            {
              handle: "RobotLab_Update", name: "Robotics Lab", confidence: "low",
              tweet_url: "https://x.com/fake3",
              tweet_text: "New preprint on arXiv: Distributed control for swarm robotics.",
              tweet_likes: 0, tweet_retweets: 0, liked: false, quote_tweeted: true,
            },
          );
        }
        setCandidates(allCandidates.slice(0, 4));
      } catch (err) {
        console.error(err);
        setError("Failed to fetch real data. Showing fallback data.");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) {
    return <div className="p-8 text-center text-muted-foreground">Loading preview data…</div>;
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="mb-8">
        <Link to="/admin/outreach" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to Outreach
        </Link>
        <h1 className="text-2xl font-bold mb-2">Outreach Row Design Variants</h1>
        <p className="text-muted-foreground text-sm mb-4">
          Testing different layouts for the candidate row in the Outreach dashboard. All action buttons here are visual-only.
        </p>
        {error && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 p-3 rounded-md text-xs mb-4">{error}</div>
        )}
      </div>

      {/* FULL-PAGE PREVIEW using Variant 1 ——————————————————————— */}
      <section className="mb-12">
        <div className="mb-3 border-b pb-2">
          <h2 className="text-lg font-semibold">Full page preview — Variant 1 applied to Medalists</h2>
          <p className="text-xs text-muted-foreground">Exactly how the real Medalists page will look if you pick Variant 1.</p>
        </div>

        {categories.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm border rounded-lg">
            No medalist data available for the preview period (monthly:2026-3). Real data required for full-page preview.
          </div>
        ) : (
          <div className="space-y-4">
            {categories.map(cat => (
              <div key={cat.category} className="border rounded-lg overflow-x-auto">
                <div className="bg-muted/30 px-3 sm:px-4 py-2 border-b flex items-baseline gap-2">
                  <span className="font-semibold text-sm">{cat.name || cat.category}</span>
                  <span className="text-[10px] sm:text-xs text-muted-foreground">{cat.category}</span>
                  {cat.label && <span className="ml-auto text-[10px] text-muted-foreground">{cat.label}</span>}
                </div>
                <table className="w-full text-sm min-w-[640px]">
                  <tbody>
                    {cat.papers.map((p, i) => (
                      <FullPageMedalistRow key={p.id} paper={p} medal={MEDAL[i] || `#${i + 1}`} />
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Row-only variants for reference ——————————————————————— */}
      <div className="mb-3 border-b pb-2">
        <h2 className="text-lg font-semibold">Row-only variants (side-by-side comparison)</h2>
        <p className="text-xs text-muted-foreground">Same candidate data rendered with each layout. Variant 1 is the one used above.</p>
      </div>

      <div className="grid grid-cols-1 gap-12 mt-4">
        {/* VARIANT 1 */}
        <section>
          <div className="mb-3 border-b pb-2">
            <h2 className="text-lg font-semibold">Variant 1 — Compact Stacked <span className="text-xs font-normal text-green-700 ml-2">(Your pick)</span></h2>
            <p className="text-xs text-muted-foreground">Clean vertical flow. Stats on top right, text in middle, actions bottom right.</p>
          </div>
          <div className="w-[45%] border border-dashed border-gray-300 p-2 bg-white">
            <div className="space-y-3">
              {candidates.map((c, i) => <Variant1 key={i} candidate={c} />)}
            </div>
          </div>
        </section>

        {/* VARIANT 2 */}
        <section>
          <div className="mb-3 border-b pb-2">
            <h2 className="text-lg font-semibold">Variant 2 — Inline Split</h2>
            <p className="text-xs text-muted-foreground">Handle on the left, creating an indentation for the tweet text.</p>
          </div>
          <div className="w-[45%] border border-dashed border-gray-300 p-2 bg-white">
            <div className="space-y-3">
              {candidates.map((c, i) => <Variant2 key={i} candidate={c} />)}
            </div>
          </div>
        </section>

        {/* VARIANT 3 */}
        <section>
          <div className="mb-3 border-b pb-2">
            <h2 className="text-lg font-semibold">Variant 3 — The Grid Density</h2>
            <p className="text-xs text-muted-foreground">Ultra-compact. Handle, stats, and actions share the top line.</p>
          </div>
          <div className="w-[45%] border border-dashed border-gray-300 p-2 bg-white">
            <div className="space-y-3">
              {candidates.map((c, i) => <Variant3 key={i} candidate={c} />)}
            </div>
          </div>
        </section>

        {/* VARIANT 4 */}
        <section>
          <div className="mb-3 border-b pb-2">
            <h2 className="text-lg font-semibold">Variant 4 — Editorial Quote Block</h2>
            <p className="text-xs text-muted-foreground">Uses the confidence color as a left-border. Message-like feel.</p>
          </div>
          <div className="w-[45%] border border-dashed border-gray-300 p-2 bg-white">
            <div className="space-y-3">
              {candidates.map((c, i) => <Variant4 key={i} candidate={c} />)}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------
// Full-page Medalist row using Variant 1 for each candidate
// ----------------------------------------------------------------------
function FullPageMedalistRow({ paper, medal }) {
  const candidates = paper.candidates || [];
  return (
    <tr className="border-b last:border-0 hover:bg-muted/10 align-top">
      <td className="px-3 py-2 w-8 text-center text-lg pt-2.5">{medal}</td>
      <td className="px-3 py-2" style={{ width: "40%" }}>
        <div className="font-medium text-[13px] leading-snug">{paper.title}</div>
        <div className="text-[11px] text-muted-foreground mt-0.5">
          {(paper.authors || []).slice(0, 3).join(", ")}
          {(paper.authors || []).length > 3 && " et al."}
          {paper.arxiv_id && (
            <a
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-2 text-accent hover:underline"
            >
              {paper.arxiv_id}
            </a>
          )}
        </div>
      </td>
      <td className="px-2 py-2 text-xs font-mono text-center pt-3 w-14">{paper.ai_rating || "—"}</td>
      <td className="px-3 py-2">
        {candidates.length > 0 ? (
          <div className="space-y-2">
            {candidates.slice(0, 2).map((c) => (
              <Variant1 key={c.handle} candidate={c} />
            ))}
          </div>
        ) : paper.discovered ? (
          <span className="text-[10px] text-muted-foreground italic">No tweets found</span>
        ) : (
          <span className="text-[10px] text-gray-400">—</span>
        )}
      </td>
    </tr>
  );
}

// ----------------------------------------------------------------------
// SHARED HELPERS & MOCK COMPONENTS
// ----------------------------------------------------------------------

function getEngagementColor(c) {
  const engaged = (c.tweet_likes > 0 || c.tweet_retweets > 0);
  return engaged ? "text-blue-600" : "text-muted-foreground";
}

function StatCounters({ candidate: c }) {
  if (!c.tweet_url) return null;
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-medium">
      <span className="flex items-center gap-0.5" title={`${c.tweet_likes || 0} Likes`}>
        <Heart className="h-2.5 w-2.5" /> {c.tweet_likes || 0}
      </span>
      <span className="flex items-center gap-0.5" title={`${c.tweet_retweets || 0} Retweets`}>
        <Repeat2 className="h-3 w-3" /> {c.tweet_retweets || 0}
      </span>
    </div>
  );
}

function ActionIcons({ candidate: c }) {
  if (!c.tweet_url) return null;
  const isLiked = c.liked;
  const isQT = c.quote_tweeted;
  
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <button 
        className={`h-6 w-6 rounded border flex items-center justify-center transition-colors
        ${isLiked ? 'border-pink-500 bg-pink-50 text-pink-600' : 'border-border text-muted-foreground hover:text-pink-600 hover:border-pink-200'}
        `}
        title={isLiked ? "Liked" : "Like"}
        onClick={() => console.log('Mock Like')}
        data-testid={`mock-like-${c.handle}`}
      >
        <Heart className={`h-3 w-3 ${isLiked ? 'fill-pink-500' : ''}`} />
      </button>

      <button 
        className={`h-6 w-6 rounded border flex items-center justify-center transition-colors
        ${isQT ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-border text-muted-foreground hover:text-blue-600 hover:border-blue-200'}
        `}
        title={isQT ? "Quote Tweeted" : "Quote Tweet (Not yet)"}
        onClick={() => console.log('Mock QT')}
        data-testid={`mock-qt-${c.handle}`}
      >
        <Twitter className={`h-3 w-3 ${isQT ? 'fill-blue-500' : ''}`} />
      </button>

      <button 
        className="h-6 w-6 rounded border border-border text-accent hover:bg-accent hover:text-background flex items-center justify-center transition-colors"
        title="Draft Quote"
        onClick={() => console.log('Mock Draft')}
        data-testid={`mock-draft-${c.handle}`}
      >
        <MessageSquare className="h-3 w-3" />
      </button>
    </div>
  );
}

// ----------------------------------------------------------------------
// VARIANTS
// ----------------------------------------------------------------------

function Variant1({ candidate: c }) {
  return (
    <div className="p-2.5 rounded-md border bg-background flex flex-col gap-1.5" data-testid={`v1-${c.handle}`}>
      {/* Top Row */}
      <div className="flex items-center justify-between">
        <a href={c.tweet_url || "#"} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] font-medium shrink-0 ${CONFIDENCE_COLORS[c.confidence]}`}>
          <Twitter className="h-2.5 w-2.5" />@{c.handle}
        </a>
        <StatCounters candidate={c} />
      </div>
      
      {/* Middle Row (Tweet) */}
      {c.tweet_text && (
        <a href={c.tweet_url || "#"} className={`text-[11px] leading-snug line-clamp-2 hover:underline ${getEngagementColor(c)}`} title={c.tweet_text}>
          {c.tweet_text}
        </a>
      )}

      {/* Bottom Row */}
      <div className="flex items-center justify-end mt-0.5">
        <ActionIcons candidate={c} />
      </div>
    </div>
  );
}

function Variant2({ candidate: c }) {
  return (
    <div className="flex gap-2 p-2 rounded hover:bg-muted/30 transition-colors border border-transparent hover:border-border" data-testid={`v2-${c.handle}`}>
      {/* Left: Handle */}
      <div className="shrink-0 pt-0.5">
        <a href={c.tweet_url || "#"} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${CONFIDENCE_COLORS[c.confidence]}`}>
          <Twitter className="h-2.5 w-2.5" />@{c.handle}
        </a>
      </div>
      
      {/* Right: Content */}
      <div className="flex-1 min-w-0 flex flex-col gap-1.5">
        {c.tweet_text && (
          <a href={c.tweet_url || "#"} className={`text-[11px] leading-snug line-clamp-2 hover:underline ${getEngagementColor(c)}`} title={c.tweet_text}>
            {c.tweet_text}
          </a>
        )}
        
        <div className="flex items-center justify-between mt-0.5">
          <StatCounters candidate={c} />
          <ActionIcons candidate={c} />
        </div>
      </div>
    </div>
  );
}

function Variant3({ candidate: c }) {
  return (
    <div className="p-2 border rounded-md bg-secondary/10" data-testid={`v3-${c.handle}`}>
      <div className="flex items-center gap-2 mb-1.5">
        <a href={c.tweet_url || "#"} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium shrink-0 ${CONFIDENCE_COLORS[c.confidence]}`}>
          <Twitter className="h-2.5 w-2.5" />@{c.handle}
        </a>
        <div className="h-3 w-px bg-border mx-1"></div>
        <StatCounters candidate={c} />
        <div className="ml-auto">
          <ActionIcons candidate={c} />
        </div>
      </div>
      
      {c.tweet_text && (
        <a href={c.tweet_url || "#"} className={`block text-[11px] leading-relaxed line-clamp-1 hover:underline ${getEngagementColor(c)}`} title={c.tweet_text}>
          {c.tweet_text}
        </a>
      )}
    </div>
  );
}

function Variant4({ candidate: c }) {
  // Extract just the color part from confidence to use as border
  const borderColorMap = {
    high: "border-green-500",
    medium: "border-amber-500",
    low: "border-gray-400"
  };
  const leftBorder = borderColorMap[c.confidence] || "border-gray-200";

  return (
    <div className={`pl-2.5 py-1.5 border-l-2 ${leftBorder}`} data-testid={`v4-${c.handle}`}>
      <div className="flex items-start gap-2 mb-1">
        <span className="font-semibold text-xs text-foreground shrink-0">@{c.handle}</span>
        {c.tweet_text && (
          <a href={c.tweet_url || "#"} className={`text-[11px] leading-snug line-clamp-2 hover:underline ${getEngagementColor(c)}`} title={c.tweet_text}>
            <Quote className="inline h-2 w-2 mr-0.5 -mt-1 text-muted-foreground/50" />
            {c.tweet_text}
          </a>
        )}
      </div>
      <div className="flex items-center gap-3">
        <StatCounters candidate={c} />
        <div className="ml-auto">
          <ActionIcons candidate={c} />
        </div>
      </div>
    </div>
  );
}
