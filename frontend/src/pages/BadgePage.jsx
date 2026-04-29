import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Trophy, ExternalLink, Share2, Copy, Check, Heart, LogIn, Mail, Loader2, Send, Edit3, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

const API = process.env.REACT_APP_BACKEND_URL || "";
const ORIGIN = typeof window !== "undefined" ? window.location.origin : "";

/**
 * Normalize the two different API response shapes into one uniform object.
 * - Period-specific: /api/badge/{cat}/{year}/{slug}/{paperId}  → flat fields
 * - Universal share: /api/badge/paper/{paperId}/share          → badge nested
 */
function normalizeBadgeData(raw, { category, year, slug, paperId, isShareMode }) {
  const badge = raw.badge || {};
  return {
    title: raw.title,
    authors: raw.authors || [],
    arxiv_id: raw.arxiv_id,
    paper_id: raw.paper_id || paperId,
    category: raw.category || category,
    category_name: raw.category_name,
    // Badge-specific (archive) rank and tier — the one that matters for sharing
    rank: badge.rank || raw.rank,
    tier: badge.tier || raw.tier,
    archive_label: badge.archive_label || raw.archive_label,
    paper_count: badge.paper_count || raw.paper_count,
    // All-time rank for the footer subtitle
    alltime_rank: raw.rank,
    total_in_category: raw.total_in_category,
    // Display helpers
    has_medal: !!(raw.has_medal || (raw.tier && (raw.display_rank || raw.rank) <= 3)),
    display_rank: raw.display_rank || badge.rank || raw.rank,
    // URLs
    image_url: isShareMode
      ? (raw.image_url ? `${API}${raw.image_url}` : null)
      : `${API}/api/badge/${category}/${year}/${slug}/${paperId}/image.png`,
    share_url: badge.badge_url
      ? `${ORIGIN}/api${badge.badge_url}/share`
      : isShareMode
        ? `${ORIGIN}/api/badge/paper/${paperId}/share/page`
        : `${ORIGIN}/api/badge/${category}/${year}/${slug}/${paperId}/share`,
    leaderboard_url: isShareMode
      ? (badge.leaderboard_url || `/?cat=${raw.category}&period=all`)
      : `/leaderboard/${category}/${year}/${slug}`,
    alltime_leaderboard_url: `/?cat=${raw.category || category}&period=all`,
  };
}

function buildShareText(d, variant = "author") {
  const tierLabel = d.tier ? `${d.tier} ` : "";
  const periodLabel = d.archive_label ? ` (${d.archive_label})` : "";
  // Don't include arXiv URL or "Kurate.org" (with dot) in tweet text —
  // Twitter auto-links bare domains and picks one to unfurl.
  // The badge share URL (passed via ?url= param) should be the only link.
  if (variant === "congrats") {
    const names = d.authors.slice(0, 2).join(" & ") + (d.authors.length > 2 ? " et al." : "");
    return `Congrats to ${names} for ranking #${d.rank} ${tierLabel}in ${d.category_name} Preprints${periodLabel} on @kurateorg!`;
  }
  return `Our paper "${d.title}" ranked #${d.rank} ${tierLabel}in ${d.category_name} Preprints${periodLabel} on @kurateorg!`;
}

function openTwitter(text, url) {
  window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`, "_blank");
}

function openLinkedIn(text, url) {
  if (text) navigator.clipboard.writeText(text).then(() => toast.success("Text copied — paste it in your LinkedIn post!")).catch(() => {});
  window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`, "_blank");
}

