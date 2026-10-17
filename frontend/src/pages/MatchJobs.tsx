import { useState } from "react";
import Matches from "./Matches";
import Jobs from "./Jobs";

/** 匹配與崗位合一頁：切換查看「我的匹配」或「崗位庫」。 */
export default function MatchJobs() {
  const [view, setView] = useState<"matches" | "jobs">("matches");
  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <button className={view === "matches" ? "" : "ghost"} onClick={() => setView("matches")}>
          ⭐ 我的匹配
        </button>
        <button className={view === "jobs" ? "" : "ghost"} onClick={() => setView("jobs")}>
          📋 崗位庫
        </button>
      </div>
      {view === "matches" ? <Matches /> : <Jobs />}
    </div>
  );
}
