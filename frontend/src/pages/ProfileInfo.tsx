import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import { decryptText, deriveKeyB64, encryptText, getKeyB64, setKeyB64 } from "../lib/crypto";

type InfoField = { key: string; value: string; source: string; updated_at: string; sensitive?: boolean; encrypted?: string | null };
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

const CORE_KEYS = ["candidate_name", "full_name", "phone", "visa_status", "preferred_locations",
  "salary_expectation", "availability", "total_years"];

/** 個人信息總覽：基本信息 + 元信息庫（含畫像提取，統一存儲），一站式檢查/編輯 */
export default function ProfileInfo() {
  const { t } = useT();
  const [data, setData] = useState<Full | null>(null);
  const [basic, setBasic] = useState({ full_name: "", email: "", phone: "" });
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const [msg, setMsg] = useState("");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  function mask(v: string) {
    if (v.length <= 4) return "****";
    return v.slice(0, 2) + "*".repeat(Math.min(v.length - 4, 8)) + v.slice(-2);
  }

  async function load() {
    try {
      const d = await api<Full>("/api/me/profile-full");
      // 敏感字段本地解密（密鑰存在時）
      const key = getKeyB64();
      if (key) {
        for (const f of d.info_fields) {
          if (f.encrypted) {
            const pt = await decryptText(key, f.encrypted);
            if (pt != null) f.value = pt;
          }
        }
      }
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

  async function rotatePassword() {
    const oldPw = prompt("請輸入當前密碼（驗證用）");
    if (!oldPw) return;
    const newPw = prompt("請輸入新密碼（至少 6 位）");
    if (!newPw || newPw.length < 6) return setMsg("新密碼太短");
    setMsg("正在遷移敏感字段密文…");
    try {
      const oldKey = getKeyB64();
      const newKey = oldKey ? await deriveKeyB64(newPw, `jobfly:${data?.basic.email}`) : null;
      // 1) 後端改密碼（驗證舊密碼）
      await api("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      // 2) 敏感字段密文遷移：舊密鑰解密 → 新密鑰加密 → 批量重傳
      if (oldKey && newKey && data) {
        const fields = [];
        for (const f of data.info_fields) {
          if (f.encrypted) {
            const pt = await decryptText(oldKey, f.encrypted);
            if (pt != null) {
              fields.push({ key: f.key, sensitive_enc: await encryptText(newKey, pt) });
            }
          }
        }
        if (fields.length) {
          await api("/api/me/info-fields/import", {
            method: "PUT",
            body: JSON.stringify({ fields }),
          });
        }
        setKeyB64(newKey);
      }
      setMsg("✅ 密碼已更新，敏感字段密文已用新密鑰重新加密");
    } catch (e) {
      setMsg(`修改失敗: ${(e as Error).message}`);
    }
  }

  async function exportBackup() {
    try {
      const r = await api<{ fields: { key: string; sensitive_enc: string }[]; note: string }>(
        "/api/me/info-fields/export",
      );
      const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "jobfly-e2ee-backup.json";
      a.click();
      setMsg("已導出密文備份文件（只含密文，恢復需同一密碼）");
    } catch (e) {
      setMsg(`導出失敗: ${(e as Error).message}`);
    }
  }

  async function importBackup() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        const r = await api<{ imported: number }>("/api/me/info-fields/import", {
          method: "PUT",
          body: JSON.stringify({ fields: parsed.fields || [] }),
        });
        setMsg(`✅ 已導入 ${r.imported} 條敏感字段密文`);
        await load();
      } catch (e) {
        setMsg(`導入失敗: ${(e as Error).message}`);
      }
    };
    input.click();
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

          <h3>🔐 安全（E2EE）</h3>
          <div className="row wrap">
            <button className="ghost" onClick={() => void rotatePassword()}>
              修改密碼（自動遷移敏感字段密文）
            </button>
            <button className="ghost" onClick={() => void exportBackup()}>
              導出密文備份（換設備用）
            </button>
            <button className="ghost" onClick={() => void importBackup()}>
              導入密文備份
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
                    {f.sensitive && !revealed.has(f.key) ? (
                      <>
                        <span className="muted">{mask(f.value)}</span>{" "}
                        <button
                          className="ghost small"
                          onClick={() => setRevealed(new Set(revealed).add(f.key))}
                        >
                          顯示
                        </button>
                      </>
                    ) : (
                      f.value
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
