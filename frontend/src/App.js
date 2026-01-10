import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import HomePage from "@/pages/HomePage";
import SearchPage from "@/pages/SearchPage";
import TournamentPage from "@/pages/TournamentPage";
import ResultsPage from "@/pages/ResultsPage";
import HistoryPage from "@/pages/HistoryPage";
import Navbar from "@/components/Navbar";

function App() {
  return (
    <div className="min-h-screen bg-background">
      <BrowserRouter>
        <Navbar />
        <main className="pb-12">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/tournament/:id" element={<TournamentPage />} />
            <Route path="/results/:id" element={<ResultsPage />} />
            <Route path="/history" element={<HistoryPage />} />
          </Routes>
        </main>
        <Toaster position="bottom-right" />
      </BrowserRouter>
    </div>
  );
}

export default App;
