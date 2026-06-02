import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { AdminStatistics } from "@/components/AdminStatistics";

const API = process.env.REACT_APP_BACKEND_URL;

export default function Admin2StatsPage() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    if (!sessionStorage.getItem("admin_token")) {
      navigate("/admin");
      return;
    }
    axios
      .get(`${API}/api/categories`)
      .then((res) => setCategories(res.data.categories || []))
      .catch(() => setCategories([]));
  }, [navigate]);

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10" data-testid="admin2-stats-page">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-heading text-2xl font-semibold" data-testid="admin2-title">Statistics v2</h1>
        <Button variant="ghost" size="sm" onClick={() => navigate("/admin/dashboard")} data-testid="admin2-back-btn">
          <ArrowLeft className="h-4 w-4 mr-1" /> Dashboard
        </Button>
      </div>
      <AdminStatistics categories={categories} />
    </div>
  );
}
