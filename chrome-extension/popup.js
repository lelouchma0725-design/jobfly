const $ = (id) => document.getElementById(id);

function showLogin() {
  $("loginBox").style.display = "block";
  $("taskBox").style.display = "none";
  $("status").textContent = "登錄已失效，請重新登錄";
  $("status").className = "err";
}

function isAuthError(e) {
  return !!e && (e.authExpired || String(e.message || e).includes("AUTH_EXPIRED"));
}

chrome.storage.local.get("token").then(({ token }) => {
  if (token) showTasks().catch((e) => isAuthError(e) && showLogin());
  else showLogin();
});

$("signin").addEventListener("click", async () => {
  $("status").textContent = "登錄中…";
  const r = await chrome.runtime.sendMessage({
    type: "SIGNIN",
    email: $("email").value.trim(),
    password: $("password").value,
  });
  if (r && r.ok) {
    showTasks();
  } else {
    $("status").textContent = "登錄失敗: " + (r?.error || "未知錯誤");
    $("status").className = "err";
  }
});

$("refresh").addEventListener("click", () => {
  loadTasks().catch((e) => isAuthError(e) && showLogin());
});

const SITE_RE = /citics\.com|gtht\.com|greenhouse\.io|lever\.co/;

/** 選目標頁籤：優先當前活動頁（若是官網）；否則找最近訪問的官網頁籤。 */
async function pickTab() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && active.url && SITE_RE.test(active.url)) return active;
  const all = await chrome.tabs.query({ currentWindow: true });
  const site = all.filter((t) => t.url && SITE_RE.test(t.url));
  return site[site.length - 1] || active;
}

function sendToTab(type, extra = {}) {
  (async () => {
    const tab = await pickTab();
    if (!tab || !tab.url || !/^https?:/.test(tab.url)) {
      $("status").textContent = "請先切換到官網頁面（當前是瀏覽器內部頁面，無法操作）";
      $("status").className = "err";
      return;
    }
    await ensureContent(tab);
    try {
      const resp = await chrome.tabs.sendMessage(tab.id, { type, ...extra });
      if (!resp) {
        $("status").textContent = "頁面腳本無響應：請在官網頁面按 F5 重新整理後再試";
        $("status").className = "err";
      }
    } catch (e) {
      $("status").textContent = "操作失敗: " + (e?.message || e);
      $("status").className = "err";
    }
  })();
}

/** 若內容腳本未加載（頁面不在白名單），現場注入後再通訊。 */
async function ensureContent(tab) {
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "PING" });
  } catch {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      await new Promise((r) => setTimeout(r, 300)); // 等監聽器註冊
    } catch (e) {
      throw new Error("無法注入頁面腳本: " + (e?.message || e));
    }
  }
}

$("scrape").addEventListener("click", () => {
  $("status").textContent = "回傳中…（請看頁面右下角面板日誌）";
  sendToTab("SCRAPE", { pageType: $("pageType").value });
});
$("fillResume").addEventListener("click", () => {
  $("status").textContent = "填報中…（請看頁面右下角面板日誌）";
  sendToTab("FILL_RESUME", { pageType: $("pageType").value });
});
$("verify").addEventListener("click", () => {
  $("status").textContent = "校驗中…（請看頁面右下角面板日誌）";
  sendToTab("VERIFY", {
    pageType: $("pageType").value,
    compareWith: $("compareWith").value,
  });
});

async function showTasks() {
  $("loginBox").style.display = "none";
  $("taskBox").style.display = "block";
  await loadTasks();
}

async function loadTasks() {
  $("status").textContent = "讀取任務…";
  let r;
  try {
    r = await chrome.runtime.sendMessage({ type: "TASKS" });
  } catch (e) {
    $("status").textContent = "讀取失敗: " + (e?.message || e);
    $("status").className = "err";
    return;
  }
  if (!r || !r.ok) {
    if (isAuthError(r?.error)) {
      showLogin();
      return;
    }
    $("status").textContent = "讀取失敗: " + (r?.error || "");
    $("status").className = "err";
    return;
  }
  const box = $("tasks");
  box.innerHTML = "";
  if (!r.tasks.length) {
    box.innerHTML = '<p class="muted">暫無待處理投遞任務</p>';
    $("status").textContent = "";
    return;
  }
  for (const t of r.tasks) {
    const div = document.createElement("div");
    div.className = "task";
    div.innerHTML =
      `<b>${t.company_name} · ${t.title}</b>` +
      `<span class="muted">${t.task_type}</span>`;
    const btn = document.createElement("button");
    btn.className = "primary";
    btn.textContent = "開始填報此頁";
    btn.addEventListener("click", async () => {
      const tab = await pickTab();
      if (!tab || !tab.url || !/^https?:/.test(tab.url)) {
        $("status").textContent = "請先切換到官網申請頁面";
        $("status").className = "err";
        return;
      }
      await ensureContent(tab);
      try {
        await chrome.tabs.sendMessage(tab.id, { type: "FILL", taskId: t.id });
      } catch (e) {
        $("status").textContent = "填報失敗: " + (e?.message || e);
        $("status").className = "err";
      }
    });
    div.appendChild(btn);
    box.appendChild(div);
  }
  $("status").textContent = "";
}
