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
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (q) params.set("q", q);
    if (company) params.set("company", company);
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

  async function collect() {
    setBusy(true);
    setMsg("正在後台採集你的關注公司…稍後點擊搜索/刷新查看");
    try {
      await api("/api/jobs/collect/run", { method: "POST" });
    } catch (e) {
      setMsg(`採集失敗: ${(e as Error).message}`);
    } finally {
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
            <input placeholder="搜索職位關鍵詞" value={q} onChange={(e) => setQ(e.target.value)} />
            <input placeholder="公司名" value={company} onChange={(e) => setCompany(e.target.value)} />
            <button onClick={() => { setOffset(0); void load(); }}>{t("search")}</button>
            <button className="ghost" disabled={busy} onClick={() => void collect()}>
              {t("collectNow")}
            </button>
          </div>
          <p className="muted">每日 02:00 自動採集；也可手動觸發（後台執行）。點擊行查看詳情。</p>
          <table>
            <thead>
              <tr>
                <th>{t("company")}</th>
                <th>{t("jobTitle")}</th>
                <th>{t("location")}</th>
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
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
