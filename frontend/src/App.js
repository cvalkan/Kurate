import "@/App.css";
import "katex/dist/katex.min.css";
import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import { BasePathProvider } from "@/contexts/BasePathContext";
import { Helmet } from "react-helmet";
import { AuthModal } from "@/components/AuthModal";

function NewSiteAuthModal() {
  const [showAuth, setShowAuth] = useState(false);
  useEffect(() => {
    const handler = () => setShowAuth(true);
    window.addEventListener("open-auth-modal", handler);
    return () => window.removeEventListener("open-auth-modal", handler);
  }, []);
  return <AuthModal open={showAuth} onClose={() => setShowAuth(false)} />;
}
import HomePage from "@/pages/HomePage";
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
import Design1Page from "@/pages/Design1Page";
import Design2Page from "@/pages/Design2Page";
import Design3Page from "@/pages/Design3Page";
import PaperDesignA from "@/pages/PaperDesignA";
import PaperDesignB from "@/pages/PaperDesignB";
import NewMethodologyPage from "@/pages/NewMethodologyPage";
import NewCorrelationPage from "@/pages/NewCorrelationPage";
import NewValidationPage from "@/pages/NewValidationPage";
import NewBadgePage from "@/pages/NewBadgePage";
import NewArchivePage from "@/pages/NewArchivePage";
import Navbar from "@/components/Navbar";
import { BookmarkProvider } from "@/contexts/BookmarkContext";

function AppRouter() {
  const location = useLocation();

  // Scroll to top on route change
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  // Check URL fragment for session_id synchronously during render (prevents race conditions)
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }

  // New site structure under /new/... — noindex, mirrors current routes with new designs
  if (location.pathname.startsWith("/new")) {
    return (
      <BasePathProvider value="/new">
        <Helmet><meta name="robots" content="noindex, nofollow" /></Helmet>
        <Routes>
          <Route path="/new" element={<HomePage />} />
          <Route path="/new/leaderboard" element={<Design3Page />} />
          <Route path="/new/paper/:id" element={<PaperDesignB />} />
          <Route path="/new/methodology" element={<NewMethodologyPage />} />
          <Route path="/new/correlation" element={<NewCorrelationPage />} />
          <Route path="/new/validation" element={<NewValidationPage />} />
          <Route path="/new/share/:paperId" element={<NewBadgePage />} />
          <Route path="/new/badge/:category/:year/:slug/:paperId" element={<NewBadgePage />} />
          <Route path="/new/leaderboard/:category/:year/:weekOrMonth" element={<NewArchivePage />} />
        </Routes>
        <NewSiteAuthModal />
        <Toaster position="bottom-right" />
      </BasePathProvider>
    );
  }

  // Standalone design explorations (legacy URLs, keep working)
  if (location.pathname === "/design1") {
    return (<><Design1Page /><Toaster position="bottom-right" /></>);
  }
  if (location.pathname === "/design2") {
    return (<><Design2Page /><Toaster position="bottom-right" /></>);
  }
  if (location.pathname === "/design3") {
    return (<><Design3Page /><Toaster position="bottom-right" /></>);
  }
  if (location.pathname.startsWith("/paper-a/")) {
    return (<><Routes><Route path="/paper-a/:id" element={<PaperDesignA />} /></Routes><Toaster position="bottom-right" /></>);
  }
  if (location.pathname.startsWith("/paper-b/")) {
    return (<><Routes><Route path="/paper-b/:id" element={<PaperDesignB />} /></Routes><Toaster position="bottom-right" /></>);
  }

  return (
    <>
      <Navbar />
      <main className="pb-12">
        <Routes>
          <Route path="/" element={<LeaderboardPage />} />
          <Route path="/leaderboard" element={<LeaderboardPage />} />
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
