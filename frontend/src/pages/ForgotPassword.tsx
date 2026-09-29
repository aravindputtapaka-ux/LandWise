import { useState } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff, Loader2, Lock, Mail, Sparkles } from "lucide-react";
import { api, ApiError } from "../api";

export default function ForgotPassword({ onBack, onLogin }: { onBack: () => void; onLogin: () => void }) {
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<"email" | "reset">("email");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function sendOtp(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const res = await api<{ message: string }>("/auth/forgot-password", { method: "POST", body: { email: email.trim() } });
      setMessage(res.message); setStep("reset");
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not send reset OTP."); }
    finally { setBusy(false); }
  }

  async function reset(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setMessage("");
    if (!/^\d{6}$/.test(otp)) { setError("Enter the 6-digit OTP."); setBusy(false); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters long."); setBusy(false); return; }
    try {
      const res = await api<{ message: string }>("/auth/reset-password", { method: "POST", body: { email: email.trim(), otp, new_password: password } });
      setMessage(res.message); setTimeout(onLogin, 700);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not reset your password."); }
    finally { setBusy(false); }
  }

  async function resend() {
    setBusy(true); setError("");
    try { const res = await api<{ message: string }>("/auth/otp/resend", { method: "POST", body: { email: email.trim(), purpose: "reset" } }); setMessage(res.message); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not resend OTP."); }
    finally { setBusy(false); }
  }

  return <main className="app"><div className="background-glow glow-a" /><div className="background-glow glow-b" /><div className="dashboard auth-card">
    <button className="back-button auth-back" onClick={onBack}><ArrowLeft size={16} /> Back</button>
    <div className="brand auth-brand"><span className="brand-icon"><Sparkles size={15} /></span><span>LandWise <b>AI</b></span></div>
    {step === "email" ? <>
      <h1>Forgot password?</h1><p className="subtitle">Enter your verified email and we'll send a 6-digit OTP through Gmail.</p>
      <form onSubmit={sendOtp}><div className="field"><label>EMAIL</label><div className="search-box"><Mail size={16} /><input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div></div>
      <button className="analyze" disabled={busy} type="submit">{busy ? <><Loader2 size={17} className="spin" /> Sending OTP...</> : <>Send OTP<ArrowRight size={18} /></>}</button>
      </form>
    </> : <>
      <h1>Reset password</h1><p className="subtitle">Enter the OTP sent to <b>{email}</b> and choose a new password.</p>
      <form onSubmit={reset}><div className="field"><label>EMAIL OTP</label><div className="search-box"><Mail size={16} /><input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="Enter 6-digit OTP" required /></div></div>
      <div className="field"><label>NEW PASSWORD</label><div className="search-box"><Lock size={16} /><input type={showPassword ? "text" : "password"} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 6 characters" required /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword(v => !v)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></div>
      <button className="analyze" disabled={busy} type="submit">{busy ? <><Loader2 size={17} className="spin" /> Resetting...</> : <>Reset password<ArrowRight size={18} /></>}</button>
      <button className="secondary-action" disabled={busy} type="button" onClick={resend}>Resend OTP</button>
      </form>
    </>}
    {message && <div className="success-message">{message}</div>}{error && <div className="error">{error}</div>}
    <p className="auth-switch"><button onClick={onLogin}>Back to login</button></p>
  </div></main>;
}
