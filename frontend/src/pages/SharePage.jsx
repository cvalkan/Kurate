import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { Trophy, Award, Share2, ArrowLeft, ExternalLink, Copy, Check } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const TIER_COLORS = {
  Gold: { color: "#D4A012", bg: "#FEFCE8", border: "#D4A012" },
  Silver: { color: "#6B7280", bg: "#F3F4F6", border: "#9CA3AF" },
  Bronze: { color: "#CD7F32", bg: "#FFF7ED", border: "#CD7F32" },
};

export default function SharePage() {
  const { paperId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    axios.get(`${API}/api/share/${paperId}`).then(res => setData(res.data)).catch(() => {}).finally(() => setLoading(false));
  }, [paperId]);

  if (loading) return <div className="flex items-center justify-center min-h-screen"><div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-slate-600 rounded-full" /></div>;
  if (!data) return <div className="text-center py-20 text-slate-500">Paper not found</div>;

  const tier = data.tier ? TIER_COLORS[data.tier] : null;
  const pageUrl = window.location.href.replace("/share/", "/paper/");
  const shareUrl = window.location.href;

  const handleCopy = () => {
    navigator.clipboard?.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const tweetText = `${data.title} — ranked #${data.rank} in ${data.category_name} on kurate.org`;
  const twitterUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweetText)}&url=${encodeURIComponent(shareUrl)}`;
  const linkedinUrl = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`;

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="max-w-lg mx-auto">
        <Link to={`/paper/${paperId}`} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-6">
          <ArrowLeft className="h-4 w-4" /> Back to paper
        </Link>

        {/* Share Card */}
        <div className="rounded-2xl overflow-hidden shadow-xl border border-slate-200 bg-white" data-testid="share-card">
          {/* Header */}
          {tier ? (
            <div className="px-6 py-4 flex items-center justify-between" style={{ backgroundColor: tier.bg }}>
              <div className="flex items-center gap-2">
                <Award className="h-5 w-5" style={{ color: tier.color }} />
                <span className="text-lg font-bold" style={{ color: tier.color }}>{data.tier} #{data.rank}</span>
              </div>
              <span className="text-xs font-medium text-slate-500">{data.archive_label}</span>
            </div>
          ) : (
            <div className="px-6 py-4 flex items-center justify-between bg-slate-100">
              <div className="flex items-center gap-2">
                <Trophy className="h-5 w-5 text-slate-500" />
                <span className="text-lg font-bold text-slate-700">#{data.rank}</span>
                <span className="text-sm text-slate-400">of {data.total_in_category}</span>
              </div>
            </div>
          )}

          {/* Body */}
          <div className="px-6 py-5">
            <h2 className="text-lg font-semibold text-slate-900 leading-snug mb-2">{data.title}</h2>
            <p className="text-xs text-slate-500 mb-4">{(data.authors || []).slice(0, 3).join(", ")}{data.authors?.length > 3 ? " et al." : ""}</p>

            <div className="flex items-center gap-4 mb-4">
              <div>
                <div className="text-2xl font-bold text-slate-900">{data.score}</div>
                <div className="text-[10px] text-slate-500">Score{data.ci ? ` ±${data.ci}` : ""}</div>
              </div>
              <div className="h-8 w-px bg-slate-200" />
              <div>
                <div className="text-2xl font-bold text-slate-900">{data.win_rate}%</div>
                <div className="text-[10px] text-slate-500">Win Rate</div>
              </div>
              <div className="h-8 w-px bg-slate-200" />
              <div>
                <div className="text-2xl font-bold text-slate-900">{data.comparisons}</div>
                <div className="text-[10px] text-slate-500">Matches</div>
              </div>
              {data.rating && (
                <>
                  <div className="h-8 w-px bg-slate-200" />
                  <div>
                    <div className="text-2xl font-bold text-slate-700">{data.rating}/10</div>
                    <div className="text-[10px] text-slate-500">AI Rating</div>
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span className="px-2 py-0.5 rounded border border-slate-200 bg-slate-50">{data.category_name}</span>
              <span>kurate.org</span>
            </div>
          </div>
        </div>

        {/* Share Actions */}
        <div className="mt-6 space-y-3">
          <button onClick={handleCopy} className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors" data-testid="copy-link-button">
            {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied!" : "Copy link"}
          </button>
          <div className="grid grid-cols-2 gap-3">
            <a href={twitterUrl} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center gap-2 py-3 px-4 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">
              <ExternalLink className="h-4 w-4" /> Post on X
            </a>
            <a href={linkedinUrl} target="_blank" rel="noopener noreferrer" className="flex items-center justify-center gap-2 py-3 px-4 rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">
              <ExternalLink className="h-4 w-4" /> Share on LinkedIn
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
