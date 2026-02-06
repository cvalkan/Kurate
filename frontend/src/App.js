import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import LeaderboardPage from "@/pages/LeaderboardPage";
import CorrelationPage from "@/pages/CorrelationPage";
import PaperPage from "@/pages/PaperPage";
import AdminLoginPage from "@/pages/AdminLoginPage";
import AdminPage from "@/pages/AdminPage";
import Navbar from "@/components/Navbar";

function App() {
  return (
    <div className="min-h-screen bg-background">
      <BrowserRouter>
        <Navbar />
        <main className="pb-12">
          <Routes>
            <Route path="/" element={<LeaderboardPage />} />
            <Route path="/correlation" element={<CorrelationPage />} />
            <Route path="/paper/:id" element={<PaperPage />} />
            <Route path="/admin" element={<AdminLoginPage />} />
            <Route path="/admin/dashboard" element={<AdminPage />} />
          </Routes>
        </main>
        <Toaster position="bottom-right" />
      </BrowserRouter>
    </div>
  );
}

export default App;
