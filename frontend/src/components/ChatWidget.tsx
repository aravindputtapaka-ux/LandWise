import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

type Source = { id: string; kind: string; title: string; urls: string[] };
type Message = { id: string; role: 'user' | 'assistant'; content: string; sources: Source[]; request_id?: string };
type Conversation = { id: string; title: string; selected_search_id?: string | null };

function cleanChatText(text: string) {
  return text.replace(/\s*\[\s*\d+(?:\s*,\s*\d+)*\s*\]/g, '').replace(/\n?Retrieved evidence \(\d+\)/gi, '').trim();
}
function Formatted({ text }: { text: string }) {
  const clean = cleanChatText(text);
  return <>{clean.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part)}</>;
}

export default function ChatWidget({ token }: { token: string }) {
  const [open, setOpen] = useState(false);
  const [chats, setChats] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [moreMessages, setMoreMessages] = useState(false);
  const [moreChats, setMoreChats] = useState(false);
  const [pending, setPending] = useState<{ text: string; id: string } | null>(null);
  const [status, setStatus] = useState('');
  const guard = useRef(false);
  const loaded = useRef(false);
  const end = useRef<HTMLDivElement>(null);

  async function refreshChats() {
    const rows = await api<Conversation[]>('/chat/conversations?limit=30', { token });
    setChats(rows); setMoreChats(rows.length === 30);
  }
  async function loadMessages(c: Conversation) {
    const rows = await api<Message[]>(`/chat/conversations/${c.id}/messages?limit=50`, { token });
    setActive(c); setMessages(rows); setMoreMessages(rows.length === 50); setPending(null);
  }
  async function run(action: () => Promise<void>) {
    if (guard.current) return;
    guard.current = true; setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'Request failed.'); }
    finally { guard.current = false; setBusy(false); }
  }
  async function initialize() {
    await run(async () => {
      const s = await api<{ gemini_configured: boolean; knowledge_chunks: number }>('/chat/status', { token });
      setStatus(s.gemini_configured ? `MongoDB connected · ${s.knowledge_chunks} knowledge passages` : 'Set your Gemini key and model in backend/.env.');
      await refreshChats(); loaded.current = true;
    });
  }
  async function newChat(searchId?: string) {
    await run(async () => {
      const c = await api<Conversation>('/chat/conversations', { token, body: { title: searchId ? 'Saved property discussion' : 'Property conversation', selected_search_id: searchId || null } });
      setActive(c); setMessages([]); setMoreMessages(false); setPending(null); setInput('');
      await refreshChats();
    });
  }
  useEffect(() => {
    const ask = (event: Event) => { setOpen(true); void newChat((event as CustomEvent<string>).detail); };
    window.addEventListener('landwise:ask', ask);
    return () => window.removeEventListener('landwise:ask', ask);
  }, [token]);
  useEffect(() => { if (open && !loaded.current) void initialize(); }, [open]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages.length]);

  async function send(retry = false) {
    const text = retry ? pending?.text : input.trim();
    if (!text || guard.current) return;
    const request = retry && pending ? pending : { text, id: crypto.randomUUID() };
    await run(async () => {
      let c = active;
      if (!c) {
        c = await api<Conversation>('/chat/conversations', { token, body: { title: text.slice(0, 80) } });
        setActive(c); setMessages([]);
      }
      setPending(request); setInput('');
      try {
        await api<Message>(`/chat/conversations/${c.id}/messages`, { token, body: { message: request.text, request_id: request.id } });
        setPending(null);
      } finally {
        // Includes a persisted user message even when generation failed.
        const rows = await api<Message[]>(`/chat/conversations/${c.id}/messages?limit=50`, { token });
        setMessages(rows); setMoreMessages(rows.length === 50);
      }
      await refreshChats();
    });
  }

  return <>
    {!open && (
  <button
    onClick={() => setOpen(true)}
    aria-label="Ask LandWise"
    style={{
      position: "fixed",
      bottom: "24px",
      right: "24px",
      width: "72px",
      height: "72px",
      padding: 0,
      border: "none",
      background: "transparent",
      cursor: "pointer",
      zIndex: 1000,
    }}
  >
    <earth-chatbot
    duration="8"
    style={{
      display: "block",
      width: "72px",
      height: "72px",
      pointerEvents: "none",
    }}
    />
  </button>
)}
    {open && <section className="lw-chat" aria-label="LandWise assistant">
      <header className="lw-chat-head"><div><strong>LandWise assistant</strong><small>Your searches. Clear answers.</small></div><button aria-label="Close chat" onClick={() => setOpen(false)}>✕</button></header>
      <div className="lw-chat-tools">
        <select aria-label="Saved conversations" disabled={busy} value={active?.id || ''} onChange={e => { const c = chats.find(x => x.id === e.target.value); if (c) void run(() => loadMessages(c)); }}>
          <option value="">Select a conversation</option>{chats.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
        <button disabled={busy} onClick={() => void newChat()}>New</button>
        <button disabled={busy} aria-label="Refresh conversations" onClick={() => void initialize()}>↻</button>
        {active && <button disabled={busy} onClick={() => { if (window.confirm('Delete this conversation and its messages?')) void run(async () => { await api(`/chat/conversations/${active.id}`, { token, method: 'DELETE' }); setActive(null); setMessages([]); setPending(null); await refreshChats(); }); }}>Delete</button>}
      </div>
      {moreChats && <button className="lw-chat-more" disabled={busy} onClick={() => void run(async () => { const rows = await api<Conversation[]>(`/chat/conversations?skip=${chats.length}&limit=30`, { token }); setChats(prev => [...prev, ...rows]); setMoreChats(rows.length === 30); })}>Load older conversations</button>}
      {active?.selected_search_id && <div className="lw-chat-context">Discussing your selected saved property result</div>}
      <div className="lw-chat-messages" aria-live="polite">
        {moreMessages && active && <button disabled={busy} onClick={() => void run(async () => { const rows = await api<Message[]>(`/chat/conversations/${active.id}/messages?skip=${messages.length}&limit=50`, { token }); setMessages(prev => [...rows, ...prev]); setMoreMessages(rows.length === 50); })}>Load earlier messages</button>}
        {!messages.length && <div className="lw-chat-welcome"><h3>How can I help?</h3><p>Ask about a saved estimate, affordability, or how LandWise works.</p><button onClick={() => setInput('Explain my latest property estimate.')}>Explain my latest estimate</button><button onClick={() => setInput('How does affordability work?')}>How does affordability work?</button><small>Answers use saved evidence, not live market quotes. Selected context is sent to Gemini.</small></div>}
        {messages.map(m => <article key={m.id} className={`lw-message lw-${m.role}`}><small>{m.role === 'user' ? 'You' : 'LandWise'}</small><div><Formatted text={m.content} /></div></article>)}
        {busy && <p className="lw-chat-wait" role="status">Working…</p>}<div ref={end} />
      </div>
      {error && <div className="lw-chat-error" role="alert">{error}{pending && <button disabled={busy} onClick={() => void send(true)}>Retry message</button>}</div>}
      <form className="lw-chat-compose" onSubmit={e => { e.preventDefault(); void send(); }}><textarea aria-label="Your message" placeholder="Ask about your property…" maxLength={4000} value={input} onChange={e => setInput(e.target.value)} disabled={busy} rows={2} /><button disabled={busy || !input.trim()}>Send</button></form>
      <footer className="lw-chat-status">{status || 'Saved conversations are available after connecting to MongoDB.'}</footer>
    </section>}
  </>;
}
