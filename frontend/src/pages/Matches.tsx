import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Header from "../components/Header";

type Match = {
  id: string;
  posting_id: string;
  match_score: number | null;
  hard_failures: unknown[];
  reasons: string[];
  status: string;
  company_name: string;
  title: string;
  location: string | null;
  apply_url: string | null;
};

const STATUS_TEXT: Record<string, string> = {
  new: "待處理",
  pushed: "已推送",
  applying: "投遞中",
  applied: "已投遞",
  hard_failed: "硬性不符",
  skipped_below_threshold: "低於閾值",
  expired: "已下架",
  ignored: "已忽略",
};

export default function Matches() {
  const [items, setItems] = useState<Match[]>([]);
  const [status, setStatus] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    try {
      setItems(await api<Match[]>(`/api/matches?${params}`));
    } catch {
      setMsg("讀取匹配結果失敗");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div className="page">
      <Header />
      <main className="narrow">
        <div className="card wide">
          <h2>我的崗位匹配（FR-1f）</h2>
          <div className="row">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">全部狀態</option>
              {Object.entries(STATUS_TEXT).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <table>
            <thead>
              <tr>
                <th>公司</th>
                <th>職位</th>
                <th>貼合度</th>
                <th>狀態</th>
                <th>理由</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>{m.company_name}</td>
                  <td>{m.title}</td>
                  <td>
                    <b>{m.match_score != null ? `${m.match_score}%` : "不符"}</b>
                  </td>
                  <td>{STATUS_TEXT[m.status] ?? m.status}</td>
                  <td className="muted">{m.reasons.join("；") || "—"}</td>
                  <td>
                    {m.apply_url && (
                      <a href={m.apply_url} target="_blank" rel="noreferrer">
                        申請頁 ↗
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
