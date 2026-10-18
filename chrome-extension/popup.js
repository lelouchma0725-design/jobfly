const $ = (id) => document.getElementById(id);

chrome.storage.local.get("token").then(({ token }) => {
  if (token) showTasks();
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

$("refresh").addEventListener("click", loadTasks);

async function showTasks() {
  $("loginBox").style.display = "none";
  $("taskBox").style.display = "block";
  await loadTasks();
}

async function loadTasks() {
  $("status").textContent = "讀取任務…";
  const r = await chrome.runtime.sendMessage({ type: "TASKS" });
  if (!r || !r.ok) {
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
