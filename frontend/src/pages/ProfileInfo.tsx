import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type InfoField = { key: string; value: string; source: string; updated_at: string };
type Full = {
  basic: { full_name: string | null; email: string | null; phone: string | null };
  profile: {
    hard_facts: Record<string, unknown>;
    education: Record<string, unknown>[];
    experiences: Record<string, unknown>[];
    skills: { name: string; level: number; years: number | null }[];
    summary: string | null;
    generated_at: string | null;
  };
  info_fields: InfoField[];
};

const FACT_KEYS: Record<string, string> = {
  visa_status: "簽證狀態",
  preferred_locations: "期望城市",
  salary_expectation: "期望薪資",
  availability: "可到崗時間",
  total_years: "工作年限",
};

const SOURCE_TEXT: Record<string, string> = {
  user: "手動填寫",
  resume: "簡歷解析",
  manual_answer: "投遞回填",
};

/** 個人信息總覽：基本信息 + 畫像提取 + 元信息表，一站式檢查/編輯 */
export default function ProfileInfo() {
  const { t } = useT();
  const [data, setData] = useState<Full | null>(null);
  const [basic, setBasic] = useState({ full_name: "", email: "", phone: "" });
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      const d = await api<Full>("/api/me/profile-full");
      setData(d);
      setBasic({
        full_name: d.basic.full_name ?? "",
        email: d.basic.email ?? "",
        phone: d.basic.phone ?? "",
      });
      setMsg("");
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function saveBasic() {
    try {
      await api("/api/me", {
        method: "PATCH",
        body: JSON.stringify({ full_name: basic.full_name || null, phone: basic.phone || null }),
      });
      setMsg("基本信息已保存");
    } catch (e) {
      setMsg(`保存失敗: ${(e as Error).message}`);
    }
  }

  async function addField() {
    const k = newKey.trim();
    const v = newVal.trim();
    if (!k || !v) return;
    try {
      await api("/api/me/info-fields", { method: "PUT", body: JSON.stringify({ key: k, value: v }) });
      setNewKey("");
      setNewVal("");
      await load();
    } catch (e) {
      setMsg(`保存失敗: ${(e as Error).message}`);
    }
  }

  async function delField(key: string) {
    await api(`/api/me/info-fields/${encodeURIComponent(key)}`, { method: "DELETE" });
    await load();
  }

  return (
    <div>
      <main>
        <div className="card wide">
          <h2>個人信息總覽</h2>
          <p className="muted">
            這裡匯總你投遞簡歷所需的全部信息：基本信息 + AI 畫像從簡歷提取的內容 + 表單問答庫（元信息）。
            投遞時表單缺項會從這裡自動互補，建議定期檢查修正。
          </p>

          <h3>基本信息</h3>
          <div className="row wrap">
            <input placeholder="姓名/暱稱" value={basic.full_name}
                   onChange={(e) => setBasic({ ...basic, full_name: e.target.value })} />
            <input placeholder="手機號" value={basic.phone}
                   onChange={(e) => setBasic({ ...basic, phone: e.target.value })} />
            <input placeholder="郵箱" value={basic.email} disabled />
            <button onClick={() => void saveBasic()}>{t("save")}</button>
          </div>

          <h3>畫像提取（來自簡歷解析）</h3>
          {data?.profile.summary && <p>{data.profile.summary}</p>}
          <table>
            <tbody>
              {Object.entries(data?.profile.hard_facts ?? {}).map(([k, v]) => (
                <tr key={k}>
                  <td className="muted">{FACT_KEYS[k] ?? k}</td>
                  <td>{Array.isArray(v) ? v.join("、") : String(v ?? "—")}</td>
                </tr>
              ))}
              <tr>
                <td className="muted">教育</td>
                <td className="cell-wrap">
                  {(data?.profile.education ?? [])
                    .map((e) => `${e.school ?? ""} ${e.degree ?? ""} ${e.major ?? ""}`.trim())
                    .filter(Boolean)
                    .join("；") || "—"}
                </td>
              </tr>
              <tr>
                <td className="muted">工作經歷</td>
                <td className="cell-wrap">
                  {(data?.profile.experiences ?? [])
                    .map((e) => `${e.title ?? ""} @ ${e.company ?? ""}`.trim())
                    .filter(Boolean)
                    .join("；") || "—"}
                </td>
              </tr>
              <tr>
                <td className="muted">技能</td>
                <td className="cell-wrap">
                  {(data?.profile.skills ?? []).map((s) => s.name).join("、") || "—"}
                </td>
              </tr>
            </tbody>
          </table>
          {data?.profile.generated_at && (
            <p className="muted">畫像生成於：{data.profile.generated_at.slice(0, 10)}（如需更新請到「AI 畫像」重新生成）</p>
          )}

          <h3>表單問答庫（元信息，投遞時自動互補）</h3>
          <table>
            <thead>
              <tr>
                <th>字段</th>
                <th>內容</th>
                <th>來源</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(data?.info_fields ?? []).map((f) => (
                <tr key={f.key}>
                  <td>{f.key}</td>
                  <td className="cell-wrap">{f.value}</td>
                  <td className="muted">{SOURCE_TEXT[f.source] ?? f.source}</td>
                  <td>
                    <button className="ghost" onClick={() => void delField(f.key)}>
                      {t("delete")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row wrap">
            <input placeholder="字段名（如：期望薪資）" value={newKey}
                   onChange={(e) => setNewKey(e.target.value)} />
            <input placeholder="內容" value={newVal}
                   onChange={(e) => setNewVal(e.target.value)} />
            <button onClick={() => void addField()}>添加</button>
          </div>
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
