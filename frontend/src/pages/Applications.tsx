import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Pager from "../components/Pager";

type App = {
  id: string;
  status: string;
  status_reason: string | null;
  attempts_count: number;
  next_retry_at: string | null;
  submitted_at: string | null;
  created_at: string;
  company_name: string;
  title: string;
  location: string | null;
  apply_url: string | null;
  source: string;
  match_score: number | null;
};

const STATUS_TEXT: Record<string, string> = {
  queued: "排隊中",
  in_progress: "投遞中",
  submitted: "✅ 已投遞",
  failed_retryable: "失敗待重試",
  needs_input: "✋ 等待補充",
  aborted: "已放棄",
  duplicate_skip: "重複跳過",
  not_supported: "無法投遞",
};

export default function Applications() {
  const { t } = useT();
  const [items, setItems] = useState<App[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [msg, setMsg] = useState("");
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.set("status", status);
    try {
      const r = await api<{ items: App[]; total: number }>(`/api/applications?${params}`);
      setItems(r.items);
      setTotal(r.total);
    } catch {
      setMsg("讀取投遞記錄失敗");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, limit, offset]);

  async function run() {
    setMsg("正在按設置生成投遞隊列並處理…");
    try {
      const r = await api<{ created: { mode: string; created: number }; processed: Record<string, number> }>(
        "/api/applications/run",
        { method: "POST" },
      );
      setMsg(
        `完成：模式=${r.created.mode}，入隊 ${r.created.created}，處理 ${r.processed.processed}，` +
          `成功 ${r.processed.submitted}，待人工 ${r.processed.needs_input}，失敗 ${r.processed.failed}`,
      );
      await load();
    } catch (e) {
      setMsg(`執行失敗: ${(e as Error).message}`);
    }
  }

  async function act(id: string, action: "retry" | "abort") {
    await api(`/api/applications/${id}/${action}`, { method: "POST" });
    await load();
  }

  return (
    <div>
      <main>
        <div className="card wide">
          <h2>{t("applications")}</h2>
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
            <button onClick={() => void run()}>{t("runQueue")}</button>
          </div>
          <p className="muted">調度器每 30 分鐘處理到期隊列；每用戶投遞間隔受設置中的速率限制保護。</p>
          <table>
            <thead>
              <tr>
                <th>{t("company")} · {t("jobTitle")}</th>
                <th>{t("fitScore")}</th>
                <th>{t("status")}</th>
                <th>嘗試</th>
                <th>原因 / 下次重試</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.company_name} · {a.title}
                    <span className="muted">（{a.source}）</span>
                  </td>
                  <td>{a.match_score != null ? `${a.match_score}%` : "-"}</td>
                  <td>{STATUS_TEXT[a.status] ?? a.status}</td>
                  <td>{a.attempts_count}</td>
                  <td className="muted cell-wrap">{a.status_reason ?? a.next_retry_at ?? "-"}</td>
                  <td>
                    {a.apply_url && (
                      <a href={a.apply_url} target="_blank" rel="noreferrer">
                        {t("openApply")}
                      </a>
                    )}
                    {["failed_retryable", "needs_input", "queued", "aborted"].includes(a.status) && (
                      <button className="ghost" onClick={() => void act(a.id, "retry")}>
                        {t("retry")}
                      </button>
                    )}
                    {!["submitted", "aborted"].includes(a.status) && (
                      <button className="ghost" onClick={() => void act(a.id, "abort")}>
                        {t("abort")}
                      </button>
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
