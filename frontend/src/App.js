import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import LeaderboardPage from "@/pages/LeaderboardPage";
import CorrelationPage from "@/pages/CorrelationPage";
import MethodologyPage from "@/pages/MethodologyPage";
import PaperPage from "@/pages/PaperPage";
import AdminLoginPage from "@/pages/AdminLoginPage";
import AdminPage from "@/pages/AdminPage";
import PromptsPage from "@/pages/PromptsPage";
import AuthCallback from "@/pages/AuthCallback";
import VerifyEmailPage from "@/pages/VerifyEmailPage";
import ValidationPage from "@/pages/ValidationPage";
import PairwisePage from "@/pages/PairwisePage";
import Navbar from "@/components/Navbar";

function AppRouter() {
  const location = useLocation();
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  // Check URL fragment for session_id synchronously during render (prevents race conditions)
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <>
      <Navbar />
      <main className="pb-12">
        <Routes>
          <Route path="/" element={<LeaderboardPage />} />
          <Route path="/correlation" element={<CorrelationPage />} />
          <Route path="/methodology" element={<MethodologyPage />} />
          <Route path="/validation" element={<ValidationPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/paper/:id" element={<PaperPage />} />
          <Route path="/admin" element={<AdminLoginPage />} />
          <Route path="/admin/dashboard" element={<AdminPage />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
        </Routes>
      </main>
      <Toaster position="bottom-right" />
    </>
  );
}

function App() {
  return (
    <div className="min-h-screen bg-background">
      <BrowserRouter>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
