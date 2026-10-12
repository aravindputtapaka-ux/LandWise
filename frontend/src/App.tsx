import { useEffect, useRef, useState } from "react";
import { useAuth } from "./auth/AuthContext";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ForgotPassword from "./pages/ForgotPassword";
import ChatWidget from "./components/ChatWidget";
import History from "./pages/History";
import Estimator from "./pages/Estimator";
import type { Result } from "./pages/Estimator";
import GuestChatWidget from "./components/GuestChatWidget";
import "./styles.css";

type View = "landing" | "login" | "signup" | "forgot" | "app" | "history";

function LandingWithVideo({ onLogin, onSignup }: {
  onLogin: () => void;
  onSignup: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const applyPreference = () => {
      if (preference.matches) video.pause();
      else void video.play().catch(() => setPlaying(false));
    };
    applyPreference();
    preference.addEventListener("change", applyPreference);
    return () => {
      preference.removeEventListener("change", applyPreference);
      video.pause();
    };
  }, []);

  const toggleVideo = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => setPlaying(false));
    else video.pause();
  };

  return (
    <div className="lw-video-page">
      <video
        ref={videoRef}
        className="lw-video-background"
        src="/videos/landing-background.mp4"
        loop
        muted
        playsInline
        preload="metadata"
        aria-hidden="true"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => { setVideoFailed(true); setPlaying(false); }}
      />
      <div className="lw-video-overlay" aria-hidden="true" />
      <div className="lw-video-content">
        <Landing onLogin={onLogin} onSignup={onSignup} />
      </div>
      {/* {!videoFailed && (
        <button type="button" className="lw-video-toggle" onClick={toggleVideo}>
          {playing ? "Pause background video" : "Play background video"}
        </button>
      )} */}
    </div>
  );
}

export default function App() {
  const { user, token, ready, logout } = useAuth();
  const [view, setView] = useState<View>("landing");
  const [openResult, setOpenResult] = useState<{
    result: Result;
    mode: "price" | "affordability";
  } | null>(null);

  const handleLogout = () => {
    logout();
    setOpenResult(null);
    setView("landing");
  };

  if (!ready) {
    return (
      <main className="app" aria-label="Loading LandWise" aria-busy="true">
        <div className="background-glow glow-a" />
        <div className="background-glow glow-b" />
      </main>
    );
  }

  if (user && token) {
    if (view === "history") {
      return (
        <>
          <History
            token={token}
            onBack={() => { setOpenResult(null); setView("app"); }}
            onLogout={handleLogout}
            onOpen={(result, mode) => {
              setOpenResult({ result, mode });
              setView("app");
            }}
          />
          <ChatWidget key={user.id} token={token} />
        </>
      );
    }
    return (
      <>
        <Estimator
          token={token}
          userName={user.name}
          onLogout={handleLogout}
          onOpenHistory={() => setView("history")}
          initialResult={openResult}
        />
        <ChatWidget key={user.id} token={token} />
      </>
    );
  }

  if (view === "login") {
    return (
      <Login
        onBack={() => setView("landing")}
        onSwitchToSignup={() => setView("signup")}
        onForgot={() => setView("forgot")}
        onSuccess={() => setView("app")}
      />
    );
  }
  if (view === "signup") {
    return (
      <Signup
        onBack={() => setView("landing")}
        onSwitchToLogin={() => setView("login")}
        onSuccess={() => setView("app")}
      />
    );
  }
  if (view === "forgot") {
    return (
      <ForgotPassword
        onBack={() => setView("login")}
        onLogin={() => setView("login")}
      />
    );
  }

  return (
    <>
      <LandingWithVideo
        onLogin={() => setView("login")}
        onSignup={() => setView("signup")}
      />
      <GuestChatWidget
        onLogin={() => setView("login")}
        onSignup={() => setView("signup")}
      />
    </>
  );
}
