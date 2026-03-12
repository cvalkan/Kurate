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
      // Return to the page the user was on (e.g., paper page) or go home
      const returnTo = sessionStorage.getItem("auth_return_to");
      sessionStorage.removeItem("auth_return_to");
      const dest = returnTo || "/";
      window.history.replaceState(null, "", dest);
      navigate(dest, { replace: true });
    })();
  }, [loginWithGoogle, navigate]);

  return null; // No loading UI — process silently
}
