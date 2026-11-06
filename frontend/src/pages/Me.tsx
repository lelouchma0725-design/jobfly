import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Profile from "./Profile";
import ProfileInfo from "./ProfileInfo";
import Documents from "./Documents";
import Accounts from "./Accounts";
import Companies from "./Companies";
import Settings from "./Settings";
import MatchJobs from "./MatchJobs";
import { getKeyB64, setKeyB64, unwrapKeyWithCode } from "../lib/crypto";
import { emitUnlockChange, gateEnabled, isUnlocked, refreshGate, setUnlocked } from "../lib/unlock";
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
  ["matchjobs", "matchJobs", MatchJobs],
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
  const GATED_TABS = new Set(["profile", "matchjobs", "applications", "tasks"]);
  const [unlocked, setUnlockedState] = useState(isUnlocked());
  const [gateOn, setGateOn] = useState(gateEnabled());
  useEffect(() => {
    void refreshGate().then((has) => setGateOn(has));
  }, []);
  const [keyInput, setKeyInput] = useState("");
  const [gateMsg, setGateMsg] = useState("");

  async function doUnlockHere() {
    const k = keyInput.trim();
    if (!k) return setGateMsg("請輸入安全密鑰");
    try {
      const r = await api<{ wrapped_key: string | null }>("/api/me/e2ee/unlock-wrapped");
      if (!r.wrapped_key) return setGateMsg("尚未設置安全密鑰，請先到「個人信息→安全」生成");
      const e2ee = await unwrapKeyWithCode(r.wrapped_key, k);
      setKeyB64(e2ee);
      setUnlocked(true);
      emitUnlockChange();
      setUnlockedState(true);
    } catch {
      setGateMsg("安全密鑰不正確");
    }
  }

  if (GATED_TABS.has(tab) && gateOn && !unlocked) {
    return (
      <main>
        <div className="card" style={{ maxWidth: 520, margin: "60px auto" }}>
          <h2>🔐 核心功能需要安全密鑰解鎖</h2>
          <p className="muted">
            本頁內容（AI 畫像/匹配結果/投遞記錄）屬於第二層核心數據，請輸入安全密鑰解鎖後查看。
          </p>
          <input
            placeholder="輸入安全密鑰"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
          />
          <button onClick={() => void doUnlockHere()}>解鎖</button>
          {gateMsg && <p className="notice">{gateMsg}</p>}
        </div>
      </main>
    );
  }

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
