import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type Msg = { role: "user" | "assistant"; content: string };
type Conv = { id: string; title: string; updated_at: string; messages_count: number };

export default function Home() {
  const { t } = useT();
  const [messages, setMessages] = useState<Msg[]>([{ role: "assistant", content: t("welcome") }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showQuick, setShowQuick] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [convs, setConvs] = useState<Conv[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    api<Conv[]>("/api/chat/conversations")
      .then(setConvs)
      .catch(() => {});
  }, [messages]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || busy) return;
    setInput("");
    setBusy(true);
    const next: Msg[] = [...messages, { role: "user", content }];
    setMessages(next);
    try {
      const r = await api<{ reply: string; conversation_id: string }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: next.map((m) => ({ role: m.role, content: m.content })),
          conversation_id: convId,
        }),
      });
      setConvId(r.conversation_id);
      setMessages([...next, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `抱歉，出了點問題：${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function openConv(id: string) {
    try {
      const r = await api<{ messages: Msg[] }>(`/api/chat/conversations/${id}`);
      setConvId(id);
      setMessages(r.messages ?? []);
    } catch {
      /* 忽略 */
    }
  }

  async function delConv(id: string) {
    if (!confirm("刪除這段問答記錄？")) return;
    await api(`/api/chat/conversations/${id}`, { method: "DELETE" });
    if (convId === id) {
      setConvId(null);
      setMessages([{ role: "assistant", content: t("welcome") }]);
    }
    setConvs(convs.filter((c) => c.id !== id));
  }

  function newChat() {
    setConvId(null);
    setMessages([{ role: "assistant", content: t("welcome") }]);
  }

  return (
    <div className="chat-page">
      <div className="chat-sidebar">
        <button className="ghost small" onClick={newChat}>
          ＋ 新對話
        </button>
        <div className="conv-list">
          {convs.map((c) => (
            <div key={c.id} className={`conv-item ${c.id === convId ? "active" : ""}`}>
              <button className="conv-title" onClick={() => void openConv(c.id)}>
                {c.title}
              </button>
              <button className="conv-del" onClick={() => void delConv(c.id)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>
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
        <div className="chat-input">
          <div
            className="quick-toggle"
            onMouseEnter={() => setShowQuick(true)}
            onMouseLeave={() => setShowQuick(false)}
          >
            <button className="ghost small" onClick={() => setShowQuick(!showQuick)} title="快捷操作">
              💡
            </button>
            {showQuick && (
              <div className="quick-pop">
                {[t("quickStatus"), t("quickGuide"), t("quickCollect"), t("quickMatches"), t("quickApps")].map(
                  (q) => (
                    <button
                      key={q}
                      className="ghost small"
                      disabled={busy}
                      onClick={() => {
                        setShowQuick(false);
                        void send(q);
                      }}
                    >
                      {q}
                    </button>
                  ),
                )}
              </div>
            )}
          </div>
          <textarea
            placeholder={t("chatPlaceholder")}
            value={input}
            rows={1}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button disabled={busy} onClick={() => void send()}>
            {t("send")}
          </button>
        </div>
      </div>
    </div>
  );
}
