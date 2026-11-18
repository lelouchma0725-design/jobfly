/** JobsComing RPA 填報助手 — service worker（代持 API 請求，繞過 CORS）。 */
const API_BASE = "https://jobscoming-backend.onrender.com";

function withTimeout(ms) {
  return new AbortController();
}

async function timedFetch(url, opts, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

async function apiFetch(path, options = {}) {
  const { token, refreshToken } = await chrome.storage.local.get(["token", "refreshToken"]);
  const doFetch = (tk) =>
    fetch(API_BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(tk ? { Authorization: `Bearer ${tk}` } : {}),
        ...(options.headers || {}),
      },
    });

  // 45 秒超時 + 失敗重試一次（後台冷啟動可能需要時間）
  let res;
  try {
    res = await timedFetch(API_BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    }, 45000);
  } catch {
    res = await timedFetch(API_BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    }, 45000);
  }
  // 401 → 自動用 refresh token 續期並重試一次
  if (res.status === 401 && refreshToken) {
    try {
      const r = await fetch(API_BASE + "/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (r.ok) {
        const data = await r.json();
        await chrome.storage.local.set({
          token: data.access_token,
          refreshToken: data.refresh_token || refreshToken,
        });
        res = await timedFetch(API_BASE + path, {
          ...options,
          headers: {
            "Content-Type": "application/json",
            ...(data.access_token ? { Authorization: `Bearer ${data.access_token}` } : {}),
            ...(options.headers || {}),
          },
        }, 45000);
      }
    } catch {
      /* 續期失敗走下方 AUTH 流程 */
    }
  }
  if (res.status === 401) {
    // 續期也失敗 → 清除憑證，通知 popup 顯示登錄框
    await chrome.storage.local.remove(["token", "refreshToken"]);
    const err = new Error("AUTH_EXPIRED");
    err.authExpired = true;
    throw err;
  }
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
          await chrome.storage.local.set({
            token: data.access_token,
            refreshToken: data.refresh_token || "",
          });
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
        case "SCRAPE_SAVE": {
          const out = await apiFetch("/api/rpa/scrape", {
            method: "POST",
            body: JSON.stringify({ site: msg.site, page_type: msg.pageType, fields: msg.fields }),
          });
          sendResponse({ ok: true, out });
          break;
        }
        case "RPA_FIELDS": {
          const fields = await apiFetch("/api/rpa/fields");
          sendResponse({ ok: true, fields });
          break;
        }
        case "PINYIN": {
          const out = await apiFetch(`/api/rpa/pinyin?name=${encodeURIComponent(msg.name || "")}`);
          sendResponse({ ok: true, out });
          break;
        }
        case "JOB_DETAIL_COLLECT": {
          // 後台逐個打開職位詳情頁（每批 5 個同步回傳，彈窗可關閉）
          (async () => {
            const jobs = msg.jobs || [];
            const site = msg.site || "jobsdb";
            const total = Math.min(jobs.length, 20);
            let doneAll = 0;
            const statuses = [];
            for (let i = 0; i < total; i++) {
              const j = jobs[i];
              let tab = null;
              let detailText = "";
              let title = j.title || "";
              try {
                tab = await chrome.tabs.create({ url: j.url, active: false });
                await new Promise((r) => setTimeout(r, 8000));
                const res = await chrome.scripting.executeScript({
                  target: { tabId: tab.id },
                  func: () => ({
                    title: (document.querySelector("h1")?.textContent || "").trim().slice(0, 200),
                    detail_text: (document.body.innerText || "").slice(0, 6000),
                  }),
                });
                const d = (res && res[0] && res[0].result) || {};
                detailText = d.detail_text || "";
                if (d.title) title = d.title;
              } catch (e) {
                /* 單頁失敗：跳過 */
              } finally {
                if (tab) {
                  try { await chrome.tabs.remove(tab.id); } catch { /* 忽略 */ }
                }
              }
              const batch = [{ ...j, title, detail_text: detailText }];
              // 每 5 個同步回傳一批（後端同步處理，Render 凍結線程不影響）
              if (batch[0].detail_text && ((i + 1) % 5 === 0 || i === total - 1)) {
                try {
                  const out = await apiFetch("/api/rpa/job-detail-ingest", {
                    method: "POST",
                    body: JSON.stringify({ site, jobs: batch }),
                  });
                  if (out && out.ok) doneAll += out.processed ?? 0;
                  statuses.push(...(out && out.results ? out.results : []));
                } catch (e) {
                  statuses.push({ external_id: j.external_id, status: "error", error: e?.message });
                }
              }
              try {
                await chrome.storage.local.set({
                  jobDetailProgress: { done: i + 1, total, msg: `詳情採集 ${i + 1}/${total}…（已抽取 ${doneAll}）` },
                });
              } catch { /* 忽略 */ }
              await new Promise((r) => setTimeout(r, 500));
            }
            const okN = statuses.filter((x) => x && x.status === "ok").length;
            try {
              await chrome.storage.local.set({
                jobDetailProgress: {
                  done: -1,
                  total,
                  msg: `詳情採集完成：${total} 頁，AI 抽取成功 ${doneAll}，含公司 ${okN}。到「我的匹配」查看（評分已同步完成）。`,
                },
              });
            } catch { /* 忽略 */ }
          })();
          sendResponse({ ok: true, started: true });
          break;
        }
        case "JOB_LIST_INGEST": {
          const out = await apiFetch("/api/rpa/job-list-ingest", {
            method: "POST",
            body: JSON.stringify({ site: msg.site, jobs: msg.jobs }),
          });
          sendResponse({ ok: true, out });
          break;
        }
        case "RPA_VERIFY": {
          const out = await apiFetch("/api/rpa/verify", {
            method: "POST",
            body: JSON.stringify({
              site: msg.site, page_type: msg.pageType,
              compare_with: msg.compareWith, fields: msg.fields,
            }),
          });
          sendResponse({ ok: true, out });
          break;
        }
        default:
          sendResponse({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      sendResponse({
        ok: false,
        error: e && e.authExpired ? "AUTH_EXPIRED" : String(e.message || e),
      });
    }
  })();
  return true; // 異步響應
});
