import { useState } from "react";
import Profile from "./Profile";
import Documents from "./Documents";
import Accounts from "./Accounts";
import Companies from "./Companies";
import Settings from "./Settings";
import Jobs from "./Jobs";
import Matches from "./Matches";
import Applications from "./Applications";
import Tasks from "./Tasks";

const TABS = [
  ["profile", "AI 畫像", Profile],
  ["documents", "我的文件", Documents],
  ["accounts", "平台帳號", Accounts],
  ["companies", "關注公司", Companies],
  ["settings", "投遞設置", Settings],
  ["jobs", "崗位庫", Jobs],
  ["matches", "我的匹配", Matches],
  ["applications", "投遞記錄", Applications],
  ["tasks", "待處理", Tasks],
] as const;

/** 我的資料：聚合所有功能於一頁（Tab 切換），導航保持極簡 */
export default function Me() {
  const [tab, setTab] = useState<string>("profile");
  const Current = TABS.find((t) => t[0] === tab)?.[2] ?? Profile;

  return (
    <div className="me-page">
      <div className="tab-bar">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "tab active" : "tab"}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tab-content">
        <Current />
      </div>
    </div>
  );
}
