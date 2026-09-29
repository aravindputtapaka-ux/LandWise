import { useEffect, useState } from "react";
import { ArrowLeft, Clock, Loader2, MapPin, Target, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import type { Result } from "./Estimator";

type HistoryItem = { id: string; type: string; request: Record<string, any>; response: Record<string, any>; created_at: string };

function money(n: number, c: string) { try { return new Intl.NumberFormat("en-IN", { style: "currency", currency: c || "INR", maximumFractionDigits: n < 1000 ? 2 : 0 }).format(n); } catch { return `${c || ""} ${Math.round(n).toLocaleString("en-IN")}`; } }

export default function History({ token, onBack, onLogout, onOpen }: { token: string; onBack: () => void; onLogout: () => void; onOpen: (result: Result, mode: "price" | "affordability") => void }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setError("");
    try {
      const rows = await api<HistoryItem[]>("/auth/history", { token });
      setItems(rows);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { onLogout(); return; }
      setError(e instanceof Error ? e.message : "Could not load your search history.");
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function remove(id: string) {
    setBusyId(id);
    try {
      await api(`/auth/history/${id}`, { method: "DELETE", token });
      setItems(prev => (prev || []).filter(i => i.id !== id));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { onLogout(); return; }
    } finally { setBusyId(null); }
  }

  return (
    <main className="results-page">
      <div className="results-shell">
        <div className="results-head"><button className="back-button" onClick={onBack}><ArrowLeft size={16} /> Back to search</button></div>
        <div className="result-title">
          <div><div className="eyebrow">YOUR ACCOUNT</div><h1>Search history</h1></div>
        </div>

        {items === null && !error && <div className="panel history-empty"><Loader2 size={18} className="spin" /> Loading your history...</div>}
        {error && <div className="error">{error}</div>}
        {items && items.length === 0 && <div className="panel history-empty"><Clock size={20} /> No searches yet. Run a property or affordability search and it will show up here.</div>}

        <div className="history-list">
          {(items || []).map(h => {
            const r = h.response as Result;
            const isPrice = h.type === "property_price";
            const isAfford = h.type === "affordability";
            const headline = isPrice
              ? money(r.estimated_total_price ?? r.price_per_unit ?? 0, r.currency || "INR")
              : isAfford
              ? (r.affordable_area ? `${Math.round(r.affordable_area).toLocaleString("en-IN")} sq ft` : `${(r.options || []).filter((o: any) => o.available).length} affordable options`)
              : `${(h.response as any)?.inserted ?? 0} sources ingested`;
            return (
              <div className="panel history-item" key={h.id}>
                <div className="history-item-icon">{isAfford ? <Target size={16} /> : <MapPin size={16} />}</div>
                <div className="history-item-body">
                  <div className="history-item-top">
                    <strong>{r.location || h.request?.location || "Unknown location"}</strong>
                    <span className="history-item-date">{new Date(h.created_at).toLocaleString()}</span>
                  </div>
                  <div className="history-item-meta">
                    <span>{isPrice ? "Price estimate" : isAfford ? "Affordability" : "Source ingest"}</span>
                    {r.property_type && <span>{r.property_type.replace("_", " ")}</span>}
                    {r.bhk && <span>{r.bhk}</span>}
                  </div>
                  <div className="history-item-value">{headline}</div>
                </div>
                <div className="history-item-actions">
                  {(isPrice || isAfford) && <button className="ghost-btn" onClick={() => onOpen(r, isAfford ? "affordability" : "price")}>View</button>}
                  <button className="ghost-btn danger" disabled={busyId === h.id} onClick={() => remove(h.id)}>{busyId === h.id ? <Loader2 size={13} className="spin" /> : <Trash2 size={13} />}</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </main>
  );
}
