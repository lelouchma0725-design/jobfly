import { useState } from "react";
import { supabase } from "../lib/supabase";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function signIn() {
    setBusy(true);
    setMsg("");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setMsg(error.message);
  }

  async function magicLink() {
    setBusy(true);
    setMsg("");
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin },
    });
    setBusy(false);
    setMsg(error ? error.message : "已發送登錄連結，請查收郵箱");
  }

  return (
    <div className="center column" style={{ minHeight: "100vh" }}>
      <div className="card">
        <h1>JobFly 求職投遞助手</h1>
        <p className="muted">郵箱登錄（手機號登錄需在 Supabase 配置短信商後啟用）</p>
        <input
          type="email"
          placeholder="郵箱"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="密碼"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && signIn()}
        />
        <button disabled={busy} onClick={signIn}>
          登錄
        </button>
        <button className="ghost" disabled={busy} onClick={magicLink}>
          發送郵箱登錄連結
        </button>
        {msg && <p className="notice">{msg}</p>}
      </div>
    </div>
  );
}
