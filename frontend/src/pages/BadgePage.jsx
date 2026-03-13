import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Trophy, ExternalLink, Share2, Copy, Check, Heart, LogIn, Mail, Loader2, Send, Edit3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

const API = process.env.REACT_APP_BACKEND_URL || "";

export default function BadgePage() {
  const { category, year, slug, paperId } = useParams();
  const { user, getAuthHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  // Congrats state
  const [remaining, setRemaining] = useState(null);
  const [showEmail, setShowEmail] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [toEmails, setToEmails] = useState("");
  const [emailSubject, setEmailSubject] = useState("");
  const [emailBody, setEmailBody] = useState("");

  useEffect(() => {
    axios.get(`${API}/api/badge/${category}/${year}/${slug}/${paperId}`)
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [category, year, slug, paperId]);

  // Fetch congrats remaining + gmail status
  useEffect(() => {
    if (!user) return;
    const headers = getAuthHeaders();
    axios.get(`${API}/api/congrats/remaining`, { withCredentials: true, headers })
      .then(res => setRemaining(res.data))
      .catch(() => {});
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

  const shareUrl = `${window.location.origin}/api/badge/${category}/${year}/${slug}/${paperId}/share`;
  const imageUrl = `${API}/api/badge/${category}/${year}/${slug}/${paperId}/image.png`;
  const arxivUrl = data.arxiv_id ? `https://arxiv.org/abs/${data.arxiv_id}` : "";
  const arxivSuffix = arxivUrl ? `\n${arxivUrl}` : "";
  const authorTweet = `Our paper "${data.title}" ranked #${data.rank} in ${data.category_name} Preprints (${data.archive_label}) on Kurate.org!${arxivSuffix}\n\n${shareUrl}`;
  const congratsTweet = `Congrats to ${data.authors?.slice(0, 2).join(" & ")}${data.authors?.length > 2 ? " et al." : ""} for ranking #${data.rank} in ${data.category_name} Preprints (${data.archive_label}) on Kurate.org!${arxivSuffix}\n\n${shareUrl}`;

  const copyLink = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const shareTwitter = (text) => {
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`, "_blank");
  };

  const shareLinkedIn = (text) => {
    if (text) {
      navigator.clipboard.writeText(text).then(() => {
        toast.success("Text copied — paste it in your LinkedIn post!");
      }).catch(() => {});
    }
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`, "_blank");
  };

  const recordCongrats = async (method) => {
    if (!user) return;
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

  const handleCongratsTwitter = () => {
    recordCongrats("twitter");
    shareTwitter(congratsTweet);
  };

  const handleCongratsLinkedIn = () => {
    recordCongrats("linkedin");
    const text = `Congrats to ${data.authors?.slice(0, 2).join(" & ")}${data.authors?.length > 2 ? " et al." : ""} for ranking #${data.rank} in ${data.category_name} Preprints (${data.archive_label}) on Kurate.org!`;
    shareLinkedIn(text);
  };

  // Email flow
  const startEmailFlow = async () => {
    setShowEmail(true);
    // Pre-fill template
    const arxivLine = arxivUrl ? `\narXiv: ${arxivUrl}` : "";
    setEmailSubject(`Congratulations on ranking #${data.rank} in ${data.category_name} (${data.archive_label})`);
    setEmailBody(
      `Hi,\n\n` +
      `Congratulations on your paper "${data.title}" ranking #${data.rank} in ${data.category_name} Preprints for ${data.archive_label} on Kurate.org!\n\n` +
      `This is a remarkable achievement. The ranking is based on AI-estimated scientific impact via pairwise tournament judging.\n\n` +
      `View and share your badge: ${shareUrl}${arxivLine}\n\n` +
      `Best regards`
    );
    // Try to extract emails
    if (!toEmails) {
      setExtracting(true);
      try {
        const res = await axios.post(`${API}/api/congrats/extract-emails`,
          { paper_id: paperId },
          { withCredentials: true, headers: getAuthHeaders() }
        );
        if (res.data.emails?.length) {
          setToEmails(res.data.emails.join(", "));
          toast.success(`Found ${res.data.emails.length} author email(s)`);
        } else {
          toast.info("No emails found in paper — please enter manually");
        }
      } catch { /* ignore */ }
      finally { setExtracting(false); }
    }
  };

  const openMailto = () => {
    const emails = toEmails.split(",").map(e => e.trim()).filter(e => e.includes("@"));
    if (!emails.length) { toast.error("Enter at least one email address"); return; }
    const mailto = `mailto:${emails.join(",")}?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent(emailBody)}`;
    window.open(mailto, "_blank");
    recordCongrats("email");
    setShowEmail(false);
    toast.success("Opening your email client...");
  };

  const truncTitle = data.title?.length > 70 ? data.title.slice(0, 67) + "..." : data.title;
  const canCongrats = remaining && remaining.remaining > 0;

  return (
    <>
      <Helmet>
        <title>{`#${data.rank} ${data.tier} — ${data.title} | Kurate.org`}</title>
        <meta property="og:title" content={`#${data.rank} ${data.tier} in ${data.category_name} Preprints — ${data.archive_label}`} />
        <meta property="og:description" content={`${data.title} | AI-ranked by scientific impact | Kurate.org`} />
        <meta property="og:image" content={`${window.location.origin}${data.image_url}`} />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:type" content="article" />
        <meta name="twitter:card" content="summary_large_image" />
      </Helmet>

      <div className="container mx-auto px-4 max-w-3xl py-8 md:py-12">
        {/* Badge preview */}
        <div className="rounded-xl border border-border overflow-hidden mb-8 bg-white" data-testid="badge-preview">
          <img src={imageUrl} alt="Badge" className="w-full" loading="lazy" />
          <div className="px-4 py-3 bg-secondary/20 border-t border-border flex items-center justify-between">
            <div>
              <div className="text-xs font-medium">#{data.rank} {data.tier} in {data.category_name} Preprints — {data.archive_label}</div>
              <div className="text-[10px] text-muted-foreground truncate max-w-md">{data.title}</div>
            </div>
            {data.arxiv_id && (
              <a href={`https://arxiv.org/abs/${data.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0">
                arXiv <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>

        {/* Section 1: Share your achievement (for authors) */}
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
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => shareTwitter(authorTweet)} data-testid="author-share-x">
              <Share2 className="h-3.5 w-3.5" /> Share on X
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => shareLinkedIn(authorTweet)} data-testid="author-share-linkedin">
              <Share2 className="h-3.5 w-3.5" /> Share on LinkedIn
            </Button>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-border my-8" />

        {/* Section 2: Congratulate the authors (for peers) */}
        <div data-testid="congrats-section">
          <div className="flex items-center gap-2 mb-1">
            <Heart className="h-4 w-4 text-rose-500" />
            <h2 className="font-heading text-base font-semibold">Congratulate the authors</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-4">
            Know the authors? Send them a congratulation.
            {remaining && <span className="ml-1 text-muted-foreground/70">({remaining.remaining}/{remaining.limit} remaining this week)</span>}
          </p>

          {!user ? (
            <div className="p-4 bg-secondary/30 rounded-lg border border-border text-center" data-testid="sign-in-cta">
              <LogIn className="h-5 w-5 mx-auto mb-2 text-muted-foreground opacity-50" />
              <p className="text-sm text-muted-foreground mb-3">Sign in to congratulate authors</p>
              <Button size="sm" className="gap-1.5" onClick={() => window.dispatchEvent(new CustomEvent("open-auth-modal"))} data-testid="congrats-sign-in-btn">
                <LogIn className="h-3.5 w-3.5" /> Sign in
              </Button>
            </div>
          ) : !canCongrats && remaining ? (
            <div className="p-4 bg-secondary/30 rounded-lg border border-border text-center text-sm text-muted-foreground">
              You've used all {remaining.limit} congratulations this week. Check back later!
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="congrats-buttons">
                <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={handleCongratsTwitter} data-testid="congrats-x-btn">
                  <Share2 className="h-3.5 w-3.5" /> Congrats on X
                </Button>
                <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={handleCongratsLinkedIn} data-testid="congrats-linkedin-btn">
                  <Share2 className="h-3.5 w-3.5" /> Congrats on LinkedIn
                </Button>
                <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={startEmailFlow} data-testid="congrats-email-btn">
                  <Mail className="h-3.5 w-3.5" /> Send email
                </Button>
              </div>

              {/* Email flow */}
              {showEmail && (
                <div className="p-4 border border-border rounded-lg bg-background space-y-3" data-testid="email-flow">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground block mb-1">To (comma-separated)</label>
                    <div className="flex gap-2">
                      <Input
                        value={toEmails} onChange={e => setToEmails(e.target.value)}
                        placeholder={extracting ? "Extracting emails from paper..." : "author@university.edu"}
                        disabled={extracting}
                        className="text-sm" data-testid="email-to-input"
                      />
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
                    <Textarea
                      value={emailBody}
                      onChange={e => setEmailBody(e.target.value)}
                      rows={6} className="text-sm" data-testid="email-body-input"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <Button size="sm" className="gap-1.5" onClick={openMailto} data-testid="send-email-btn">
                      <Send className="h-3.5 w-3.5" /> Open in email client
                    </Button>
                    <Button size="sm" variant="ghost" className="text-xs" onClick={() => setShowEmail(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer links */}
        <div className="text-center text-sm text-muted-foreground mt-10 pt-6 border-t border-border">
          <a href={`/paper/${data.paper_id}`} className="text-accent hover:underline">View full paper details</a>
          <span className="mx-2">·</span>
          <a href="/" className="text-accent hover:underline">Explore the leaderboard</a>
        </div>
      </div>
    </>
  );
}
