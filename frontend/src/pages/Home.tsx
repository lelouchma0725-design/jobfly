import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type Msg = { role: "user" | "assistant"; content: string };

export default function Home() {
  const { t } = useT();
  const [messages, setMessages] = useState<Msg[]>([{ role: "assistant", content: t("welcome") }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || busy) return;
    setInput("");
    setBusy(true);
    const next: Msg[] = [...messages, { role: "user", content }];
    setMessages(next);
    try {
      const r = await api<{ reply: string }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ messages: next.map((m) => ({ role: m.role, content: m.content })) }),
      });
      setMessages([...next, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `抱歉，出了點問題：${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-box">
        <div className="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              <div className="chat-avatar">{m.role === "assistant" ? "🤖" : "👤"}</div>
              <div className="chat-bubble">{m.content}</div>
            </div>
          ))}
          {busy && (
            <div className="chat-msg assistant">
              <div className="chat-avatar">🤖</div>
              <div className="chat-bubble typing">{t("thinking")}</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <div className="chat-quick">
          {[t("quickStatus"), t("quickGuide"), t("quickCollect"), t("quickMatches"), t("quickApps")].map((q) => (
            <button key={q} className="ghost small" disabled={busy} onClick={() => void send(q)}>
              {q}
            </button>
          ))}
        </div>
        <div className="chat-input">
          <input
            placeholder={t("chatPlaceholder")}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void send()}
          />
          <button disabled={busy} onClick={() => void send()}>
            {t("send")}
          </button>
        </div>
      </div>
    </div>
  );
}
