import { useState } from "react";

declare global {
  namespace JSX {
    interface IntrinsicElements {
      "earth-chatbot": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement>,
        HTMLElement
      > & {
        duration?: string;
      };
    }
  }
}

type Props = {
  onLogin: () => void;
  onSignup: () => void;
};

export default function GuestChatWidget({
  onLogin,
  onSignup,
}: Props) {
  const [open, setOpen] = useState(false);

  function navigate(action: () => void) {
    setOpen(false);
    action();
  }

  return (
    <>
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

      {open && (
        <section
          className="lw-chat lw-guest-chat"
          aria-label="LandWise assistant"
        >
          <header className="lw-chat-head">
            <div>
              <strong>LandWise assistant</strong>
              <small>Your property questions, explained simply.</small>
            </div>

            <button
              type="button"
              aria-label="Close chat"
              onClick={() => setOpen(false)}
            >
              ✕
            </button>
          </header>

          <div className="lw-chat-messages">
            <article className="lw-message lw-assistant">
              <small>LandWise</small>

              <div>
                Welcome to LandWise! 👋
                {"\n\n"}
                Please log in or sign up to start a conversation.
                {"\n\n"}
                Once you’re signed in, I can explain property
                estimates, affordability, and your saved searches.
              </div>
            </article>

            <div className="lw-guest-actions">
              <button
                type="button"
                onClick={() => navigate(onLogin)}
              >
                Log in
              </button>

              <button
                type="button"
                onClick={() => navigate(onSignup)}
              >
                Create an account
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}