import { useState, useEffect } from "react";
import axios from "axios";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Loader2, ShieldCheck, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

function OrcidIcon({ className }) {
  return (
    <svg viewBox="0 0 256 256" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M128 0C57.3 0 0 57.3 0 128s57.3 128 128 128 128-57.3 128-128S198.7 0 128 0z" fill="#A6CE39" />
      <path d="M86.3 186.2H70.9V79.1h15.4v107.1zM108.9 79.1h41.6c39.6 0 57 28.3 57 53.6 0 27.5-21.5 53.6-56.8 53.6h-41.8V79.1zm15.4 93.3h24.5c34.9 0 42.9-26.5 42.9-39.7 0-21.5-13.7-39.7-43.7-39.7h-23.7v79.4zM86.3 74.4c0 5.4-4.4 9.8-9.8 9.8-5.4 0-9.8-4.4-9.8-9.8s4.4-9.8 9.8-9.8c5.4 0 9.8 4.4 9.8 9.8z" fill="#fff" />
    </svg>
  );
}

export function AuthorClaimSection({ paperId, paperAuthors, claims = [] }) {
  const { user, getAuthHeaders, checkAuth } = useAuth();
  const [claiming, setClaiming] = useState(false);
  const [claimResult, setClaimResult] = useState(null);

  const verifiedClaims = claims.filter(c => c.verified);
  const pendingClaims = claims.filter(c => !c.verified);
  const userClaim = user?.orcid_id
    ? claims.find(c => c.orcid_id === user.orcid_id)
    : null;

  // Derive ORCID status directly from user context — no extra API call needed
  const orcidLinked = !!user?.orcid_id;

  const connectOrcid = async () => {
    try {
      const redirectUri = `${window.location.origin}/auth/orcid/callback`;
      const res = await axios.get(`${API}/api/claim/orcid/auth-url`, {
        params: { redirect_uri: redirectUri },
        withCredentials: true, headers: getAuthHeaders(),
      });
      sessionStorage.setItem("orcid_return_to", window.location.pathname);
      window.location.href = res.data.url;
    } catch (err) {
      if (err.response?.status === 503) {
        toast.error("ORCID integration is not yet configured.");
      } else {
        toast.error("Failed to start ORCID connection");
      }
    }
  };

  const claimPaper = async () => {
    setClaiming(true);
    try {
      const res = await axios.post(
        `${API}/api/claim/${paperId}`, {},
        { withCredentials: true, headers: getAuthHeaders() }
      );
      setClaimResult(res.data);
      if (res.data.status === "verified") {
        toast.success(`Verified as author via ${res.data.method.replace(/_/g, " ")}`);
      } else if (res.data.status === "already_claimed") {
        toast.info("You've already claimed this paper");
      } else {
        toast.info("Claim submitted for admin review");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to claim paper");
    } finally {
      setClaiming(false);
    }
  };

  return (
    <div className="mb-8" data-testid="author-claim-section">
      {/* Verified author badges */}
      {verifiedClaims.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="verified-badges">
          {verifiedClaims.map((c, i) => (
            <a
              key={i}
              href={`https://orcid.org/${c.orcid_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 border border-green-200 text-green-800 text-xs hover:bg-green-100 transition-colors"
              data-testid={`verified-badge-${i}`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              <span className="font-medium">{c.author_name}</span>
              <OrcidIcon className="h-3.5 w-3.5" />
            </a>
          ))}
        </div>
      )}

      {/* Claim panel — for logged-in users who haven't claimed this paper yet */}
      {user && !userClaim && !claimResult && (
        <div className="p-3 bg-secondary/30 rounded-lg border border-border" data-testid="claim-panel">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Are you an author?</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Verify your authorship via ORCID to get a verified badge
              </p>
            </div>
            {!orcidLinked ? (
              <Button size="sm" className="gap-1.5 shrink-0 bg-[#A6CE39] hover:bg-[#96be29] text-white" onClick={connectOrcid} data-testid="connect-orcid-btn">
                <OrcidIcon className="h-3.5 w-3.5" />
                Connect ORCID
              </Button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <OrcidIcon className="h-3 w-3" />
                  {user.orcid_id}
                </span>
                <Button size="sm" className="gap-1.5 shrink-0" onClick={claimPaper} disabled={claiming} data-testid="claim-paper-btn">
                  {claiming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                  Verify & Claim
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Prompt for non-logged-in users */}
      {!user && (
        <div className="p-3 bg-secondary/30 rounded-lg border border-border" data-testid="claim-panel-guest">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Are you an author?</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Sign in and verify via ORCID to get a verified badge
              </p>
            </div>
            <Button size="sm" variant="outline" className="gap-1.5 shrink-0" onClick={() => { sessionStorage.setItem("auth_return_to", window.location.pathname); window.dispatchEvent(new Event("open-auth-modal")); }} data-testid="sign-in-to-claim-btn">
              Sign in to claim
            </Button>
          </div>
        </div>
      )}

      {/* Already claimed by this user (pending) */}
      {user && userClaim && !userClaim.verified && !claimResult && (
        <div className="p-3 rounded-lg border bg-amber-50 border-amber-200" data-testid="claim-pending">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-amber-600" />
            <span className="text-sm text-amber-800">Your claim is pending admin review</span>
          </div>
        </div>
      )}

      {/* Claim result (just submitted) */}
      {claimResult && (
        <div className={`p-3 rounded-lg border ${
          claimResult.status === "verified" ? "bg-green-50 border-green-200" :
          claimResult.status === "already_claimed" ? "bg-blue-50 border-blue-200" :
          "bg-amber-50 border-amber-200"
        }`} data-testid="claim-result">
          <div className="flex items-center gap-2">
            {claimResult.status === "verified" ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <span className="text-sm text-green-800">
                  Verified as author{claimResult.matched_name ? ` (${claimResult.matched_name})` : ""}
                </span>
              </>
            ) : claimResult.status === "already_claimed" ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-blue-600" />
                <span className="text-sm text-blue-800">Already claimed</span>
              </>
            ) : (
              <>
                <AlertCircle className="h-4 w-4 text-amber-600" />
                <span className="text-sm text-amber-800">Claim submitted for admin review</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
