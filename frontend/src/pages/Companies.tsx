import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Header from "../components/Header";

type Company = {
  id: string;
  company_name: string;
  aliases: string[];
  careers_url: string | null;
  platform: string;
  notes: string | null;
  is_active: boolean;
  created_at: string;
};

export default function Companies() {
  const [list, setList] = useState<Company[]>([]);
  const [form, setForm] = useState({
    company_name: "",
    aliases: "",
    careers_url: "",
    platform: "official",
    notes: "",
  });
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setList(await api<Company[]>("/api/companies"));
    } catch {
      setMsg("讀取失敗");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api("/api/companies", {
        method: "POST",
        body: JSON.stringify({
          company_name: form.company_name,
          aliases: form.aliases
            .split(/[,，]/)
            .map((s) => s.trim())
            .filter(Boolean),
          careers_url: form.careers_url || null,
          platform: form.platform,
          notes: form.notes || null,
        }),
      });
      setForm({ company_name: "", aliases: "", careers_url: "", platform: "official", notes: "" });
      await load();
    } catch (e) {
      setMsg(`保存失敗: ${(e as Error).message}`);
    }
  }

  async function remove(id: string) {
    if (!confirm("確認刪除？")) return;
    await api(`/api/companies/${id}`, { method: "DELETE" });
    await load();
  }

  async function toggle(c: Company) {
    await api(`/api/companies/${c.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !c.is_active }),
    });
    await load();
  }

  return (
    <div className="page">
      <Header />
      <main className="narrow">
        <div className="card wide">
          <h2>關注公司（FR-1d）</h2>
          <p className="muted">
            每日定時任務會合併所有用戶的關注公司，去重後採集其官網/ATS 招聘信息。
          </p>
          <form onSubmit={submit} className="row wrap">
            <input
              placeholder="公司名稱（如 騰訊）"
              value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })}
              required
            />
            <input
              placeholder="別名，逗號分隔（如 Tencent,腾讯）"
              value={form.aliases}
              onChange={(e) => setForm({ ...form, aliases: e.target.value })}
            />
            <input
              placeholder="招聘頁網址（可選，如 https://careers.tencent.com）"
              value={form.careers_url}
              onChange={(e) => setForm({ ...form, careers_url: e.target.value })}
            />
            <select
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
            >
              <option value="official">公司官網</option>
              <option value="workday">Workday</option>
              <option value="greenhouse">Greenhouse</option>
              <option value="lever">Lever</option>
              <option value="linkedin">LinkedIn</option>
            </select>
            <input
              placeholder="備註（可選）"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
            <button type="submit">添加</button>
          </form>
          <table>
            <thead>
              <tr>
                <th>公司</th>
                <th>招聘頁</th>
                <th>平台</th>
                <th>狀態</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td>
                    {c.company_name}
                    {c.aliases.length > 0 && (
                      <span className="muted">（{c.aliases.join("、")}）</span>
                    )}
                  </td>
                  <td>{c.careers_url ?? "-"}</td>
                  <td>{c.platform}</td>
                  <td>{c.is_active ? "監控中" : "已暫停"}</td>
                  <td>
                    <button className="ghost" onClick={() => toggle(c)}>
                      {c.is_active ? "暫停" : "恢復"}
                    </button>
                    <button className="ghost" onClick={() => remove(c.id)}>
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
