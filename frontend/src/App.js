import "@/App.css";
import "katex/dist/katex.min.css";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import LeaderboardPage from "@/pages/LeaderboardPage";
import CorrelationPage from "@/pages/CorrelationPage";
import MethodologyPage from "@/pages/MethodologyPage";
import PaperPage from "@/pages/PaperPage";
import AdminLoginPage from "@/pages/AdminLoginPage";
import AdminPage from "@/pages/AdminPage";
import OutreachPage from "@/pages/OutreachPage";
import OutreachActivityPage from "@/pages/OutreachActivityPage";
import EmailOutreachPage from "@/pages/EmailOutreachPage";
import DefiPage from "@/pages/DefiPage";
import PromptsPage from "@/pages/PromptsPage";
import AuthCallback from "@/pages/AuthCallback";
import VerifyEmailPage from "@/pages/VerifyEmailPage";
import ValidationHubPage from "@/pages/ValidationHubPage";
import ArchivePage from "@/pages/ArchivePage";
import OrcidCallbackPage from "@/pages/OrcidCallbackPage";
import BadgePage from "@/pages/BadgePage";
import ProfilePage from "@/pages/ProfilePage";
import BookmarksPage from "@/pages/BookmarksPage";
import ReadingListPage from "@/pages/ReadingListPage";
import ScoreCardTest from "@/pages/ScoreCardTest";
import NewBadgeTest from "@/pages/NewBadgeTest";
import SimulatedMemChart from "@/pages/SimulatedMemChart";
import PrivacyPage from "@/pages/PrivacyPage";
import ImpressumPage from "@/pages/ImpressumPage";
import ContactPage from "@/pages/ContactPage";
import StartRedirect from "@/pages/StartRedirect";
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
          <Route path="/start" element={<StartRedirect />} />
          <Route path="/leaderboard/:category/:year/:weekOrMonth" element={<ArchivePage />} />
          <Route path="/correlation" element={<CorrelationPage />} />
          <Route path="/methodology" element={<MethodologyPage />} />
          <Route path="/validation" element={<ValidationHubPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
          <Route path="/paper/:id" element={<PaperPage />} />
          <Route path="/admin" element={<AdminLoginPage />} />
          <Route path="/test/score-card" element={<ScoreCardTest />} />
          <Route path="/test/new-badge" element={<NewBadgeTest />} />
          <Route path="/test/sim-mem" element={<SimulatedMemChart />} />
          <Route path="/admin/dashboard" element={<AdminPage />} />
          <Route path="/admin/outreach" element={<OutreachPage />} />
          <Route path="/admin/outreach/activity" element={<OutreachActivityPage />} />
          <Route path="/admin/outreach/email" element={<EmailOutreachPage />} />
          <Route path="/defi" element={<DefiPage />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/auth/orcid/callback" element={<OrcidCallbackPage />} />
          <Route path="/badge/:category/:year/:slug/:paperId" element={<BadgePage />} />
          <Route path="/share/:paperId" element={<BadgePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/bookmarks" element={<BookmarksPage />} />
          <Route path="/list/:listId" element={<ReadingListPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/impressum" element={<ImpressumPage />} />
          <Route path="/contact" element={<ContactPage />} />
        </Routes>
      </main>
      <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground">
        <a href="/privacy" className="hover:underline">Privacy Policy</a>
        <span className="mx-2">·</span>
        <a href="/impressum" className="hover:underline">Impressum</a>
        <span className="mx-2">·</span>
        <a href="/contact" className="hover:underline">Contact</a>
      </footer>
      <Toaster position="bottom-right" />
    </>
  );
}

import { ThemeProvider } from "@/contexts/ThemeContext";

function App() {
  return (
    <div className="min-h-screen bg-background">
      <BrowserRouter>
        <ThemeProvider>
          <AuthProvider>
            <BookmarkProvider>
              <AppRouter />
            </BookmarkProvider>
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
