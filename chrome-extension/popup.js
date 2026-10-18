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

function sendToTab(type, extra = {}) {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    ensureContent(tab).then(() => {
      chrome.tabs.sendMessage(tab.id, { type, ...extra }, (resp) => {
        if (chrome.runtime.lastError || !resp) {
          $("status").textContent = "操作失敗：請確認頁面已打開且不是瀏覽器內部頁面（chrome:// 等）";
          $("status").className = "err";
        }
      });
    });
  });
}

/** 若內容腳本未加載（頁面不在白名單），現場注入後再通訊。 */
async function ensureContent(tab) {
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "PING" });
  } catch {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    } catch {
      // 無法注入（chrome:// 等內部頁面）
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
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      ensureContent(tab).then(() => {
        chrome.tabs.sendMessage(tab.id, { type: "FILL", taskId: t.id }, (resp) => {
          if (chrome.runtime.lastError || !resp) {
            $("status").textContent = "操作失敗：請確認已打開官網申請頁面";
            $("status").className = "err";
          }
        });
      });
    });
    div.appendChild(btn);
    box.appendChild(div);
  }
  $("status").textContent = "";
}
