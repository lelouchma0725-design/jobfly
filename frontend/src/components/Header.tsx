import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { api } from "../lib/api";

export default function Header() {
  const [role, setRole] = useState("");
  useEffect(() => {
    api<{ role: string }>("/api/me").then((m) => setRole(m.role)).catch(() => {});
  }, []);

  async function signOut() {
    await supabase.auth.signOut();
  }
  return (
    <header>
      <h1>JobFly</h1>
      <nav>
        <Link to="/">首頁</Link>
        <Link to="/jobs">崗位庫</Link>
        <Link to="/matches">我的匹配</Link>
        <Link to="/applications">投遞記錄</Link>
        <Link to="/tasks">待處理</Link>
        <Link to="/documents">我的文件</Link>
        <Link to="/profile">我的畫像</Link>
        <Link to="/accounts">平台帳號</Link>
        <Link to="/companies">關注公司</Link>
        <Link to="/settings">投遞設置</Link>
        {role === "admin" && <Link to="/admin">管理後台</Link>}
        <button className="ghost" onClick={signOut}>
          退出
        </button>
      </nav>
    </header>
  );
}
