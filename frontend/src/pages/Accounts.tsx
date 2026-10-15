import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Header from "../components/Header";

type Account = {
  id: string;
  platform: string;
  label: string;
  login_masked: string;
  status: string;
  last_login_at: string | null;
  last_error: string | null;
};

const PLATFORMS: Record<string, string> = {
  workday: "Workday",
  greenhouse: "Greenhouse",
  lever: "Lever",
  successfactors: "SAP SuccessFactors",
  icims: "iCIMS",
  official: "公司官網",
  liepin: "獵聘",
  boss: "Boss直聘",
  lagou: "拉勾",
  zhilian: "智聯招聘",
  job51: "前程無憂",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  other: "其他",
};

const STATUS: Record<string, string> = {
  pending_verify: "待驗證",
  active: "正常",
  expired: "已失效",
  locked: "已鎖定",
  error: "異常",
};

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [form, setForm] = useState({ platform: "workday", label: "", id: "", password: "" });
  const [editing, setEditing] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setAccounts(await api<Account[]>("/api/accounts"));
    } catch {
      setMsg("讀取帳號失敗");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      if (editing) {
        await api(`/api/accounts/${editing}`, {
          method: "PATCH",
          body: JSON.stringify({
            label: form.label || undefined,
            login_identifier: form.id || undefined,
            password: form.password || undefined,
          }),
        });
      } else {
        await api("/api/accounts", {
          method: "POST",
          body: JSON.stringify({
            platform: form.platform,
            label: form.label,
            login_identifier: form.id,
            password: form.password,
          }),
        });
      }
      setForm({ platform: "workday", label: "", id: "", password: "" });
      setEditing(null);
      setMsg("已保存（帳密已加密存儲）");
      await load();
    } catch (err) {
      setMsg(`保存失敗: ${(err as Error).message}`);
    }
  }

  async function remove(id: string) {
    if (!confirm("確認刪除該帳號？")) return;
    await api(`/api/accounts/${id}`, { method: "DELETE" });
    await load();
  }

  return (
    <div className="page">
      <Header />
      <main className="narrow">
        <div className="card wide">
          <h2>招聘平台帳號（FR-1d）</h2>
          <p className="muted">
            帳號密碼經 AES-256 信封加密存儲，數據庫中不存明文；登錄態 Cookie 同樣加密保存。
            獵聘/Boss 等平台首期僅用於採集。
          </p>
          <form onSubmit={submit} className="row wrap">
            <select
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
            >
              {Object.entries(PLATFORMS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
            <input
              placeholder="標籤（如：我的領英）"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              required
            />
            <input
              placeholder="帳號"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              required
            />
            <input
              type="password"
              placeholder="密碼"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required={!editing}
            />
            <button type="submit">{editing ? "保存修改" : "添加帳號"}</button>
            {editing && (
              <button type="button" className="ghost" onClick={() => setEditing(null)}>
                取消
              </button>
            )}
          </form>
          <table>
            <thead>
              <tr>
                <th>平台</th>
                <th>標籤</th>
                <th>帳號</th>
                <th>狀態</th>
                <th>最近登錄</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id}>
                  <td>{PLATFORMS[a.platform] ?? a.platform}</td>
                  <td>{a.label}</td>
                  <td>{a.login_masked}</td>
                  <td>{STATUS[a.status] ?? a.status}</td>
                  <td>{a.last_login_at ?? "-"}</td>
                  <td>
                    <button
                      className="ghost"
                      onClick={() => {
                        setEditing(a.id);
                        setForm({ ...form, label: a.label, id: "", password: "" });
                      }}
                    >
                      修改
                    </button>
                    <button className="ghost" onClick={() => remove(a.id)}>
                      刪除
                    </button>
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
