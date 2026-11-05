import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type InfoField = { key: string; value: string; source: string; updated_at: string; sensitive?: boolean };
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

const KEY_LABELS: Record<string, string> = {
  candidate_name: "姓名（簡歷提取）",
  full_name: "姓名/暱稱",
  email: "郵箱",
  phone: "手機號",
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
  chat: "AI 助手填寫",
};

/** 個人信息總覽：基本信息 + 元信息庫（含畫像提取，統一存儲），一站式檢查/編輯 */
export default function ProfileInfo() {
  const { t } = useT();
  const [data, setData] = useState<Full | null>(null);
  const [basic, setBasic] = useState({ full_name: "", email: "", phone: "" });
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [msg, setMsg] = useState("");
  /** 已按需取回的敏感字段明文（服務端單條解密，不批量下發） */
  const [revealed, setRevealed] = useState<Record<string, string>>({});

  async function load() {
    try {
      const d = await api<Full>("/api/me/profile-full");
      setData(d);
      setBasic({
        full_name: d.basic.full_name ?? "",
        email: d.basic.email ?? "",
        phone: d.basic.phone ?? "",
      });
      setRevealed({});
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

  async function revealField(key: string) {
    try {
      const r = await api<{ value: string }>(
        `/api/me/info-fields/${encodeURIComponent(key)}/reveal`,
      );
      setRevealed({ ...revealed, [key]: r.value });
    } catch (e) {
      setMsg(`讀取失敗: ${(e as Error).message}`);
    }
  }

  async function rotatePassword() {
    const oldPw = prompt("請輸入當前密碼（驗證用）");
    if (!oldPw) return;
    const newPw = prompt("請輸入新密碼（至少 6 位）");
    if (!newPw || newPw.length < 6) return setMsg("新密碼太短");
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      setMsg("✅ 密碼已更新");
    } catch (e) {
      setMsg(`修改失敗: ${(e as Error).message}`);
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
            這裡是你投遞簡歷所需的全部信息（統一存儲）：AI 從簡歷提取的內容、你手動維護的內容、
            投遞回填的答案都匯總在下方信息庫，投遞時表單缺項自動從這裡互補，請定期檢查。
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

          <h3>🔐 安全</h3>
          <p className="muted">
            敏感字段（證件、家庭、聯繫方式等）由服務端加密後存儲，頁面只顯示打碼結果，
            點「顯示」可按需查看單條明文。
          </p>
          <div className="row wrap">
            <button className="ghost" onClick={() => void rotatePassword()}>
              修改密碼
            </button>
          </div>

          <h3>個人信息庫（投遞時自動互補，無重複單一來源）</h3>
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
                  <td>{KEY_LABELS[f.key] ?? f.key}{f.sensitive ? " 🔒" : ""}</td>
                  <td className="cell-wrap">
                    {f.sensitive && !revealed[f.key] ? (
                      <>
                        <span className="muted">{f.value}</span>{" "}
                        <button className="ghost small" onClick={() => void revealField(f.key)}>
                          顯示
                        </button>
                      </>
                    ) : (
                      revealed[f.key] ?? f.value
                    )}
                  </td>
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

          {data?.profile.summary && (
            <>
              <h3>簡歷摘要（只讀，改簡歷後到「AI 畫像」重新生成）</h3>
              <p>{data.profile.summary}</p>
              <p className="muted cell-wrap">
                教育：{(data.profile.education ?? [])
                  .map((e) => `${e.school ?? ""} ${e.degree ?? ""} ${e.major ?? ""}`.trim())
                  .filter(Boolean).join("；") || "—"}
                <br />
                經歷：{(data.profile.experiences ?? [])
                  .map((e) => `${e.title ?? ""} @ ${e.company ?? ""}`.trim())
                  .filter(Boolean).join("；") || "—"}
                <br />
                技能：{(data.profile.skills ?? []).map((s) => s.name).join("、") || "—"}
              </p>
            </>
          )}
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
