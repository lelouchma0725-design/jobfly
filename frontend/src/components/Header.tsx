import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { signOut } from "../lib/auth";
import { api } from "../lib/api";

/** 極簡導航：首頁（AI 管家）｜我的資料｜管理後台（僅管理員）｜退出 */
export default function Header() {
  const [role, setRole] = useState("");
  useEffect(() => {
    api<{ role: string }>("/api/me").then((m) => setRole(m.role)).catch(() => {});
  }, []);

  return (
    <header>
      <h1>
        <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
          JobFly<span className="muted"> · AI 求職管家</span>
        </Link>
      </h1>
      <nav>
        <Link to="/">首頁</Link>
        <Link to="/me">我的資料</Link>
        {role === "admin" && <Link to="/admin">管理後台</Link>}
        <button className="ghost" onClick={() => void signOut()}>
          退出
        </button>
      </nav>
    </header>
  );
}
