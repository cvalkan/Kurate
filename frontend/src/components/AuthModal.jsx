import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { X, Mail, Chrome, RefreshCw } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

const API = process.env.REACT_APP_BACKEND_URL;

export function AuthModal({ open, onClose }) {
  const [mode, setMode] = useState("login"); // login | register
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [verificationSent, setVerificationSent] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState("");
  const { login } = useAuth();

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
        onClose();
      } else {
        const res = await fetch(`${API}/api/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, name }),
        });
        const data = await res.json();
        if (!res.ok) throw { response: { data } };
        setVerificationSent(true);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || "Something went wrong";
      // If login fails because unverified, show verification screen
      if (detail.includes("verify your email")) {
        setVerificationSent(true);
        return;
      }
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResendVerification = async () => {
    if (!email) return;
    setResending(true);
    setResendMsg("");
    try {
      const res = await fetch(`${API}/api/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) {
        setResendMsg(data.detail || "Failed to resend");
      } else {
        setResendMsg(data.message || "Verification email sent!");
      }
    } catch {
      setResendMsg("Failed to resend. Try again.");
    } finally {
      setResending(false);
    }
  };

  const handleGoogle = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/auth/callback";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  if (verificationSent) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
        <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-sm mx-4 p-6" onClick={e => e.stopPropagation()}>
          <div className="text-center">
            <Mail className="h-10 w-10 mx-auto mb-3 text-accent" />
            <h2 className="text-lg font-semibold mb-2">Check your email</h2>
            <p className="text-sm text-muted-foreground mb-4">
              We sent a verification link to <span className="font-medium text-foreground">{email}</span>. Click it to verify your account before logging in.
            </p>

            <Button
              variant="outline"
              className="w-full gap-2 mb-3"
              onClick={handleResendVerification}
              disabled={resending}
              data-testid="resend-verification-btn"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${resending ? "animate-spin" : ""}`} />
              {resending ? "Sending..." : "Resend verification email"}
            </Button>

            {resendMsg && (
              <p className="text-xs text-muted-foreground mb-3">{resendMsg}</p>
            )}

            <Button onClick={() => { setVerificationSent(false); setMode("login"); setError(""); setResendMsg(""); }} variant="ghost" className="w-full text-xs">
              Back to sign in
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose} data-testid="auth-modal">
      <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-base font-semibold">
            {mode === "login" ? "Sign in" : "Create account"}
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Google OAuth */}
          <Button variant="outline" className="w-full gap-2" onClick={handleGoogle} data-testid="google-login-btn">
            <Chrome className="h-4 w-4" />
            Continue with Google
          </Button>

          <div className="relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-border" /></div>
            <div className="relative flex justify-center text-xs"><span className="bg-background px-2 text-muted-foreground">or</span></div>
          </div>

          {/* Email form */}
          <form onSubmit={handleSubmit} className="space-y-3">
            {mode === "register" && (
              <div>
                <Label className="text-xs">Name</Label>
                <Input
                  value={name} onChange={e => setName(e.target.value)}
                  placeholder="Your name" required
                  className="h-9 text-sm" data-testid="auth-name-input"
                />
              </div>
            )}
            <div>
              <Label className="text-xs">Email</Label>
              <Input
                type="email" value={email} onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com" required
                className="h-9 text-sm" data-testid="auth-email-input"
              />
            </div>
            <div>
              <Label className="text-xs">Password</Label>
              <Input
                type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder={mode === "register" ? "Min 6 characters" : "Your password"} required minLength={6}
                className="h-9 text-sm" data-testid="auth-password-input"
              />
            </div>

            {error && <p className="text-xs text-red-500" data-testid="auth-error">{error}</p>}

            <Button type="submit" className="w-full" disabled={submitting} data-testid="auth-submit-btn">
              {submitting ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <div className="text-xs text-center space-y-1.5">
            <p className="text-muted-foreground">
              {mode === "login" ? (
                <>Don't have an account? <button onClick={() => { setMode("register"); setError(""); }} className="text-accent hover:underline" data-testid="switch-to-register">Sign up</button></>
              ) : (
                <>Already have an account? <button onClick={() => { setMode("login"); setError(""); }} className="text-accent hover:underline" data-testid="switch-to-login">Sign in</button></>
              )}
            </p>
            {mode === "login" && (
              <p>
                <button
                  onClick={() => { if (email) { setVerificationSent(true); } else { setError("Enter your email first"); } }}
                  className="text-muted-foreground hover:text-accent hover:underline"
                  data-testid="resend-link"
                >
                  Resend verification email
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
