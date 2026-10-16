import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

type Msg = { role: "user" | "assistant"; content: string };

const QUICK_ACTIONS = [
  "我現在的求職狀態如何？",
  "帶我完成第一次投遞設置",
  "立即採集最新崗位",
  "看看我最匹配的崗位",
  "我的投遞進度如何？",
];

export default function Home() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      content:
        "你好！我是你的 AI 求職管家 🤖\n我可以幫你：查看求職狀態、採集最新崗位、分析匹配度、管理投遞進度。\n直接告訴我你想做什麼，或者點下面的快捷操作。",
    },
  ]);
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
              <div className="chat-bubble typing">思考中…</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <div className="chat-quick">
          {QUICK_ACTIONS.map((q) => (
            <button key={q} className="ghost small" disabled={busy} onClick={() => void send(q)}>
              {q}
            </button>
          ))}
        </div>
        <div className="chat-input">
          <input
            placeholder="告訴我你想做什麼…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void send()}
          />
          <button disabled={busy} onClick={() => void send()}>
            發送
          </button>
        </div>
      </div>
    </div>
  );
}
