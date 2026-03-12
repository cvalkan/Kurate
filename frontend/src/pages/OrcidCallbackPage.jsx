import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/contexts/AuthContext";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function OrcidCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { getAuthHeaders } = useAuth();
  const [status, setStatus] = useState("processing"); // processing | success | error
  const [message, setMessage] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setStatus("error");
      setMessage("No authorization code received from ORCID.");
      return;
    }

    const connectOrcid = async () => {
      try {
        const redirectUri = `${window.location.origin}/auth/orcid/callback`;
        const res = await axios.post(
          `${API}/api/claim/orcid/connect`,
          { code, redirect_uri: redirectUri },
          { withCredentials: true, headers: getAuthHeaders() }
        );
        setStatus("success");
        setMessage(`ORCID ${res.data.orcid_id} linked successfully!`);
        // Redirect back after short delay
        setTimeout(() => {
          const returnTo = sessionStorage.getItem("orcid_return_to");
          sessionStorage.removeItem("orcid_return_to");
          navigate(returnTo || "/", { replace: true });
        }, 1500);
      } catch (err) {
        setStatus("error");
        setMessage(err.response?.data?.detail || "Failed to connect ORCID. Please try again.");
      }
    };

    connectOrcid();
  }, [searchParams, getAuthHeaders, navigate]);

  return (
    <div className="container mx-auto px-4 max-w-md py-20 text-center">
      {status === "processing" && (
        <div className="space-y-4">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-accent" />
          <p className="text-sm text-muted-foreground">Connecting your ORCID...</p>
        </div>
      )}
      {status === "success" && (
        <div className="space-y-4">
          <CheckCircle2 className="h-8 w-8 mx-auto text-green-600" />
          <p className="text-sm font-medium">{message}</p>
          <p className="text-xs text-muted-foreground">Redirecting...</p>
        </div>
      )}
      {status === "error" && (
        <div className="space-y-4">
          <XCircle className="h-8 w-8 mx-auto text-red-500" />
          <p className="text-sm font-medium text-red-600">{message}</p>
          <button onClick={() => navigate(-1)} className="text-xs text-accent hover:underline">
            Go back
          </button>
        </div>
      )}
    </div>
  );
}
