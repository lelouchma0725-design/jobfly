import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Task = {
  id: string;
  task_type: string;
  question: string;
  options: Record<string, { label: string; type: string }>;
  status: string;
  created_at: string;
  expires_at: string;
  application_status: string;
  company_name: string;
  title: string;
};

const TYPE_TEXT: Record<string, string> = {
  captcha: "驗證碼",
  login_required: "需要登錄",
  missing_field: "缺字段",
  missing_file: "缺文件",
  confirm_content: "確認內容",
  citics_manual: "中信官網投遞",
  manual_citics_login: "中信官網投遞",
  other: "其他",
};

export default function Tasks() {
  const [items, setItems] = useState<Task[]>([]);
  const [answers, setAnswers] = useState<Record<string, Record<string, string | boolean>>>({});
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setItems(await api<Task[]>("/api/manual-tasks?status=open"));
    } catch {
      setMsg("讀取任務失敗");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  function setAnswer(taskId: string, key: string, value: string | boolean) {
    setAnswers((prev) => ({ ...prev, [taskId]: { ...(prev[taskId] ?? {}), [key]: value } }));
  }

  async function submit(task: Task) {
    setMsg("提交中（提交後會自動重新投遞）…");
    try {
      const r = await api<Record<string, unknown>>(`/api/manual-tasks/${task.id}/answer`, {
        method: "POST",
        body: JSON.stringify({ answer: answers[task.id] ?? {} }),
      });
      setMsg(`已提交並重新投遞：${JSON.stringify(r)}`);
      await load();
    } catch (e) {
      setMsg(`提交失敗: ${(e as Error).message}`);
    }
  }

  async function fillPlan(task: Task) {
    try {
      const p = await api<{ copy_text: string }>(`/api/manual-tasks/${task.id}/fill-plan`);
      await navigator.clipboard.writeText(p.copy_text);
      setMsg("✅ 填寫方案已複製到剪貼板，粘貼到官網對應欄位即可");
    } catch (e) {
      setMsg(`獲取填寫方案失敗: ${(e as Error).message}`);
    }
  }

  async function cancel(task: Task) {
    if (!confirm("取消後該投遞將標記為放棄，確認？")) return;
    await api(`/api/manual-tasks/${task.id}/cancel`, { method: "POST" });
    await load();
  }

  return (
    <div className="page">      <main className="narrow">
        <div className="card wide">
          <h2>待你處理</h2>
          <p className="muted">
            投遞遇到驗證碼、缺字段、缺文件時會暫停並在這裡等你。填寫/確認後系統自動在原位置繼續投遞。
          </p>
          {items.length === 0 && <p>暫無待處理任務 🎉</p>}
          {items.map((t) => (
            <div key={t.id} className="task">
              <h3>
                [{TYPE_TEXT[t.task_type] ?? t.task_type}] {t.company_name} · {t.title}
              </h3>
              <p>{t.question}</p>
              {["citics_manual", "manual_citics_login"].includes(t.task_type) && (
                <button className="ghost" onClick={() => void fillPlan(t)}>
                  📋 一鍵複製填寫方案（按官網要求整理好的答案）
                </button>
              )}
              <div className="column">
                {Object.entries(t.options ?? {}).map(([key, opt]) => (
                  <label key={key} className="row">
                    {opt.type === "checkbox" ? (
                      <input
                        type="checkbox"
                        checked={Boolean(answers[t.id]?.[key])}
                        onChange={(e) => setAnswer(t.id, key, e.target.checked)}
                      />
                    ) : opt.type === "textarea" ? (
                      <textarea
                        style={{ flex: 1, minHeight: 70 }}
                        placeholder={opt.label}
                        onChange={(e) => setAnswer(t.id, key, e.target.value)}
                      />
                    ) : (
                      <input
                        style={{ flex: 1 }}
                        placeholder={opt.label}
                        onChange={(e) => setAnswer(t.id, key, e.target.value)}
                      />
                    )}
                    <span className="muted">{opt.label}</span>
                  </label>
                ))}
              </div>
              <div className="row">
                <button onClick={() => void submit(t)}>提交並繼續投遞</button>
                <button className="ghost" onClick={() => void cancel(t)}>
                  放棄此投遞
                </button>
              </div>
              <p className="muted">
                過期時間：{t.expires_at}（48 小時未處理自動過期）
              </p>
            </div>
          ))}
          <p className="notice">{msg}</p>
        </div>
      </main>
    </div>
  );
}
