import { useState } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff, Loader2, Lock, Mail, Sparkles, User } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

export default function Signup({ onBack, onSwitchToLogin, onSuccess }: { onBack: () => void; onSwitchToLogin: () => void; onSuccess: () => void }) {
  const { signup, verifySignup, resendOtp, busy, error, clearError } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<"details" | "otp">("details");
  const [message, setMessage] = useState("");
  const [localError, setLocalError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault(); clearError(); setLocalError(""); setMessage("");
    if (!name.trim() || !email.trim() || !password) return;
    if (password.length < 6) { setLocalError("Password must be at least 6 characters long."); return; }
    const res = await signup(name.trim(), email.trim(), password);
    if (res) { setStep("otp"); setMessage(res.message); }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault(); clearError(); setLocalError("");
    if (!/^\d{6}$/.test(otp)) { setLocalError("Enter the 6-digit OTP sent to your email."); return; }
    const ok = await verifySignup(email.trim(), otp);
    if (ok) onSuccess();
  }

  async function resend() {
    clearError(); setLocalError("");
    const res = await resendOtp(email.trim(), "signup");
    if (res) setMessage(res.message);
  }

  return (
    <main className="app">
      <div className="background-glow glow-a" /><div className="background-glow glow-b" />
      <div className="dashboard auth-card">
        <button className="back-button auth-back" onClick={onBack}><ArrowLeft size={16} /> Back</button>
        <div className="brand auth-brand"><span className="brand-icon"><Sparkles size={15} /></span><span>LandWise <b>AI</b></span></div>
        {step === "details" ? <>
          <h1>Create your account</h1>
          <p className="subtitle">Create your account and verify your email with a 6-digit OTP.</p>
          <form onSubmit={submit}>
            <div className="field"><label>FULL NAME</label><div className="search-box"><User size={16} /><input value={name} onChange={e => setName(e.target.value)} placeholder="Your name" required /></div></div>
            <div className="field"><label>EMAIL</label><div className="search-box"><Mail size={16} /><input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div></div>
            <div className="field"><label>PASSWORD</label><div className="search-box"><Lock size={16} /><input type={showPassword ? "text" : "password"} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 6 characters" required /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword(v => !v)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></div>
            <button className="analyze" disabled={busy} type="submit">{busy ? <><Loader2 size={17} className="spin" /> Sending OTP...</> : <>Continue<ArrowRight size={18} /></>}</button>
            {(localError || error) && <div className="error">{localError || error}</div>}
          </form>
        </> : <>
          <h1>Verify your email</h1>
          <p className="subtitle">We sent a 6-digit OTP to <b>{email}</b>. It expires in 10 minutes.</p>
          <form onSubmit={verify}>
            <div className="field"><label>EMAIL OTP</label><div className="search-box"><Mail size={16} /><input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="Enter 6-digit OTP" required /></div></div>
            <button className="analyze" disabled={busy} type="submit">{busy ? <><Loader2 size={17} className="spin" /> Verifying...</> : <>Verify email<ArrowRight size={18} /></>}</button>
            <button className="secondary-action" disabled={busy} type="button" onClick={resend}>Resend OTP</button>
            {message && <div className="success-message">{message}</div>}
            {(localError || error) && <div className="error">{localError || error}</div>}
          </form>
        </>}
        <p className="auth-switch">Already have an account? <button onClick={onSwitchToLogin}>Log in</button></p>
      </div>
    </main>
  );
}
