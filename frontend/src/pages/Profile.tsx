import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

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

const FACT_KEYS: Record<string, string> = {
  visa_status: "visaStatus",
  preferred_locations: "preferredLocations",
  salary_expectation: "salaryExpectation",
  availability: "availability",
  total_years: "totalYears",
};

export default function ProfilePage() {
  const { t } = useT();
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
    setMsg(t("generating"));
    try {
      await api("/api/profile/generate", { method: "POST", body: JSON.stringify({}) });
      await load();
      setMsg("");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const roles = (profile?.suggested_roles ?? [])
    .slice()
    .sort((a, b) => b.fit_score - a.fit_score)
    .slice(0, 5);

  return (
    <div>
      <main>
        <div className="card wide">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>{t("aiPortrait")}</h2>
            <div className="row">
              {profile && (
                <span className="muted">
                  {t("generatedAt")}: {profile.generated_at.slice(0, 10)}
                </span>
              )}
              <button disabled={busy} onClick={() => void generate()}>
                {profile ? t("regenerateProfile") : t("generateProfile")}
              </button>
            </div>
          </div>
          <p className="muted">基於已解析的簡歷，AI 自動分析適合你的崗位、貼合度與理由。</p>
          {profile && (
            <>
              <h3>{t("overview")}</h3>
              <p>{profile.summary}</p>
              <h3>{t("coreSkills")}</h3>
              <p>
                {(profile.skills ?? [])
                  .map((s) => `${s.name}(${s.level}/5${s.years ? `, ${s.years}y` : ""})`)
                  .join("、") || "—"}
              </p>
              <h3>{t("experience")}</h3>
              <ul>
                {(profile.experiences ?? []).map((e, i) => (
                  <li key={i}>
                    <b>{e.title}</b> @ {e.company}（{e.start} – {e.end}）
                  </li>
                ))}
              </ul>
              <h3>{t("hardFacts")}</h3>
              <table>
                <tbody>
                  {Object.entries(profile.hard_facts ?? {}).map(([k, v]) => (
                    <tr key={k}>
                      <td className="muted">{t(FACT_KEYS[k] ?? k)}</td>
                      <td>{Array.isArray(v) ? v.join("、") : String(v ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3>{t("suggestedRoles")}</h3>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t("jobTitle")}</th>
                    <th>{t("fitScore")}</th>
                    <th>{t("reasons")}</th>
                    <th>{t("demand")}</th>
                  </tr>
                </thead>
                <tbody>
                  {roles.map((r, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td>
                      <td>{r.title}</td>
                      <td><b>{r.fit_score}%</b></td>
                      <td className="cell-wrap">{r.reasons.join("；")}</td>
                      <td className="muted">{r.demand_note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
