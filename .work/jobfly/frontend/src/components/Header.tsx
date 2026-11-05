import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { signOut } from "../lib/auth";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

/** 極簡導航：首頁（AI 管家）｜我的資料｜管理後台（僅管理員）｜語言｜退出 */
export default function Header() {
  const { t, lang, setLang } = useT();
  const [role, setRole] = useState("");
  const [name, setName] = useState("");
  useEffect(() => {
    api<{ role: string; full_name: string | null }>("/api/me")
      .then((m) => {
        setRole(m.role);
        if (m.full_name) setName(m.full_name);
      })
      .catch(() => {});
  }, []);

  return (
    <header>
      <h1>
        <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
          JobsComing<span className="muted"> · {t("aiAssistant")}</span>
        </Link>
      </h1>
      <nav>
        <Link to="/">{t("home")}</Link>
        <Link to="/me">{t("myData")}</Link>
        {role === "admin" && <Link to="/admin">{t("admin")}</Link>}
        <span className="muted">{name ? `${t("hello")}${name}` : ""}</span>
        <button className="ghost small" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
          {lang === "zh" ? "EN" : "中文"}
        </button>
        <button className="ghost" onClick={() => void signOut()}>
          {t("logout")}
        </button>
      </nav>
    </header>
  );
}
