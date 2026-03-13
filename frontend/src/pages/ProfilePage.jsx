import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { User, Lock, Loader2, CheckCircle2, ExternalLink, Clock } from "lucide-react";
import { toast } from "sonner";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

function OrcidIcon({ className }) {
  return (
    <svg viewBox="0 0 256 256" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M128 0C57.3 0 0 57.3 0 128s57.3 128 128 128 128-57.3 128-128S198.7 0 128 0z" fill="#A6CE39" />
      <path d="M86.3 186.2H70.9V79.1h15.4v107.1zM108.9 79.1h41.6c39.6 0 57 28.3 57 53.6 0 27.5-21.5 53.6-56.8 53.6h-41.8V79.1zm15.4 93.3h24.5c34.9 0 42.9-26.5 42.9-39.7 0-21.5-13.7-39.7-43.7-39.7h-23.7v79.4zM86.3 74.4c0 5.4-4.4 9.8-9.8 9.8-5.4 0-9.8-4.4-9.8-9.8s4.4-9.8 9.8-9.8c5.4 0 9.8 4.4 9.8 9.8z" fill="#fff" />
    </svg>
  );
}

export default function ProfilePage() {
  const { user, getAuthHeaders, checkAuth } = useAuth();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPw, setChangingPw] = useState(false);
  const [connectingOrcid, setConnectingOrcid] = useState(false);

  if (!user) {
    return (
      <div className="container mx-auto px-4 max-w-lg py-20 text-center text-muted-foreground">
        <User className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">Sign in to view your profile.</p>
      </div>
    );
  }

  const changePassword = async (e) => {
    e.preventDefault();
    if (newPassword.length < 6) { toast.error("Password must be at least 6 characters"); return; }
    if (newPassword !== confirmPassword) { toast.error("Passwords don't match"); return; }
    setChangingPw(true);
    try {
      await axios.post(`${API}/api/auth/change-password`,
        { current_password: currentPassword, new_password: newPassword },
        { withCredentials: true, headers: getAuthHeaders() }
      );
      toast.success("Password changed");
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to change password");
    } finally { setChangingPw(false); }
  };

  const connectOrcid = async () => {
    try {
      const redirectUri = `${window.location.origin}/auth/orcid/callback`;
      const res = await axios.get(`${API}/api/claim/orcid/auth-url`, {
        params: { redirect_uri: redirectUri },
        withCredentials: true, headers: getAuthHeaders(),
      });
      sessionStorage.setItem("orcid_return_to", "/profile");
      window.location.href = res.data.url;
    } catch (err) {
      if (err.response?.status === 503) {
        toast.error("ORCID integration is not yet configured.");
      } else {
        toast.error("Failed to connect ORCID");
      }
    }
  };

  const isGoogleUser = user.provider === "google";

  return (
    <div className="container mx-auto px-4 max-w-lg py-8 md:py-12">
      <h1 className="font-heading text-xl font-semibold mb-6" data-testid="profile-title">Profile</h1>

      {/* Account info */}
      <div className="mb-8 p-4 bg-secondary/30 rounded-lg border border-border" data-testid="account-info">
        <div className="flex items-center gap-3 mb-3">
          {user.picture ? (
            <img src={user.picture} alt="" className="w-10 h-10 rounded-full" />
          ) : (
            <div className="w-10 h-10 rounded-full bg-accent/10 flex items-center justify-center">
              <User className="h-5 w-5 text-accent" />
            </div>
          )}
          <div>
            <p className="font-medium text-sm">{user.name}</p>
            <p className="text-xs text-muted-foreground">{user.email}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isGoogleUser ? "bg-blue-50 text-blue-700" : "bg-secondary text-foreground"}`}>
            {isGoogleUser ? "Google" : "Email"}
          </span>
          {user.email_verified && <span className="text-green-600 flex items-center gap-0.5"><CheckCircle2 className="h-3 w-3" /> Verified</span>}
        </div>
      </div>

      {/* Change password — only for email users */}
      {!isGoogleUser && (
        <div className="mb-8" data-testid="change-password">
          <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
            <Lock className="h-4 w-4" /> Change Password
          </h2>
          <form onSubmit={changePassword} className="space-y-3">
            <div>
              <Label className="text-xs">Current Password</Label>
              <Input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required className="mt-1" data-testid="current-password" />
            </div>
            <div>
              <Label className="text-xs">New Password</Label>
              <Input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6} className="mt-1" data-testid="new-password" />
            </div>
            <div>
              <Label className="text-xs">Confirm New Password</Label>
              <Input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required className="mt-1" data-testid="confirm-password" />
            </div>
            <Button type="submit" size="sm" disabled={changingPw} className="gap-1.5" data-testid="change-password-btn">
              {changingPw && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Change Password
            </Button>
          </form>
        </div>
      )}

      {/* ORCID linking */}
      <div data-testid="orcid-section">
        <h2 className="text-sm font-medium mb-3 flex items-center gap-1.5">
          <OrcidIcon className="h-4 w-4" /> ORCID
        </h2>
        {user.orcid_id ? (
          <div className={`p-3 rounded-lg border ${user.orcid_admin_verified ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"}`}>
            <div className="flex items-center gap-2 text-sm">
              {user.orcid_admin_verified ? (
                <CheckCircle2 className="h-4 w-4 text-green-600" />
              ) : (
                <Clock className="h-4 w-4 text-amber-600" />
              )}
              <span className="font-medium">
                {user.orcid_admin_verified ? "ORCID verified" : "ORCID linked — pending review"}
              </span>
            </div>
            <a href={`https://orcid.org/${user.orcid_id}`} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[#A6CE39] hover:underline mt-1">
              {user.orcid_id} <ExternalLink className="h-3 w-3" />
            </a>
            <p className="text-[10px] text-muted-foreground mt-1">
              {user.orcid_admin_verified
                ? "Your ORCID identity has been verified by an admin."
                : "Your ORCID link is awaiting admin verification."}
            </p>
          </div>
        ) : (
          <div className="p-3 bg-secondary/30 rounded-lg border border-border">
            <p className="text-sm mb-2">Link your ORCID to verify authorship of your papers.</p>
            <p className="text-xs text-muted-foreground mb-3">After linking, you can claim your papers for admin-approved author badges.</p>
            <Button size="sm" className="gap-1.5 bg-[#A6CE39] hover:bg-[#96be29] text-white" onClick={connectOrcid} data-testid="connect-orcid-btn">
              <OrcidIcon className="h-3.5 w-3.5" />
              Connect ORCID
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
