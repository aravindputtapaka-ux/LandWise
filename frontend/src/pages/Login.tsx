import { useState } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff, Loader2, Lock, Mail, Sparkles } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

export default function Login({ onBack, onSwitchToSignup, onForgot, onSuccess }: { onBack: () => void; onSwitchToSignup: () => void; onForgot: () => void; onSuccess: () => void }) {
  const { login, busy, error, clearError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); clearError();
    if (!email.trim() || !password) return;
    const ok = await login(email.trim(), password);
    if (ok) onSuccess();
  }

  return (
    <main className="app">
      <div className="background-glow glow-a" /><div className="background-glow glow-b" />
      <div className="dashboard auth-card">
        <button className="back-button auth-back" onClick={onBack}><ArrowLeft size={16} /> Back</button>
        <div className="brand auth-brand"><span className="brand-icon"><Sparkles size={15} /></span><span>LandWise <b>AI</b></span></div>
        <h1>Welcome back</h1>
        <p className="subtitle">Log in to run property estimates and see your saved search history.</p>
        <form onSubmit={submit}>
          <div className="field"><label>EMAIL</label><div className="search-box"><Mail size={16} /><input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div></div>
          <div className="field"><label>PASSWORD</label><div className="search-box"><Lock size={16} /><input type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" required /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword(v => !v)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></div>
          <button className="analyze" disabled={busy} type="submit">{busy ? <><Loader2 size={17} className="spin" /> Signing in...</> : <>Log in<ArrowRight size={18} /></>}</button>
          {error && <div className="error">{error}</div>}
        </form>
        <p className="auth-switch"><button onClick={onForgot}>Forgot password?</button></p>
        <p className="auth-switch">New to LandWise AI? <button onClick={onSwitchToSignup}>Create an account</button></p>
      </div>
    </main>
  );
}
