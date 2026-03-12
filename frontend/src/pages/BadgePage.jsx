import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet";
import axios from "axios";
import { Trophy, ExternalLink, Share2, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

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

  const shareUrl = `${API}/api/badge/${category}/${year}/${slug}/${paperId}/share`;
  const imageUrl = `${API}${data.image_url}`;
  const tweetText = `Our paper "${data.title}" ranked #${data.rank} in ${data.category_name} Preprints (${data.archive_label}) on @KurateAI!\n\n${shareUrl}`;

  const copyLink = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    toast.success("Link copied!");
    setTimeout(() => setCopied(false), 2000);
  };

  const shareTwitter = () => {
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(tweetText)}`, "_blank");
  };

  const shareLinkedIn = () => {
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`, "_blank");
  };

  const truncTitle = data.title?.length > 70 ? data.title.slice(0, 67) + "..." : data.title;
  const authors3 = data.authors?.slice(0, 3).join(", ") + (data.authors?.length > 3 ? ` +${data.authors.length - 3}` : "");

  return (
    <>
      <Helmet>
        <title>{`#${data.rank} ${data.tier} — ${data.title} | Kurate.org`}</title>
        <meta property="og:title" content={`#${data.rank} ${data.tier} in ${data.category_name} Preprints — ${data.archive_label}`} />
        <meta property="og:description" content={`${data.title} | AI-ranked by scientific impact | Kurate.org`} />
        <meta property="og:image" content={imageUrl} />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:type" content="article" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={`#${data.rank} ${data.tier} in ${data.category_name} Preprints`} />
        <meta name="twitter:description" content={data.title} />
        <meta name="twitter:image" content={imageUrl} />
      </Helmet>

      <div className="container mx-auto px-4 max-w-3xl py-8 md:py-12">
        <h2 className="font-heading text-lg font-semibold mb-1">Share your badge</h2>
        <p className="text-sm text-muted-foreground mb-6">Preview how it looks on social platforms</p>

        {/* Share buttons */}
        <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="share-section">
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

        {/* X (Twitter) Preview */}
        <div className="mb-6" data-testid="x-preview">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium mb-2">X / Twitter Preview</div>
          <div className="border border-border rounded-xl overflow-hidden bg-white max-w-lg">
            {/* Tweet content */}
            <div className="p-3 pb-2">
              <div className="flex items-center gap-2 mb-1.5">
                <div className="w-8 h-8 rounded-full bg-secondary" />
                <div>
                  <span className="text-sm font-bold">Author Name</span>
                  <span className="text-xs text-muted-foreground ml-1">@author</span>
                </div>
              </div>
              <p className="text-sm leading-snug">Our paper "{truncTitle}" ranked #{data.rank} in {data.category_name} Preprints ({data.archive_label}) on <span className="text-accent">@KurateAI</span>!</p>
            </div>
            {/* Card preview */}
            <div className="mx-3 mb-3 border border-border rounded-lg overflow-hidden">
              <img src={imageUrl} alt="Badge" className="w-full" loading="lazy" />
              <div className="px-3 py-2 bg-gray-50">
                <div className="text-[10px] text-muted-foreground">kurate.org</div>
                <div className="text-xs font-medium truncate">#{data.rank} {data.tier} in {data.category_name} Preprints — {data.archive_label}</div>
                <div className="text-[10px] text-muted-foreground truncate">{data.title}</div>
              </div>
            </div>
          </div>
        </div>

        {/* LinkedIn Preview */}
        <div className="mb-8" data-testid="linkedin-preview">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium mb-2">LinkedIn Preview</div>
          <div className="border border-border rounded-lg overflow-hidden bg-white max-w-lg">
            {/* Post header */}
            <div className="p-3 pb-2">
              <div className="flex items-center gap-2 mb-1.5">
                <div className="w-10 h-10 rounded-full bg-secondary" />
                <div>
                  <div className="text-sm font-bold">Author Name</div>
                  <div className="text-[10px] text-muted-foreground">Researcher · 1h</div>
                </div>
              </div>
              <p className="text-sm leading-snug">Excited to share: our paper ranked #{data.rank} in {data.category_name} Preprints for {data.archive_label} on Kurate.org!</p>
            </div>
            {/* Card */}
            <img src={imageUrl} alt="Badge" className="w-full" loading="lazy" />
            <div className="px-3 py-2 bg-gray-50 border-t border-border">
              <div className="text-[10px] text-muted-foreground">kurate.org</div>
              <div className="text-xs font-medium">#{data.rank} {data.tier} in {data.category_name} Preprints — {data.archive_label}</div>
            </div>
          </div>
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
