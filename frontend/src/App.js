import "@/App.css";
import "katex/dist/katex.min.css";
import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import { BasePathProvider } from "@/contexts/BasePathContext";
import { AuthModal } from "@/components/AuthModal";
import { BookmarkProvider } from "@/contexts/BookmarkContext";
import { ThemeProvider } from "@/contexts/ThemeContext";

// Auth modal listener (replaces old Navbar's auth modal)
function GlobalAuthModal() {
  const [showAuth, setShowAuth] = useState(false);
  useEffect(() => {
    const handler = () => setShowAuth(true);
    window.addEventListener("open-auth-modal", handler);
    return () => window.removeEventListener("open-auth-modal", handler);
  }, []);
  return <AuthModal open={showAuth} onClose={() => setShowAuth(false)} />;
}

// Pages — new design
import HomePage from "@/pages/HomePage";
import Design3Page from "@/pages/Design3Page";
import PaperDesignB from "@/pages/PaperDesignB";
import NewArchivePage from "@/pages/NewArchivePage";
import TopNavLayout from "@/components/TopNavLayout";

// Pages — existing (wrapped with TopNavLayout)
import CorrelationPage from "@/pages/CorrelationPage";
import MethodologyPage from "@/pages/MethodologyPage";
import ValidationHubPage from "@/pages/ValidationHubPage";
import PromptsPage from "@/pages/PromptsPage";
import BadgePage from "@/pages/BadgePage";
import DefiPage from "@/pages/DefiPage";
import ProfilePage from "@/pages/ProfilePage";
import BookmarksPage from "@/pages/BookmarksPage";
import ReadingListPage from "@/pages/ReadingListPage";
import VerifyEmailPage from "@/pages/VerifyEmailPage";
import PrivacyPage from "@/pages/PrivacyPage";
import ImpressumPage from "@/pages/ImpressumPage";
import ContactPage from "@/pages/ContactPage";
import AuthCallback from "@/pages/AuthCallback";
import OrcidCallbackPage from "@/pages/OrcidCallbackPage";
import StartRedirect from "@/pages/StartRedirect";

// Pages — admin
import AdminLoginPage from "@/pages/AdminLoginPage";
import AdminPage from "@/pages/AdminPage";
import OutreachPage from "@/pages/OutreachPage";
import OutreachActivityPage from "@/pages/OutreachActivityPage";
import EmailOutreachPage from "@/pages/EmailOutreachPage";
import ScoreCardTest from "@/pages/ScoreCardTest";
import NewBadgeTest from "@/pages/NewBadgeTest";
import SimulatedMemChart from "@/pages/SimulatedMemChart";

function AppRouter() {
  const location = useLocation();

  // Scroll to top on route change
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }

  // Admin pages — TopNav for consistency
  if (location.pathname.startsWith("/admin") || location.pathname.startsWith("/test/")) {
    return (
      <BasePathProvider value="">
        <TopNavLayout>
          <main className="pb-12">
            <Routes>
              <Route path="/admin" element={<AdminLoginPage />} />
              <Route path="/admin/dashboard" element={<AdminPage />} />
              <Route path="/admin/outreach" element={<OutreachPage />} />
              <Route path="/admin/outreach/activity" element={<OutreachActivityPage />} />
              <Route path="/admin/outreach/email" element={<EmailOutreachPage />} />
              <Route path="/test/score-card" element={<ScoreCardTest />} />
              <Route path="/test/new-badge" element={<NewBadgeTest />} />
              <Route path="/test/sim-mem" element={<SimulatedMemChart />} />
            </Routes>
          </main>
        </TopNavLayout>
        <GlobalAuthModal />
        <Toaster position="bottom-right" />
      </BasePathProvider>
    );
  }

  // Homepage — has its own TopNav + SiteFooter
  if (location.pathname === "/") {
    return (
      <BasePathProvider value="">
        <HomePage />
        <GlobalAuthModal />
        <Toaster position="bottom-right" />
      </BasePathProvider>
    );
  }

  // All other pages — new TopNav design
  return (
    <BasePathProvider value="">
      <Routes>
        {/* New design pages */}
        <Route path="/leaderboard" element={<Design3Page />} />
        <Route path="/leaderboard/:category/:year/:weekOrMonth" element={<NewArchivePage />} />
        <Route path="/paper/:id" element={<PaperDesignB />} />

        {/* Existing pages wrapped with TopNav */}
        <Route path="/methodology" element={<TopNavLayout><MethodologyPage /></TopNavLayout>} />
        <Route path="/correlation" element={<TopNavLayout><CorrelationPage /></TopNavLayout>} />
        <Route path="/validation" element={<TopNavLayout><ValidationHubPage /></TopNavLayout>} />
        <Route path="/prompts" element={<TopNavLayout><PromptsPage /></TopNavLayout>} />
        <Route path="/share/:paperId" element={<TopNavLayout><BadgePage /></TopNavLayout>} />
        <Route path="/badge/:category/:year/:slug/:paperId" element={<TopNavLayout><BadgePage /></TopNavLayout>} />
        <Route path="/defi" element={<TopNavLayout><DefiPage /></TopNavLayout>} />
        <Route path="/profile" element={<TopNavLayout><ProfilePage /></TopNavLayout>} />
        <Route path="/bookmarks" element={<TopNavLayout><BookmarksPage /></TopNavLayout>} />
        <Route path="/list/:listId" element={<TopNavLayout><ReadingListPage /></TopNavLayout>} />
        <Route path="/verify-email" element={<TopNavLayout><VerifyEmailPage /></TopNavLayout>} />
        <Route path="/privacy" element={<TopNavLayout><PrivacyPage /></TopNavLayout>} />
        <Route path="/impressum" element={<TopNavLayout><ImpressumPage /></TopNavLayout>} />
        <Route path="/contact" element={<TopNavLayout><ContactPage /></TopNavLayout>} />
        <Route path="/start" element={<StartRedirect />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/auth/orcid/callback" element={<OrcidCallbackPage />} />
      </Routes>
      <GlobalAuthModal />
      <Toaster position="bottom-right" />
    </BasePathProvider>
  );
}

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
