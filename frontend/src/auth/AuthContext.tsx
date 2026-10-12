import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api, ApiError } from "../api";

export type User = { id: string; name: string; email: string; created_at?: string | null };

type AuthState = {
  user: User | null;
  token: string | null;
  ready: boolean;
  error: string;
  busy: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  signup: (name: string, email: string, password: string) => Promise<{ message: string } | null>;
  verifySignup: (email: string, otp: string) => Promise<boolean>;
  resendOtp: (email: string, purpose: "signup" | "reset") => Promise<{ message: string } | null>;
  logout: () => void;
  clearError: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

const TOKEN_KEY = "landwise.token";
const USER_KEY = "landwise.user";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(() => {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? (JSON.parse(raw) as User) : null;
    } catch { return null; }
  });
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      if (!token) { setReady(true); return; }
      try {
        const me = await api<User>("/auth/me", { token });
        setUser(me);
        localStorage.setItem(USER_KEY, JSON.stringify(me));
      } catch {
        // Token expired or invalid: clear silently.
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        setToken(null);
        setUser(null);
      } finally {
        setReady(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, password: string) {
    setBusy(true); setError("");
    try {
      const res = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
      setToken(res.token); setUser(res.user);
      localStorage.setItem(TOKEN_KEY, res.token);
      localStorage.setItem(USER_KEY, JSON.stringify(res.user));
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not sign in. Please try again.");
      return false;
    } finally { setBusy(false); }
  }

  async function signup(name: string, email: string, password: string) {
    setBusy(true); setError("");
    try {
      return await api<{ message: string }>("/auth/signup", { method: "POST", body: { name, email, password } });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create your account. Please try again.");
      return null;
    } finally { setBusy(false); }
  }

  async function verifySignup(email: string, otp: string) {
    setBusy(true); setError("");
    try {
      const res = await api<{ token: string; user: User }>("/auth/signup/verify", { method: "POST", body: { email, otp } });
      setToken(res.token); setUser(res.user);
      localStorage.setItem(TOKEN_KEY, res.token); localStorage.setItem(USER_KEY, JSON.stringify(res.user));
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not verify your email.");
      return false;
    } finally { setBusy(false); }
  }

  async function resendOtp(email: string, purpose: "signup" | "reset") {
    setBusy(true); setError("");
    try { return await api<{ message: string }>("/auth/otp/resend", { method: "POST", body: { email, purpose } }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not resend OTP."); return null; }
    finally { setBusy(false); }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null); setUser(null);
  }

  function clearError() { setError(""); }

  return (
    <AuthContext.Provider value={{ user, token, ready, error, busy, login, signup, verifySignup, resendOtp, logout, clearError }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
