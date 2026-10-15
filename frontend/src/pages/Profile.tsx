import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Header from "../components/Header";

type Skill = { name: string; level: number; years: number | null };
type Experience = { company: string; title: string; start: string; end: string; bullets: string[] };
type Role = { title: string; fit_score: number; reasons: string[]; demand_note: string };

type Profile = {
  id: string;
  summary: string | null;
  skills: Skill[] | null;
  experiences: Experience[] | null;
  education: Record<string, unknown>[] | null;
  hard_facts: Record<string, unknown> | null;
  suggested_roles: Role[] | null;
  generated_at: string;
};

export default function Profile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setProfile(await api<Profile>("/api/profile"));
      setMsg("");
    } catch (e) {
      setProfile(null);
      setMsg((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function generate() {
    setBusy(true);
    setMsg("正在生成畫像（需數十秒，請稍候）…");
    try {
      await api("/api/profile/generate", { method: "POST", body: JSON.stringify({}) });
      await load();
      setMsg("畫像已生成");
    } catch (e) {
      setMsg(`生成失敗: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Header />
      <main className="narrow">
        <div className="card wide">
          <h2>AI 用戶畫像（FR-1e）</h2>
          <p className="muted">
            基於已解析的簡歷，AI 自動分析適合你的崗位、貼合度與理由。簡歷更新後可重新生成。
          </p>
          <div className="row">
            <button disabled={busy} onClick={generate}>
              {profile ? "重新生成畫像" : "生成畫像"}
            </button>
          </div>
          {profile && (
            <>
              <h3>概覽</h3>
              <p>{profile.summary}</p>
              <h3>核心技能</h3>
              <p>
                {(profile.skills ?? [])
                  .map((s) => `${s.name}(${s.level}/5${s.years ? `, ${s.years}年` : ""})`)
                  .join("、") || "—"}
              </p>
              <h3>主要經歷</h3>
              <ul>
                {(profile.experiences ?? []).map((e, i) => (
                  <li key={i}>
                    <b>{e.title}</b> @ {e.company}（{e.start} – {e.end}）
                  </li>
                ))}
              </ul>
              <h3>硬性事實</h3>
              <pre className="code">{JSON.stringify(profile.hard_facts ?? {}, null, 2)}</pre>
              <h3>適合崗位推薦</h3>
              <table>
                <thead>
                  <tr>
                    <th>崗位</th>
                    <th>貼合度</th>
                    <th>理由</th>
                    <th>市場需求</th>
                  </tr>
                </thead>
                <tbody>
                  {(profile.suggested_roles ?? []).map((r, i) => (
                    <tr key={i}>
                      <td>{r.title}</td>
                      <td>
                        <b>{r.fit_score}%</b>
                      </td>
                      <td>{r.reasons.join("；")}</td>
                      <td className="muted">{r.demand_note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">生成時間：{profile.generated_at}</p>
            </>
          )}
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
