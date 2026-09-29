import { useState } from "react";
import { useAuth } from "./auth/AuthContext";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ForgotPassword from "./pages/ForgotPassword";
import History from "./pages/History";
import Estimator from "./pages/Estimator";
import type { Result } from "./pages/Estimator";

type View = "landing" | "login" | "signup" | "forgot" | "app" | "history";

export default function App() {
  const { user, token, ready, logout } = useAuth();
  const [view, setView] = useState<View>("landing");
  const [openResult, setOpenResult] = useState<{ result: Result; mode: "price" | "affordability" } | null>(null);

  if (!ready) {
    return <main className="app"><div className="background-glow glow-a" /><div className="background-glow glow-b" /></main>;
  }

  if (user && token) {
    if (view === "history") {
      return (
        <History
          token={token}
          onBack={() => { setOpenResult(null); setView("app"); }}
          onLogout={() => { logout(); setView("landing"); }}
          onOpen={(result, mode) => { setOpenResult({ result, mode }); setView("app"); }}
        />
      );
    }
    return (
      <Estimator
        token={token}
        userName={user.name}
        onLogout={() => { logout(); setOpenResult(null); setView("landing"); }}
        onOpenHistory={() => setView("history")}
        initialResult={openResult}
      />
    );
  }

  if (view === "login") {
    return <Login onBack={() => setView("landing")} onSwitchToSignup={() => setView("signup")} onForgot={() => setView("forgot")} onSuccess={() => setView("app")} />;
  }
  if (view === "signup") {
    return <Signup onBack={() => setView("landing")} onSwitchToLogin={() => setView("login")} onSuccess={() => setView("app")} />;
  }
  if (view === "forgot") {
    return <ForgotPassword onBack={() => setView("login")} onLogin={() => setView("login")} />;
  }
  return <Landing onLogin={() => setView("login")} onSignup={() => setView("signup")} />;
}
