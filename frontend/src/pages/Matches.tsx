import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Pager from "../components/Pager";

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
  const { t } = useT();
  const [items, setItems] = useState<Match[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [company, setCompany] = useState("");
  const [companies, setCompanies] = useState<{ company_name: string; count: number; top_score: number | null }[]>([]);
  const [msg, setMsg] = useState("");
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.set("status", status);
    if (company) params.set("company", company);
    try {
      const r = await api<{ items: Match[]; total: number }>(`/api/matches?${params}`);
      setItems(r.items);
      setTotal(r.total);
    } catch {
      setMsg("讀取匹配結果失敗");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, company, limit, offset]);
  useEffect(() => {
    api<{ company_name: string; count: number; top_score: number | null }[]>("/api/matches/companies")
      .then(setCompanies)
      .catch(() => {});
  }, []);

  async function rematch() {
    setMsg("正在後台全量重新匹配（補評缺失崗位 + 重算舊分數）…");
    try {
      await api("/api/matches/rematch", { method: "POST" });
      // 輪詢進度直到全部補評完成
      let tries = 0;
      const timer = window.setInterval(async () => {
        tries += 1;
        try {
          const st = await api<{ remaining_missing: number; total_matches: number }>("/api/matches/rematch-status");
          setMsg(`重新匹配中… 剩餘未評分 ${st.remaining_missing} 個（已匹配 ${st.total_matches} 個）`);
          if (st.remaining_missing === 0 || tries > 60) {
            window.clearInterval(timer);
            setMsg(st.remaining_missing === 0 ? "✅ 全部崗位已匹配完成" : "匹配仍在後台進行，可稍後再點「刷新」");
            await load();
          }
        } catch {
          window.clearInterval(timer);
        }
      }, 5000);
    } catch (e) {
      setMsg(`重新匹配失敗: ${(e as Error).message}`);
    }
  }

  return (
    <div>
      <main>
        <div className="card wide">
          <h2>{t("myMatches")}</h2>
          <div className="row wrap">
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">{t("all")}</option>
              {Object.entries(STATUS_TEXT).map(([v, s]) => (
                <option key={v} value={v}>
                  {s}
                </option>
              ))}
            </select>
            <input
              placeholder="公司篩選（輸入即篩選，如：中信）"
              value={company}
              onChange={(e) => {
                setCompany(e.target.value);
                setOffset(0);
              }}
            />
            <button className="ghost" onClick={() => { void load(); setMsg("已刷新"); }}>
              🔃 刷新
            </button>
            <button className="ghost" onClick={() => void rematch()}>
              🔄 重新匹配
            </button>
          </div>
          <p className="muted">重新匹配會用你當前畫像重算所有崗位貼合度（後台執行，稍後刷新）。</p>
          <table>
            <thead>
              <tr>
                <th>{t("company")}</th>
                <th>{t("jobTitle")}</th>
                <th>{t("fitScore")}</th>
                <th>{t("status")}</th>
                <th>{t("reasons")}</th>
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
                  <td className="muted cell-wrap">{m.reasons.join("；") || "—"}</td>
                  <td>
                    {m.apply_url && (
                      <a href={m.apply_url} target="_blank" rel="noreferrer">
                        {t("openApply")}
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager
            total={total}
            limit={limit}
            offset={offset}
            onPage={(o) => setOffset(o)}
            onLimit={(l) => {
              setLimit(l);
              setOffset(0);
            }}
          />
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
