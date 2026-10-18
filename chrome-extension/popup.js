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
    chrome.tabs.sendMessage(tab.id, { type, ...extra }, (resp) => {
      if (chrome.runtime.lastError || !resp) {
        $("status").textContent = "請先打開官網的簡歷/申請頁面再操作";
        $("status").className = "err";
      }
    });
  });
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
      chrome.tabs.sendMessage(tab.id, { type: "FILL", taskId: t.id }, (resp) => {
        if (chrome.runtime.lastError || !resp) {
          $("status").textContent = "請先打開官網的崗位申請頁面再點此按鈕";
          $("status").className = "err";
        }
      });
    });
    div.appendChild(btn);
    box.appendChild(div);
  }
  $("status").textContent = "";
}
