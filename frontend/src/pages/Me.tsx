import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Profile from "./Profile";
import ProfileInfo from "./ProfileInfo";
import Documents from "./Documents";
import Accounts from "./Accounts";
import Companies from "./Companies";
import Settings from "./Settings";
import Jobs from "./Jobs";
import Matches from "./Matches";
import Applications from "./Applications";
import Tasks from "./Tasks";

const TABS = [
  ["info", "personalInfo", ProfileInfo],
  ["profile", "aiPortrait", Profile],
  ["documents", "myFiles", Documents],
  ["accounts", "accounts", Accounts],
  ["companies", "companies", Companies],
  ["settings", "settings", Settings],
  ["jobs", "jobBoard", Jobs],
  ["matches", "myMatches", Matches],
  ["applications", "applications", Applications],
  ["tasks", "tasks", Tasks],
] as const;

/** 我的資料：身份感知 + 聚合所有功能於一頁（Tab 切換） */
export default function Me() {
  const { t } = useT();
  const [tab, setTab] = useState<string>("profile");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");

  useEffect(() => {
    api<{ full_name: string | null; email: string | null }>("/api/me")
      .then((m) => {
        if (m.full_name) setName(m.full_name);
        else if (m.email) setName(m.email.split("@")[0]);
      })
      .catch(() => {});
  }, []);

  async function saveName() {
    const n = input.trim();
    if (!n) return;
    await api("/api/me", { method: "PATCH", body: JSON.stringify({ full_name: n }) });
    setName(n);
    setEditing(false);
  }

  const Current = TABS.find((x) => x[0] === tab)?.[2] ?? Profile;

  return (
    <div className="me-page">
      <div className="identity-bar">
        <div className="identity-avatar">{name ? name.slice(0, 1).toUpperCase() : "👤"}</div>
        {editing ? (
          <>
            <input value={input} onChange={(e) => setInput(e.target.value)} autoFocus
                   onKeyDown={(e) => e.key === "Enter" && void saveName()} />
            <button onClick={() => void saveName()}>{t("save")}</button>
            <button className="ghost" onClick={() => setEditing(false)}>✕</button>
          </>
        ) : (
          <>
            <div className="identity-name">{name || "—"}</div>
            <button
              className="ghost small"
              onClick={() => {
                setInput(name);
                setEditing(true);
              }}
            >
              {t("edit")}
            </button>
          </>
        )}
      </div>
      <div className="tab-bar">
        {TABS.map(([key, labelKey]) => (
          <button key={key} className={tab === key ? "tab active" : "tab"} onClick={() => setTab(key)}>
            {t(labelKey)}
          </button>
        ))}
      </div>
      <div className="tab-content">
        <Current />
      </div>
    </div>
  );
}
