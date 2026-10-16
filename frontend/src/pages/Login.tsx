import { useState } from "react";
import { magicLink, signIn, signUp } from "../lib/auth";
import type { AuthSession } from "../lib/auth";

export default function Login({ onLogin }: { onLogin: (s: AuthSession) => void }) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!email || !password) return setMsg("請填寫郵箱和密碼");
    setBusy(true);
    setMsg("");
    try {
      if (mode === "signin") {
        onLogin(await signIn(email, password));
      } else {
        const r = await signUp(email, password);
        setMsg(
          r.status === "ok"
            ? "註冊成功，正在進入…（自動登錄）"
            : "註冊成功！請到郵箱點擊確認連結後再登錄。",
        );
        if (r.status === "ok") {
          const s = await signIn(email, password);
          onLogin(s);
        }
      }
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendMagic() {
    if (!email) return setMsg("請填寫郵箱");
    setBusy(true);
    setMsg("");
    try {
      await magicLink(email);
      setMsg("已發送登錄連結，請查收郵箱");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center column" style={{ minHeight: "100vh" }}>
      <div className="card">
        <h1>JobsComing 求職投遞助手</h1>
        <p className="muted">郵箱登錄（公共用戶可自助註冊）</p>
        <input
          type="email"
          placeholder="郵箱"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="密碼（至少 6 位）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
        />
        <button disabled={busy} onClick={() => void submit()}>
          {mode === "signin" ? "登錄" : "註冊並登錄"}
        </button>
        <button className="ghost" disabled={busy} onClick={() => void sendMagic()}>
          發送郵箱登錄連結
        </button>
        <button
          className="ghost"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setMsg("");
          }}
        >
          {mode === "signin" ? "沒有帳號？註冊" : "已有帳號？登錄"}
        </button>
        {msg && <p className="notice">{msg}</p>}
      </div>
    </div>
  );
}