export default function BadgePage() {
  const { category, year, slug, paperId } = useParams();
  const isShareMode = !category && !year && !slug;
  const { user, getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [remaining, setRemaining] = useState(null);
  const [showEmail, setShowEmail] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [toEmails, setToEmails] = useState("");
  const [emailSubject, setEmailSubject] = useState("");
  const [emailBody, setEmailBody] = useState("");

  useEffect(() => {
    const url = isShareMode
      ? `${API}/api/badge/paper/${paperId}/share`
      : `${API}/api/badge/${category}/${year}/${slug}/${paperId}`;
    axios.get(url)
      .then(res => setData(normalizeBadgeData(res.data, { category, year, slug, paperId, isShareMode })))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [category, year, slug, paperId, isShareMode]);

  useEffect(() => {
    if (!user) return;
    axios.get(`${API}/api/congrats/remaining`, { withCredentials: true, headers: getAuthHeaders() })
      .then(res => setRemaining(res.data)).catch(() => {});
  }, [user, getAuthHeaders]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center">
        <div className="h-8 w-48 bg-secondary/50 rounded animate-pulse mx-auto" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="container mx-auto px-4 max-w-3xl py-20 text-center text-muted-foreground">
        <Trophy className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Badge not found. Only the top 3 papers per category per week earn badges.</p>
        <a href="/" className="text-accent text-sm hover:underline mt-4 inline-block">View Leaderboard</a>
      </div>
    );
  }

  // All share text uses the normalized badge rank (not all-time)
  const authorText = buildShareText(data, "author");
  const congratsText = buildShareText(data, "congrats");

  const copyLink = () => {
    const url = data.leaderboard_url.startsWith("http") ? data.leaderboard_url : `${ORIGIN}${data.leaderboard_url}`;
    navigator.clipboard.writeText(url);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const recordCongrats = async (method) => {
    if (!user || isShareMode) return;
    try {
      const res = await axios.post(`${API}/api/congrats/send`, {
        paper_id: paperId, badge_category: category,
        badge_year: parseInt(year), badge_slug: slug, method,
      }, { withCredentials: true, headers: getAuthHeaders() });
      setRemaining(r => r ? { ...r, remaining: res.data.remaining, used: r.used + 1 } : r);
    } catch (err) {
      if (err.response?.status === 429) toast.error("Weekly congrats limit reached");
    }
  };

  const startEmailFlow = async () => {
    setShowEmail(true);
    const arxivLine = data.arxiv_id ? `\narXiv: https://arxiv.org/abs/${data.arxiv_id}` : "";
    setEmailSubject(`Congratulations on ranking #${data.rank} in ${data.category_name} (${data.archive_label || ""})`);
    setEmailBody(
      `Hi,\n\nCongratulations on your paper "${data.title}" ranking #${data.rank} in ${data.category_name} Preprints for ${data.archive_label || ""} on Kurate.org!\n\n` +
      `This is a remarkable achievement. The ranking is based on AI-estimated scientific impact via pairwise tournament judging. Learn more about the methodology: https://kurate.org/methodology\n\n` +
      `Your badge: ${ORIGIN}/badge/${category}/${year}/${slug}/${paperId}\n\nBest regards`
    );
    if (!toEmails) {
      setExtracting(true);
      try {
        const res = await axios.post(`${API}/api/congrats/extract-emails`, { paper_id: paperId },
          { withCredentials: true, headers: getAuthHeaders() });
        if (res.data.emails?.length) { setToEmails(res.data.emails.join(", ")); toast.success(`Found ${res.data.emails.length} author email(s)`); }
        else toast.info("No emails found in paper — please enter manually");
      } catch { /* ignore */ }
      finally { setExtracting(false); }
    }
  };

  const openMailto = () => {
    const emails = toEmails.split(",").map(e => e.trim()).filter(e => e.includes("@"));
    if (!emails.length) { toast.error("Enter at least one email address"); return; }
    window.open(`mailto:${emails.join(",")}?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(emailBody)}`, "_blank");
    recordCongrats("email");
    setShowEmail(false);
  };

  const openGmail = () => {
    const emails = toEmails.split(",").map(e => e.trim()).filter(e => e.includes("@"));
    if (!emails.length) { toast.error("Enter at least one email address"); return; }
    window.open(`https://mail.google.com/mail/?view=cm&to=${encodeURIComponent(emails.join(","))}&su=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(emailBody)}`, "_blank");
    recordCongrats("email");
    setShowEmail(false);
  };

  const truncTitle = data.title?.length > 70 ? data.title.slice(0, 67) + "..." : data.title;
  const pageTitle = data.has_medal
    ? `#${data.display_rank} ${data.tier} — ${data.title} | Kurate.org`
    : `#${data.alltime_rank} in ${data.category_name} — ${data.title} | Kurate.org`;
  const ogTitle = data.has_medal
    ? `#${data.display_rank} ${data.tier} in ${data.category_name} Preprints — ${data.archive_label || ""}`
    : `#${data.alltime_rank} of ${data.total_in_category} in ${data.category_name} — Kurate.org`;
  const subtitleText = `#${data.alltime_rank} of ${data.total_in_category || "—"} in ${data.category_name} (All Time)`;

  return (
    <>
      <Helmet>
        <title>{pageTitle}</title>
        <meta property="og:title" content={ogTitle} />
        <meta property="og:description" content={`${data.title} | AI-ranked by scientific impact | Kurate.org`} />
        <meta property="og:image" content={`${ORIGIN}${data.image_url}`} />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:type" content="article" />
        <meta name="twitter:card" content="summary_large_image" />
      </Helmet>

      <div className="container mx-auto px-4 max-w-3xl py-8 md:py-12">
        {/* Badge preview */}
        <div className="rounded-xl border border-border overflow-hidden mb-8 bg-white" data-testid="badge-preview">
          <div className="relative min-h-[120px]">
            <img src={data.image_url} alt="Badge" className="w-full" loading="eager"
              onLoad={e => e.target.parentElement.querySelector('[data-loader]')?.remove()}
              onError={e => { const loader = e.target.parentElement.querySelector('[data-loader]'); if (loader) loader.querySelector('span').textContent = 'Badge image unavailable'; }}
            />
            <div data-loader className="absolute inset-0 flex items-center justify-center bg-secondary/20 rounded-t-xl">
              <span className="text-sm text-muted-foreground animate-pulse">Generating badge image...</span>
            </div>
          </div>
          <div className="px-4 py-3 bg-secondary/20 border-t border-border flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs font-medium">{subtitleText}</div>
              <div className="text-[10px] text-muted-foreground">{data.title}</div>
            </div>
            {data.arxiv_id && (
              <a href={`https://arxiv.org/abs/${data.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0">
                arXiv <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>

        {/* Navigation links */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-accent mb-8">
          <a href={`/paper/${data.paper_id}`} className="hover:underline">Paper details</a>
          {data.leaderboard_url && data.leaderboard_url !== data.alltime_leaderboard_url && (
            <>
              <span className="text-border">·</span>
              <a href={data.leaderboard_url} className="hover:underline">{data.archive_label || "Archive"} leaderboard</a>
            </>
          )}
          <span className="text-border">·</span>
          <a href={data.alltime_leaderboard_url} className="hover:underline">All Time leaderboard</a>
        </div>

        {/* Share your achievement (for authors) */}
        <div className="mb-10" data-testid="author-section">
          <div className="flex items-center gap-2 mb-1">
            <Trophy className="h-4 w-4 text-amber-500" />
            <h2 className="font-heading text-base font-semibold">Share your achievement</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-4">Are you one of the authors? Share this badge on social media.</p>
          <div className="flex flex-wrap items-center gap-2" data-testid="author-share-buttons">
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={copyLink} data-testid="copy-link-btn">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied!" : "Copy link"}
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => openTwitter(authorText, data.share_url)} data-testid="author-share-x">
              <Share2 className="h-3.5 w-3.5" /> Share on X
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => openLinkedIn(authorText, data.share_url)} data-testid="author-share-linkedin">
              <Share2 className="h-3.5 w-3.5" /> Share on LinkedIn
            </Button>
            <a href={data.image_url} download={`kurate-badge-${data.tier?.toLowerCase()}.png`}
              className="inline-flex items-center gap-1.5 text-xs px-3 h-8 rounded-md border border-input bg-background hover:bg-secondary/50 transition-colors font-medium" data-testid="download-badge-img">
              <Download className="h-3.5 w-3.5" /> Download image
            </a>
          </div>
        </div>

        <div className="border-t border-border my-8" />

        {/* Congratulate the authors (for peers) */}
        <div data-testid="congrats-section">
          <div className="flex items-center gap-2 mb-1">
            <Heart className="h-4 w-4 text-rose-500" />
            <h2 className="font-heading text-base font-semibold">Congratulate the authors</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-4">
            Know the authors? Send them a congratulation.
            {remaining && <span className="ml-1 text-muted-foreground/70">({remaining.remaining}/{remaining.limit} remaining this week)</span>}
          </p>

          <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="congrats-buttons">
            <Button size="sm" variant="outline" className="gap-1.5 text-xs"
              onClick={() => { recordCongrats("twitter"); openTwitter(congratsText, data.share_url); }} data-testid="congrats-x-btn">
              <Share2 className="h-3.5 w-3.5" /> Congrats on X
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs"
              onClick={() => { recordCongrats("linkedin"); openLinkedIn(congratsText, data.share_url); }} data-testid="congrats-linkedin-btn">
              <Share2 className="h-3.5 w-3.5" /> Congrats on LinkedIn
            </Button>
            {user ? (
              <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={startEmailFlow}
                disabled={remaining && remaining.remaining <= 0} data-testid="congrats-email-btn">
                <Mail className="h-3.5 w-3.5" /> Send email
              </Button>
            ) : (
              <Button size="sm" variant="outline" className="gap-1.5 text-xs"
                onClick={() => window.dispatchEvent(new CustomEvent("open-auth-modal"))} data-testid="congrats-email-signin-btn">
                <LogIn className="h-3.5 w-3.5" /> Sign in to email
              </Button>
            )}
          </div>

          {user && remaining && remaining.remaining <= 0 && (
            <div className="p-3 bg-secondary/30 rounded-lg border border-border text-center text-xs text-muted-foreground mb-4">
              You've used all {remaining.limit} email congratulations this week. Social sharing is unlimited!
            </div>
          )}

          {showEmail && user && (
            <div className="p-4 border border-border rounded-lg bg-background space-y-3" data-testid="email-flow">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">To (comma-separated)</label>
                <div className="flex gap-2">
                  <Input value={toEmails} onChange={e => setToEmails(e.target.value)}
                    placeholder={extracting ? "Extracting emails from paper..." : "author@university.edu"}
                    disabled={extracting} className="text-sm" data-testid="email-to-input" />
                  {extracting && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mt-2" />}
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">Subject</label>
                <Input value={emailSubject} onChange={e => setEmailSubject(e.target.value)} className="text-sm" data-testid="email-subject-input" />
              </div>
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <label className="text-xs font-medium text-muted-foreground">Message</label>
                  <Edit3 className="h-3 w-3 text-muted-foreground" />
                  <span className="text-[10px] text-muted-foreground">edit before sending</span>
                </div>
                <Textarea value={emailBody} onChange={e => setEmailBody(e.target.value)}
                  rows={12} className="text-sm" data-testid="email-body-input" />
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" className="gap-1.5" onClick={openGmail} data-testid="send-gmail-btn">
                  <Send className="h-3.5 w-3.5" /> Open in Gmail
                </Button>
                <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={openMailto} data-testid="send-email-btn">
                  <Mail className="h-3.5 w-3.5" /> Other email client
                </Button>
                <Button size="sm" variant="ghost" className="text-xs" onClick={() => setShowEmail(false)}>Cancel</Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
