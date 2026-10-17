import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Pager from "../components/Pager";

type Job = {
  id: string;
  company_name: string;
  title: string;
  location: string | null;
  department: string | null;
  source: string;
  apply_url: string | null;
  first_seen_at: string;
  match_score: number | null;
  match_status: string | null;
  is_campus: boolean;
  org_level: string;
};

type JobDetail = Job & { description_text: string | null; reasons: string[]; hard_failures: unknown[] };

const STATUS_TEXT: Record<string, string> = {
  new: "新崗位",
  pushed: "已推送",
  applying: "投遞中",
  applied: "已投遞",
  hard_failed: "硬性條件不符",
  skipped_below_threshold: "低於閾值",
};

export default function Jobs() {
  const { t } = useT();
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [company, setCompany] = useState("");
  const [campus, setCampus] = useState("");
  const [org, setOrg] = useState("");
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (q) params.set("q", q);
    if (company) params.set("company", company);
    if (campus) params.set("campus", campus);
    if (org) params.set("org", org);
    try {
      const res = await api<{ items: Job[]; total: number }>(`/api/jobs?${params}`);
      setItems(res.items);
      setTotal(res.total ?? 0);
    } catch {
      setMsg("讀取崗位失敗");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, offset]);

  const [collectOk, setCollectOk] = useState(false);

  async function collect(onlyCompany: boolean) {
    setBusy(true);
    setCollectOk(false);
    setMsg(onlyCompany ? `正在後台採集「${company}」…` : "正在後台採集你的關注公司…");
    try {
      await api("/api/jobs/collect/run", {
        method: "POST",
        body: JSON.stringify({ company: onlyCompany ? company || null : null }),
      });
      // 輪詢採集進度，完成後綠色提示
      let tries = 0;
      const timer = window.setInterval(async () => {
        tries += 1;
        try {
          const st = await api<{ running: boolean; finished_at: string | null; report: Record<string, number> | null }>(
            "/api/jobs/collect-status",
          );
          if (!st.running && st.finished_at) {
            window.clearInterval(timer);
            const rp = st.report ?? {};
            setCollectOk(true);
            setMsg(`✅ 採集完成：新增 ${rp.new ?? 0}，更新 ${rp.updated ?? 0}，匹配 ${rp.matched ?? 0}，錯誤 ${rp.errors ?? 0}。點「刷新」查看最新崗位。`);
            setBusy(false);
          } else if (tries > 60) {
            window.clearInterval(timer);
            setMsg("採集仍在後台進行，稍後點「刷新」查看");
            setBusy(false);
          }
        } catch {
          window.clearInterval(timer);
          setBusy(false);
        }
      }, 8000);
    } catch (e) {
      setMsg(`採集失敗: ${(e as Error).message}`);
      setBusy(false);
    }
  }

  async function openDetail(id: string) {
    try {
      setDetail(await api<JobDetail>(`/api/jobs/${id}`));
    } catch {
      setMsg("讀取詳情失敗");
    }
  }

  async function score(id: string) {
    setMsg("評分中…");
    try {
      await api(`/api/matches/${id}/score`, { method: "POST" });
      setMsg("評分完成");
      await load();
    } catch (e) {
      setMsg(`評分失敗: ${(e as Error).message}`);
    }
  }

  return (
    <div>
      <main>
        <div className="card wide">
          <h2>{t("jobBoard")}</h2>
          <div className="row wrap">
            <input placeholder="搜索職位關鍵詞（點搜索查詢）" value={q} onChange={(e) => setQ(e.target.value)} />
            <input placeholder="公司名" value={company} onChange={(e) => setCompany(e.target.value)} />
            <button onClick={() => { setOffset(0); void load(); }}>{t("search")}</button>
            <select
              value={campus}
              onChange={(e) => setCampus(e.target.value)}
            >
              <option value="">校招/社招：全部</option>
              <option value="campus">僅校招</option>
              <option value="society">僅社招</option>
            </select>
            <select
              value={org}
              onChange={(e) => setOrg(e.target.value)}
            >
              <option value="">總部/分支：全部</option>
              <option value="headquarter">僅總部</option>
              <option value="branch">僅分支機構</option>
            </select>
            <button className="ghost" disabled={busy} onClick={() => void collect(!!company)}>
              {company ? `採集「${company}」` : t("collectNow")}
            </button>
            <button className="ghost" onClick={() => { void load(); setCollectOk(false); setMsg("已刷新"); }}>
              🔃 刷新
            </button>
          </div>
          <p className={collectOk ? "notice success" : "notice"}>{msg}</p>
          <p className="muted">每日 02:00 自動採集；也可手動觸發（後台執行）。點擊行查看詳情。</p>
          <table>
            <thead>
              <tr>
                <th>{t("company")}</th>
                <th>{t("jobTitle")}</th>
                <th>{t("location")}</th>
                <th>類型</th>
                <th>部門</th>
                <th>{t("source")}</th>
                <th>{t("fitScore")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id} onClick={() => void openDetail(j.id)} style={{ cursor: "pointer" }}>
                  <td>{j.company_name}</td>
                  <td>{j.title}</td>
                  <td>{j.location ?? "-"}</td>
                  <td>{j.is_campus ? "校招" : "社招"} · {j.org_level === "headquarter" ? "總部" : j.org_level === "branch" ? "分支" : "—"}</td>
                  <td className="muted">{j.department ?? "—"}</td>
                  <td>{j.source}</td>
                  <td>
                    {j.match_score != null ? (
                      <b>{j.match_score}%</b>
                    ) : (
                      <button
                        className="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          void score(j.id);
                        }}
                      >
                        {t("match")}
                      </button>
                    )}
                  </td>
                  <td>{j.match_status ? STATUS_TEXT[j.match_status] ?? j.match_status : ""}</td>
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
          {detail && (
            <div className="detail">
              <h3>
                {detail.company_name} · {detail.title}
              </h3>
              <p className="muted">
                {detail.location ?? ""} · {detail.department ?? ""} · 貼合度:{" "}
                {detail.match_score != null ? `${detail.match_score}%` : "未匹配"}
              </p>
              {detail.reasons.length > 0 && (
                <p>
                  <b>匹配理由：</b>
                  {detail.reasons.join("；")}
                </p>
              )}
              {Array.isArray(detail.hard_failures) && detail.hard_failures.length > 0 && (
                <p className="notice">硬性條件不符：{JSON.stringify(detail.hard_failures)}</p>
              )}
              <div className="code" style={{ maxHeight: 240 }}>
                {detail.description_text ?? "（無 JD 描述）"}
              </div>
              <div className="row">
                {detail.apply_url && (
                  <a href={detail.apply_url} target="_blank" rel="noreferrer">
                    {t("openApply")}
                  </a>
                )}
                <button onClick={() => setDetail(null)} className="ghost">
                  關閉
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
