import { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import axios from "axios";
import { CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState("verifying"); // verifying | success | error

  useEffect(() => {
    if (!token) { setStatus("error"); return; }
    (async () => {
      try {
        await axios.post(`${API}/api/auth/verify-email?token=${token}`);
        setStatus("success");
      } catch {
        setStatus("error");
      }
    })();
  }, [token]);

  return (
    <div className="container mx-auto px-4 max-w-sm py-20 text-center">
      {status === "verifying" && (
        <div className="space-y-3">
          <div className="h-10 w-10 mx-auto rounded-full bg-secondary animate-pulse" />
          <p className="text-sm text-muted-foreground">Verifying your email...</p>
        </div>
      )}
      {status === "success" && (
        <div className="space-y-4">
          <CheckCircle2 className="h-12 w-12 mx-auto text-green-600" />
          <h1 className="text-xl font-semibold">Email verified!</h1>
          <p className="text-sm text-muted-foreground">Your account is now fully activated.</p>
          <Link to="/"><Button>Go to Leaderboard</Button></Link>
        </div>
      )}
      {status === "error" && (
        <div className="space-y-4">
          <XCircle className="h-12 w-12 mx-auto text-red-500" />
          <h1 className="text-xl font-semibold">Verification failed</h1>
          <p className="text-sm text-muted-foreground">This link may be invalid or expired.</p>
          <Link to="/"><Button variant="outline">Go to Leaderboard</Button></Link>
        </div>
      )}
    </div>
  );
}
