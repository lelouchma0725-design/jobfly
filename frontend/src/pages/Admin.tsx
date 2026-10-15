import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Header from "../components/Header";

type Stats = {
  users: number;
  active_postings: number;
  matches_24h: number;
  applications_total: number;
  applications_submitted_24h: number;
  open_manual_tasks: number;
  platform_accounts_issue: number;
  collected_today: number;
  llm_usage: { calls: number; tokens_in: number; tokens_out: number };
};
type UserRow = {
  id: string; email: string | null; role: string; created_at: string;
  disabled: boolean; applications: number; matches: number;
};
type Adapter = {
  adapter: string; last_run_at: string | null; last_success_at: string | null;
  success_count: number; fail_count: number; last_error: string | null; avg_duration_ms: number | null;
};

export default function Admin() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const [s, u, a] = await Promise.all([
        api<Stats>("/api/admin/stats"),
        api<UserRow[]>("/api/admin/users"),
        api<Adapter[]>("/api/admin/adapters"),
      ]);
      setStats(s); setUsers(u); setAdapters(a); setErr("");
    } catch (e) {
      setErr(`無權限或加載失敗: ${(e as Error).message}`);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function setUser(id: string, patch: { disabled?: boolean; role?: string }) {
    const qs = new URLSearchParams(patch as Record<string, string>);
    await api(`/api/admin/users/${id}?${qs}`, { method: "PATCH" });
    await load();
  }

  if (err) {
    return (
      <div className="page">
        <Header />
        <main className="narrow"><div className="card"><h2>管理後台</h2><p className="notice">{err}</p></div></main>
      </div>
    );
  }

  return (
    <div className="page">
      <Header />
      <main className="narrow">
        <div className="card wide">
          <h2>管理後台（GAP-10）</h2>
          {stats && (
            <div className="row wrap">
              <Stat label="用戶數" value={stats.users} />
              <Stat label="活躍崗位" value={stats.active_postings} />
              <Stat label="今日新採集" value={stats.collected_today} />
              <Stat label="24h 匹配" value={stats.matches_24h} />
              <Stat label="24h 投遞成功" value={stats.applications_submitted_24h} />
              <Stat label="待人工任務" value={stats.open_manual_tasks} />
              <Stat label="帳號異常" value={stats.platform_accounts_issue} />
              <Stat label="LLM 調用" value={stats.llm_usage.calls} />
              <Stat
                label="LLM tokens"
                value={`${(stats.llm_usage.tokens_in + stats.llm_usage.tokens_out).toLocaleString()}`}
              />
            </div>
          )}
          <h3>用戶</h3>
          <table>
            <thead>
              <tr><th>郵箱</th><th>角色</th><th>註冊</th><th>匹配</th><th>投遞</th><th></th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email ?? "-"}</td>
                  <td>{u.role}</td>
                  <td>{u.created_at.slice(0, 10)}</td>
                  <td>{u.matches}</td>
                  <td>{u.applications}</td>
                  <td>
                    <button className="ghost" onClick={() => void setUser(u.id, { role: u.role === "admin" ? "user" : "admin" })}>
                      {u.role === "admin" ? "降為用戶" : "設為管理員"}
                    </button>
                    <button className="ghost" onClick={() => void setUser(u.id, { disabled: !u.disabled })}>
                      {u.disabled ? "啟用" : "禁用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>採集適配器健康</h3>
          <table>
            <thead>
              <tr><th>適配器</th><th>成功/失敗</th><th>平均耗時</th><th>最近成功</th><th>最近錯誤</th></tr>
            </thead>
            <tbody>
              {adapters.map((a) => (
                <tr key={a.adapter}>
                  <td>{a.adapter}</td>
                  <td>{a.success_count} / {a.fail_count}</td>
                  <td>{a.avg_duration_ms ? `${a.avg_duration_ms}ms` : "-"}</td>
                  <td>{a.last_success_at ?? "-"}</td>
                  <td className="muted">{a.last_error ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="stat">
      <div className="muted">{label}</div>
      <b>{value}</b>
    </div>
  );
}
