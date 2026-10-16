import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import Pager from "../components/Pager";

type Doc = {
  id: string;
  doc_type: string;
  file_name: string;
  mime: string;
  size_bytes: number | null;
  parse_status: string;
  is_active: boolean;
  lang: string;
  created_at: string;
};

const DOC_KEYS: Record<string, string> = {
  resume: "resume",
  cover_letter: "coverLetter",
  transcript: "transcript",
  visa: "visa",
  certificate: "certificate",
  portfolio: "portfolio",
  other: "other",
};

export default function Documents() {
  const { t } = useT();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [docType, setDocType] = useState(""); // 默認全部
  const [lang, setLang] = useState("zh");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState("");
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);

  async function load() {
    setMsg("");
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (docType) params.set("doc_type", docType);
      const r = await api<{ items: Doc[]; total: number }>(`/api/documents?${params}`);
      setDocs(r.items);
      setTotal(r.total);
    } catch {
      setMsg("加載失敗");
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docType, limit, offset]);

  async function upload() {
    if (!file) return setMsg("請選擇文件");
    setMsg("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api(`/api/documents?doc_type=${docType || "resume"}&lang=${lang}`, { method: "POST", body: fd });
      setFile(null);
      setMsg("上傳成功，點擊「刷新」查看");
    } catch (e) {
      setMsg(`上傳失敗: ${(e as Error).message}`);
    }
  }

  async function remove(id: string) {
    if (!confirm("確認刪除該文件？")) return;
    await api(`/api/documents/${id}`, { method: "DELETE" });
    await load();
  }

  async function parse(id: string) {
    setMsg("解析中…");
    try {
      await api(`/api/documents/${id}/parse`, { method: "POST" });
      setMsg("解析完成");
    } catch (e) {
      setMsg(`解析失敗: ${(e as Error).message}`);
    }
  }

  return (
    <div>
      <main>
        <div className="card wide">
          <h2>{t("myFiles")}</h2>
          <div className="row wrap">
            <select value={docType} onChange={(e) => { setDocType(e.target.value); setOffset(0); }}>
              <option value="">{t("all")}</option>
              {Object.entries(DOC_KEYS).map(([v, k]) => (
                <option key={v} value={v}>{t(k)}</option>
              ))}
            </select>
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="zh">{t("chinese")}</option>
              <option value="en">{t("english")}</option>
            </select>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button onClick={() => void upload()}>{t("upload")}</button>
            <button className="ghost" onClick={() => void load()}>{t("refresh")}</button>
          </div>
          <p className="muted">支持 PDF / Word / TXT / 圖片，單文件 ≤50MB</p>
          <table>
            <thead>
              <tr>
                <th>{t("type")}</th>
                <th>{t("fileName")}</th>
                <th>{t("size")}</th>
                <th>{t("lang")}</th>
                <th>{t("status")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{t(DOC_KEYS[d.doc_type] ?? "other")}</td>
                  <td className="cell-wrap">{d.file_name}</td>
                  <td>{d.size_bytes ? `${(d.size_bytes / 1024).toFixed(0)}KB` : "-"}</td>
                  <td>{d.lang === "en" ? t("english") : t("chinese")}</td>
                  <td>{d.parse_status}</td>
                  <td>
                    <button className="ghost" onClick={() => void parse(d.id)}>{t("parse")}</button>
                    <button className="ghost" onClick={() => void remove(d.id)}>{t("delete")}</button>
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
            onLimit={(l) => { setLimit(l); setOffset(0); }}
          />
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
