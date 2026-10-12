import { ArrowRight, BarChart3, MapPin, ShieldCheck, Sparkles, Target, TrendingUp } from "lucide-react";

const FEATURES = [
  { icon: <TrendingUp size={18}/>, title: "Real-time comparables", body: "Every estimate is built from current web evidence discovered and extracted live, not a stale dataset." },
  { icon: <ShieldCheck size={18}/>, title: "Evidence-first, no guessing", body: "If there isn't enough validated price + area evidence, LandWise AI tells you instead of inventing a number." },
  { icon: <BarChart3 size={18}/>, title: "Leakage-free ML", body: "A historical model only nudges the estimate when it has proven, validated accuracy — never a hard-coded correction." },
  { icon: <Target size={18}/>, title: "Affordability planning", body: "Turn a budget into purchasable land area, or see what 1–5 BHK homes you can actually afford." },
];

export default function Landing({ onLogin, onSignup }: { onLogin: () => void; onSignup: () => void }) {
  return (
    <main className="app landing">
      <div className="background-glow glow-a" />
      <div className="background-glow glow-b" />
      <div className="landing-shell">
        <header className="topbar landing-topbar">
          <div className="brand"><span className="brand-icon"><Sparkles size={15} /></span><span>LandWise <b>AI</b></span></div>
          <div className="landing-topbar-actions">
            <button className="ghost-btn" onClick={onLogin}>Log in</button>
            <button className="analyze landing-cta-small" onClick={onSignup}>Sign up<ArrowRight size={15} /></button>
          </div>
        </header>

        <section className="landing-hero">
          <div className="eyebrow">PROPERTY PRICE INTELLIGENCE</div>
          <h1 className="landing-title">Know what land and property really cost, right now.</h1>
          <p className="landing-subtitle">LandWise AI searches live web evidence, extracts validated price and area pairs, and blends them with a leakage-free ML model to give you an honest, current estimate — for land, flats, villas, independent houses and commercial property.</p>
          <div className="landing-hero-actions">
            <button className="analyze landing-cta" onClick={onSignup}>Get started free<ArrowRight size={18} /></button>
            <button className="ghost-btn landing-cta-outline" onClick={onLogin}>I already have an account</button>
          </div>
          <div className="powered landing-powered"><Sparkles size={13} /> Tavily search <b>+</b> source extraction <b>+</b> validated comparables <b>+</b> ML</div>
        </section>

        <section className="landing-features">
          {FEATURES.map((f) => (
            <div className="panel landing-feature" key={f.title}>
              <div className="landing-feature-icon">{f.icon}</div>
              <strong>{f.title}</strong>
              <p>{f.body}</p>
            </div>
          ))}
        </section>

        <section className="panel landing-how">
          <div className="panel-title"><MapPin size={16} /> How an estimate is built</div>
          <div className="landing-steps">
            <div><span>1</span><p>Search discovers current listings, auctions and classifieds for your location.</p></div>
            <div><span>2</span><p>Selected pages are extracted and parsed for explicit price + area evidence — no guessed numbers.</p></div>
            <div><span>3</span><p>Comparables are normalized to ₹/sq ft and combined into a weighted, outlier-resistant estimate.</p></div>
            <div><span>4</span><p>A historical ML model applies a small, validated correction only when it has proven accuracy.</p></div>
          </div>
        </section>

        <footer className="landing-footer">
          <span>© {new Date().getFullYear()} LandWise AI. Estimates are evidence-based, not a valuation or legal guarantee.</span>
        </footer>
      </div>
    </main>
  );
}
