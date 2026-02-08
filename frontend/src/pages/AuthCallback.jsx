import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

export default function AuthCallback() {
  const hasProcessed = useRef(false);
  const navigate = useNavigate();
  const { loginWithGoogle } = useAuth();

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash;
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/", { replace: true });
      return;
    }

    const sessionId = match[1];

    (async () => {
      try {
        await loginWithGoogle(sessionId);
      } catch (err) {
        console.error("Google auth failed:", err);
      }
      // Clean URL and go home
      window.history.replaceState(null, "", "/");
      navigate("/", { replace: true });
    })();
  }, [loginWithGoogle, navigate]);

  return null; // No loading UI — process silently
}
