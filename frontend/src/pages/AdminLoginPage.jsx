import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Shield, Lock } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function AdminLoginPage() {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  // Check if already logged in
  const existingToken = sessionStorage.getItem("admin_token");
  if (existingToken) {
    navigate("/admin/dashboard", { replace: true });
    return null;
  }

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await axios.post(`${API}/api/admin/login`, { password });
      if (res.data.success) {
        sessionStorage.setItem("admin_token", res.data.token);
        toast.success("Logged in");
        navigate("/admin/dashboard");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Invalid password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container mx-auto px-4 max-w-sm py-20">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-lg bg-secondary mb-4">
          <Shield className="h-6 w-6 text-muted-foreground" />
        </div>
        <h1 className="font-heading text-xl font-semibold" data-testid="admin-login-title">Admin Panel</h1>
        <p className="text-sm text-muted-foreground mt-1">Enter the admin password to continue</p>
      </div>

      <form onSubmit={handleLogin} className="space-y-4" data-testid="admin-login-form">
        <div className="relative">
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="pl-10"
            autoFocus
            data-testid="admin-password-input"
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading || !password} data-testid="admin-login-button">
          {loading ? "Checking..." : "Sign In"}
        </Button>
      </form>
    </div>
  );
}
