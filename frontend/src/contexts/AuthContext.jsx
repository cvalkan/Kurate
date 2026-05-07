import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const getAuthHeaders = useCallback(() => {
    const token = localStorage.getItem("session_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/auth/me`, {
        withCredentials: true,
        headers: getAuthHeaders(),
      });
      setUser(res.data);
    } catch {
      setUser(null);
      localStorage.removeItem("session_token");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (email, password) => {
    const res = await axios.post(`${API}/api/auth/login`, { email, password }, { withCredentials: true });
    if (res.data.session_token) {
      localStorage.setItem("session_token", res.data.session_token);
    }
    setUser(res.data.user);
    return res.data;
  };

  const register = async (email, password, name) => {
    const res = await axios.post(`${API}/api/auth/register`, { email, password, name }, { withCredentials: true });
    if (res.data.session_token) {
      localStorage.setItem("session_token", res.data.session_token);
    }
    setUser(res.data.user);
    // X (Twitter) signup conversion pixel
    if (window.twq) window.twq('event', 'tw-rc00t-rcb0n', {});
    return res.data;
  };

  const loginWithGoogle = async (sessionId) => {
    const res = await axios.post(`${API}/api/auth/google-session`, { session_id: sessionId }, { withCredentials: true });
    if (res.data.session_token) {
      localStorage.setItem("session_token", res.data.session_token);
    }
    setUser(res.data.user);
    // X (Twitter) signup conversion pixel (Google OAuth)
    if (window.twq) window.twq('event', 'tw-rc00t-rcb0n', {});
    return res.data;
  };

  const logout = async () => {
    try {
      await axios.post(`${API}/api/auth/logout`, {}, { withCredentials: true, headers: getAuthHeaders() });
    } catch { /* ignore */ }
    localStorage.removeItem("session_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, loginWithGoogle, logout, checkAuth, getAuthHeaders }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
