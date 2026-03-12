import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Trophy, ExternalLink, Share2, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

const TIER_STYLES = {
  Gold:   { bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-700", emoji: "1st" },
  Silver: { bg: "bg-gray-50",  border: "border-gray-300",  text: "text-gray-600",  emoji: "2nd" },
  Bronze: { bg: "bg-orange-50", border: "border-orange-300", text: "text-orange-700", emoji: "3rd" },
};

export default function BadgePage() {
  const { category, year, slug, paperId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const fetchBadge = async () => {
      try {
        const res = await axios.get(`${API}/api/badge/${category}/${year}/${slug}/${paperId}`);
        setData(res.data);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    fetchBadge();
  }, [category, year, slug, paperId]);

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
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">View Leaderboard</Link>
      </div>
    );
  }

  const style = TIER_STYLES[data.tier] || TIER_STYLES.Gold;
  const badgeUrl = window.location.href;
  const imageUrl = `${API}${data.image_url}`;
  const tweetText = `Our paper "${data.title}" ranked #${data.rank} in ${data.category_name} (${data.archive_label}) on @KurateAI!\n\n${badgeUrl}`;

  const copyLink = () => {
    navigator.clipboard.writeText(badgeUrl);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const shareTwitter = () => {
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(tweetText)}`, "_blank");
  };

  const shareLinkedIn = () => {
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(badgeUrl)}`, "_blank");
  };

  return (
    <>
      <Helmet>
        <title>{`#${data.rank} ${data.tier} — ${data.title} | PaperSumo`}</title>
        <meta property="og:title" content={`#${data.rank} ${data.tier} in ${data.category_name} — ${data.archive_label}`} />
        <meta property="og:description" content={`${data.title} by ${data.authors?.slice(0, 3).join(", ")}${data.authors?.length > 3 ? " et al." : ""}`} />
        <meta property="og:image" content={imageUrl} />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:type" content="article" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={`#${data.rank} ${data.tier} in ${data.category_name}`} />
        <meta name="twitter:description" content={data.title} />
        <meta name="twitter:image" content={imageUrl} />
      </Helmet>

      <div className="container mx-auto px-4 max-w-3xl py-8 md:py-12">
        {/* Badge Card */}
        <div className={`rounded-xl border-2 ${style.border} ${style.bg} p-6 md:p-8 mb-6`} data-testid="badge-card">
          <div className="flex items-start gap-4 mb-6">
            <div className={`w-16 h-16 md:w-20 md:h-20 rounded-full flex items-center justify-center text-white font-bold text-2xl md:text-3xl shrink-0`}
              style={{ backgroundColor: data.tier_color }}>
              #{data.rank}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-sm font-bold uppercase tracking-wide ${style.text}`}>{data.tier}</span>
                <span className="text-sm text-muted-foreground">{data.category_name}</span>
              </div>
              <h1 className="font-heading text-lg md:text-xl font-semibold leading-tight" data-testid="badge-title">
                {data.title}
              </h1>
              <p className="text-sm text-muted-foreground mt-1.5">
                {data.authors?.slice(0, 5).join(", ")}
                {data.authors?.length > 5 && ` +${data.authors.length - 5}`}
              </p>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <div className="text-center p-3 bg-white/60 rounded-lg">
              <div className="font-mono text-xl font-bold">{data.score}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">Elo Score</div>
            </div>
            <div className="text-center p-3 bg-white/60 rounded-lg">
              <div className="font-mono text-xl font-bold">{data.win_rate}%</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">Win Rate</div>
            </div>
            <div className="text-center p-3 bg-white/60 rounded-lg">
              <div className="font-mono text-xl font-bold">{data.comparisons}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">Matches</div>
            </div>
            <div className="text-center p-3 bg-white/60 rounded-lg">
              <div className="font-mono text-xl font-bold">of {data.paper_count}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">Papers</div>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            {data.archive_label} · Ranked by AI pairwise tournament
          </div>
        </div>

        {/* Share section */}
        <div className="flex flex-wrap items-center gap-2 mb-8" data-testid="share-section">
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={copyLink} data-testid="copy-link-btn">
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied!" : "Copy Link"}
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={shareTwitter} data-testid="share-twitter-btn">
            <Share2 className="h-3.5 w-3.5" />
            Share on X
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={shareLinkedIn} data-testid="share-linkedin-btn">
            <Share2 className="h-3.5 w-3.5" />
            Share on LinkedIn
          </Button>
          {data.arxiv_id && (
            <a href={`https://arxiv.org/abs/${data.arxiv_id}`} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline ml-auto">
              arXiv:{data.arxiv_id} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        {/* OG Image preview */}
        <div className="rounded-lg overflow-hidden border border-border mb-6" data-testid="badge-image-preview">
          <img src={imageUrl} alt={`Badge for ${data.title}`} className="w-full" loading="lazy" />
        </div>

        {/* CTA */}
        <div className="text-center text-sm text-muted-foreground">
          <Link to={`/paper/${data.paper_id}`} className="text-accent hover:underline">View full paper details</Link>
          <span className="mx-2">·</span>
          <Link to="/" className="text-accent hover:underline">Explore the leaderboard</Link>
        </div>
      </div>
    </>
  );
}
