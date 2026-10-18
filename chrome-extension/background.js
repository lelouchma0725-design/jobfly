/** JobsComing RPA 填報助手 — service worker（代持 API 請求，繞過 CORS）。 */
const API_BASE = "https://jobscoming-backend.onrender.com";

async function apiFetch(path, options = {}) {
  const { token } = await chrome.storage.local.get("token");
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {
        case "SIGNIN": {
          const data = await apiFetch("/api/auth/signin", {
            method: "POST",
            body: JSON.stringify({ email: msg.email, password: msg.password }),
          });
          await chrome.storage.local.set({ token: data.access_token });
          sendResponse({ ok: true });
          break;
        }
        case "TASKS": {
          const tasks = await apiFetch("/api/manual-tasks?status=open");
          sendResponse({ ok: true, tasks });
          break;
        }
        case "FILL_PLAN": {
          const plan = await apiFetch(`/api/manual-tasks/${msg.taskId}/fill-plan`);
          sendResponse({ ok: true, plan });
          break;
        }
        case "COMPLETE": {
          const out = await apiFetch(`/api/manual-tasks/${msg.taskId}/answer`, {
            method: "POST",
            body: JSON.stringify({ answer: msg.answer }),
          });
          sendResponse({ ok: true, out });
          break;
        }
        case "DOWNLOAD": {
          // 經由後台下載簡歷（返回 dataURL，content script 塞進 file input）
          const { token } = await chrome.storage.local.get("token");
          const res = await fetch(msg.url);
          const blob = await res.blob();
          const dataUrl = await new Promise((resolve) => {
            const fr = new FileReader();
            fr.onload = () => resolve(fr.result);
            fr.readAsDataURL(blob);
          });
          sendResponse({ ok: true, dataUrl });
          break;
        }
        default:
          sendResponse({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // 異步響應
});
