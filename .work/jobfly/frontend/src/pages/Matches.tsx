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
  directions: string[];
  direction_scores: { direction: string; match_score: number; reasons: string[] }[];
  hard_failures: unknown[];
  reasons: string[];
  score_breakdown: Record<string, number | string>;
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

const BD_TEXT: Record<string, string> = {
  fit_base: "個人條件匹配（貼合度）",
  location_adjust: "地區偏好加權",
  campus_adjust: "校招職級適配",
  org_adjust: "總部/分支偏好",
};

export default function Matches() {
  const { t } = useT();
  const [items, setItems] = useState<Match[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [campus, setCampus] = useState("");
  const [org, setOrg] = useState("");
  const [companyInput, setCompanyInput] = useState("");
  const [company, setCompany] = useState("");
  const [msg, setMsg] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function expandAll() {
    setExpanded(new Set(items.map((m) => m.id)));
  }

  function collapseAll() {
    setExpanded(new Set());
  }
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
            <button className="ghost" onClick={expandAll}>
              ⬇ 展開全部
            </button>
            <button className="ghost" onClick={collapseAll}>
              ⬆ 收起全部
            </button>
          </div>
          <p className="notice">{msg}</p>
          <p className="muted">
            點擊任意行查看「貼合度分析」（個人條件匹配 + 各項偏好加權 + 匹配理由）。
            {company && " 篩選公司時「重新匹配」只匹配該公司（省時）。"}
          </p>
          <table>
            <thead>
              <tr>
                <th>{t("company")}</th>
                <th>{t("jobTitle")}</th>
                <th>類型</th>
                <th>部門</th>
                <th>優先級</th>
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <>
                  <tr
                    key={m.id}
                    onClick={() => toggleExpand(m.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{m.company_name}</td>
                    <td>{m.title}</td>
                    <td>
                      {m.is_campus ? "校招" : "社招"} · {ORG_TEXT[m.org_level] ?? m.org_level}
                    </td>
                    <td className="muted">{m.department ?? "—"}</td>
                    <td>
                      <b>{m.priority_score != null ? `${m.priority_score}%` : "—"}</b>
                    </td>
                    <td>{STATUS_TEXT[m.status] ?? m.status}</td>
                  </tr>
                  {expanded.has(m.id) && (
                    <tr key={m.id + "-detail"}>
                      <td colSpan={6} className="match-detail">
                        <div className="row wrap" style={{ gap: 18 }}>
                          <div>
                            <h4>貼合度分析</h4>
                            <table className="mini">
                              <tbody>
                                <tr>
                                  <td className="muted">貼合度（個人條件）</td>
                                  <td>
                                    <b>{m.match_score != null ? `${m.match_score}%` : "硬性不符"}</b>
                                  </td>
                                </tr>
                                {Object.entries(m.score_breakdown ?? {})
                                  .filter(([k]) => k !== "fit_base")
                                  .map(([k, v]) => (
                                    <tr key={k}>
                                      <td className="muted">{BD_TEXT[k] ?? k}</td>
                                      <td>
                                        {Number(v) > 0 ? `+${v}` : `${v}`} 分
                                      </td>
                                    </tr>
                                  ))}
                                <tr>
                                  <td className="muted">優先級（排序用）</td>
                                  <td>
                                    <b>{m.priority_score != null ? `${m.priority_score}%` : "—"}</b>
                                  </td>
                                </tr>
                              </tbody>
                            </table>
                          </div>
                          {(m.direction_scores ?? []).length > 0 && (
                            <div>
                              <h4>崗位方向貼合度（逐方向評分）</h4>
                              <table className="mini">
                                <tbody>
                                  {(m.direction_scores ?? []).map((d) => (
                                    <tr key={d.direction}>
                                      <td>{d.direction}</td>
                                      <td>
                                        <b>{d.match_score}%</b>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              <p className="muted">投遞仍為一崗一投（按職位提交，方向在官網申請時選擇）。</p>
                            </div>
                          )}
                          {!(m.direction_scores ?? []).length &&
                            (Array.isArray(m.directions) ? m.directions : []).length > 0 && (
                            <div>
                              <h4>崗位方向</h4>
                              <p className="muted">{(Array.isArray(m.directions) ? m.directions : []).join("、")}</p>
                            </div>
                          )}
                          <div style={{ flex: 1, minWidth: 240 }}>
                            {m.match_score == null ? (
                              <>
                                <h4>硬性不符原因</h4>
                                <ul>
                                  {(m.hard_failures ?? []).map((hf, i) => (
                                    <li key={i} className="notice-text">
                                      {(hf as { requirement?: string }).requirement ?? JSON.stringify(hf)}
                                    </li>
                                  ))}
                                </ul>
                              </>
                            ) : (
                              <>
                                <h4>匹配理由</h4>
                                <ul>
                                  {(m.reasons ?? []).map((r, i) => (
                                    <li key={i}>{r}</li>
                                  ))}
                                  {!(m.reasons ?? []).length && <li className="muted">—</li>}
                                </ul>
                              </>
                            )}
                            {m.apply_url && (
                              <a href={m.apply_url} target="_blank" rel="noreferrer">
                                {t("openApply")}
                              </a>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
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
        </div>
      </main>
    </div>
  );
}
