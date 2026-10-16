import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Doc = {
  id: string;
  doc_type: string;
  file_name: string;
  mime: string;
  size_bytes: number | null;
  parse_status: string;
  is_active: boolean;
  created_at: string;
};

const TYPES: Record<string, string> = {
  resume: "簡歷",
  cover_letter: "Cover Letter",
  transcript: "成績單",
  visa: "簽證",
  certificate: "證書",
  portfolio: "作品集",
  other: "其他",
};

export default function Documents() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docType, setDocType] = useState("resume");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setDocs(await api<Doc[]>("/api/documents"));
    } catch {
      setMsg("讀取文件失敗");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function upload() {
    if (!file) return setMsg("請選擇文件");
    setBusy(true);
    setMsg("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api(`/api/documents?doc_type=${docType}`, { method: "POST", body: fd });
      setFile(null);
      setMsg("上傳成功，將自動解析");
      await load();
    } catch (e) {
      setMsg(`上傳失敗: ${(e as Error).message}`);
    } finally {
      setBusy(false);
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
      await load();
    } catch (e) {
      setMsg(`解析失敗: ${(e as Error).message}`);
    }
  }

  return (
    <div className="page">      <main className="narrow">
        <div className="card wide">
          <h2>我的文件（FR-1b）</h2>
          <div className="row">
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              {Object.entries(TYPES).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button disabled={busy} onClick={upload}>
              上傳
            </button>
          </div>
          <p className="muted">支持 PDF / Word / TXT / 圖片，單文件 ≤50MB（免費層上限）</p>
          <table>
            <thead>
              <tr>
                <th>類型</th>
                <th>文件名</th>
                <th>大小</th>
                <th>解析狀態</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{TYPES[d.doc_type] ?? d.doc_type}</td>
                  <td>{d.file_name}</td>
                  <td>{d.size_bytes ? `${(d.size_bytes / 1024).toFixed(0)}KB` : "-"}</td>
                  <td>{d.parse_status}</td>
                  <td>
                    <button className="ghost" onClick={() => parse(d.id)}>
                      解析
                    </button>
                    <button className="ghost" onClick={() => remove(d.id)}>
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
