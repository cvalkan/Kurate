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
import ValidationHubPage from "@/pages/ValidationHubPage";
import ArchivePage from "@/pages/ArchivePage";
import OrcidCallbackPage from "@/pages/OrcidCallbackPage";
import BadgePage from "@/pages/BadgePage";
import ProfilePage from "@/pages/ProfilePage";
import BookmarksPage from "@/pages/BookmarksPage";
import Navbar from "@/components/Navbar";
import { BookmarkProvider } from "@/contexts/BookmarkContext";

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
          <Route path="/leaderboard/:category/:year/:weekOrMonth" element={<ArchivePage />} />
          <Route path="/correlation" element={<CorrelationPage />} />
          <Route path="/methodology" element={<MethodologyPage />} />
          <Route path="/validation" element={<ValidationHubPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/paper/:id" element={<PaperPage />} />
          <Route path="/admin" element={<AdminLoginPage />} />
          <Route path="/admin/dashboard" element={<AdminPage />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/auth/orcid/callback" element={<OrcidCallbackPage />} />
          <Route path="/badge/:category/:year/:slug/:paperId" element={<BadgePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/bookmarks" element={<BookmarksPage />} />
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
          <BookmarkProvider>
            <AppRouter />
          </BookmarkProvider>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
