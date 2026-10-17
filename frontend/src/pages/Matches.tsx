import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Pager from "../components/Pager";

type Match = {
  id: string;
  posting_id: string;
  match_score: number | null;
  priority_score: number | null;
  is_campus: boolean;
  org_level: string;
  department: string | null;
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

const ORG_TEXT: Record<string, string> = {
  headquarter: "總部",
  branch: "分支機構",
  unknown: "—",
};

export default function Matches() {
  const { t } = useT();
  const [items, setItems] = useState<Match[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [campus, setCampus] = useState("");
  const [org, setOrg] = useState("");
  // 輸入框與實際查詢條件分離：只有點「查詢」才觸發
  const [companyInput, setCompanyInput] = useState("");
  const [company, setCompany] = useState("");
  const [msg, setMsg] = useState("");
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.set("status", status);
    if (campus) params.set("campus", campus);
    if (org) params.set("org", org);
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
  }, [status, company, campus, org, limit, offset]);

  async function rematch(onlyCompany: boolean) {
    setMsg(onlyCompany ? "正在後台重新匹配該公司…" : "正在後台全量重新匹配…");
    try {
      await api("/api/matches/rematch", {
        method: "POST",
        body: JSON.stringify({ company: onlyCompany ? company || null : null }),
      });
      let tries = 0;
      const timer = window.setInterval(async () => {
        tries += 1;
        try {
          const st = await api<{ remaining_missing: number; total_matches: number }>(
            "/api/matches/rematch-status",
          );
          setMsg(`重新匹配中… 剩餘未評分 ${st.remaining_missing} 個（已匹配 ${st.total_matches} 個）`);
          if (st.remaining_missing === 0 || tries > 60) {
            window.clearInterval(timer);
            setMsg(st.remaining_missing === 0 ? "✅ 匹配完成" : "仍在後台進行，可稍後再點「刷新」");
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
            <input
              placeholder="公司篩選（輸入後點「查詢」）"
              value={companyInput}
              onChange={(e) => setCompanyInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setCompany(companyInput);
                  setOffset(0);
                }
              }}
            />
            <button
              onClick={() => {
                setCompany(companyInput);
                setOffset(0);
              }}
            >
              查詢
            </button>
            <select
              value={campus}
              onChange={(e) => {
                setCampus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">校招/社招：全部</option>
              <option value="campus">僅校招</option>
              <option value="society">僅社招</option>
            </select>
            <select
              value={org}
              onChange={(e) => {
                setOrg(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">總部/分支：全部</option>
              <option value="headquarter">僅總部</option>
              <option value="branch">僅分支機構</option>
            </select>
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">狀態：全部</option>
              {Object.entries(STATUS_TEXT).map(([v, s]) => (
                <option key={v} value={v}>
                  {s}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={() => void load()}>
              🔃 刷新
            </button>
            <button className="ghost" onClick={() => void rematch(!!company)}>
              🔄 {company ? `重新匹配「${company}」` : "全量重新匹配"}
            </button>
          </div>
          <p className="muted">
            貼合度 = 純個人條件匹配；優先級 = 貼合度 + 地區/校招職級/總部分支偏好加權（投遞按優先級選崗位）。
            {company && " 篩選公司時「重新匹配」只匹配該公司（省時）。"}
          </p>
          <table>
            <thead>
              <tr>
                <th>{t("company")}</th>
                <th>{t("jobTitle")}</th>
                <th>類型</th>
                <th>部門</th>
                <th>{t("fitScore")}</th>
                <th>優先級</th>
                <th>{t("status")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>{m.company_name}</td>
                  <td>{m.title}</td>
                  <td>
                    {m.is_campus ? "校招" : "社招"} · {ORG_TEXT[m.org_level] ?? m.org_level}
                  </td>
                  <td className="muted">{m.department ?? "—"}</td>
                  <td>
                    <b>{m.match_score != null ? `${m.match_score}%` : "不符"}</b>
                  </td>
                  <td>{m.priority_score != null ? `${m.priority_score}%` : "—"}</td>
                  <td>{STATUS_TEXT[m.status] ?? m.status}</td>
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
