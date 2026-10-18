const $ = (id) => document.getElementById(id);

const SITE_RE = /citics\.com|gtht\.com|greenhouse\.io|lever\.co/;

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
    btn.addEventListener("click", () => runAction("FILL", { taskId: t.id }));
    div.appendChild(btn);
    box.appendChild(div);
  }
  $("status").textContent = "";
}

/** 選目標頁籤：優先當前活動頁（若是官網）；否則找最近訪問的官網頁籤。 */
async function pickTab() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && active.url && SITE_RE.test(active.url)) return active;
  const all = await chrome.tabs.query({ currentWindow: true });
  const site = all.filter((t) => t.url && SITE_RE.test(t.url));
  return site[site.length - 1] || active;
}

/** 頁面注入：執行一個同步小函數並返回其結果（頁面側零異步，永不卡住）。 */
async function inject(tab, func, args = []) {
  // 確保庫已加載（v3 標記）
  const probe = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => !!(window.__jrpa_sync__ && window.__jrpa_run_v3__),
  });
  if (!(probe[0] && probe[0].result)) {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    await new Promise((r) => setTimeout(r, 400));
  }
  const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func, args });
  return out[0] ? out[0].result : null;
}

/** 頁面右下角面板（同步注入，立刻可見）。 */
function pagePanel(lines) {
  return (lines) => window.__jrpa_sync__.panel("JobsComing RPA", lines);
}

async function bg(type, payload) {
  return chrome.runtime.sendMessage({ type, ...payload });
}

/** 主操作編排：所有後台請求在 popup 完成，頁面只做同步小動作。 */
async function runAction(type, extra) {
  $("status").textContent = "執行中…";
  $("status").className = "";
  try {
    const tab = await pickTab();
    if (!tab || !tab.url || !/^https?:/.test(tab.url)) {
      throw new Error("請先切換到官網頁面（當前是瀏覽器內部頁面）");
    }
    if (type === "SCRAPE") {
      const pageType = $("pageType").value;
      const fields = await inject(
        tab,
        () => window.__jrpa_sync__.collect(),
      );
      await inject(tab, (ls) => {
        window.__jrpa_sync__.panel("回傳簡歷資料", ls);
        return true;
      }, [[{ text: `頁面共識別到 ${fields ? fields.length : 0} 個欄位`, ok: null },
          { text: "正在連線 JobsComing 後台…", ok: null }]]);
      const r = await bg("SCRAPE_SAVE", { site: tab.url ? new URL(tab.url).hostname : "", pageType, fields: fields || [] });
      if (r && r.ok) {
        $("status").textContent = `✅ 已回傳 ${r.out.saved} 個字段到元信息表`;
        $("status").className = "ok";
        await inject(tab, (n) => {
          window.__jrpa_sync__.panel("回傳簡歷資料", [{ text: `✅ 已回傳 ${n} 個字段到元信息表`, ok: true }]);
          return true;
        }, [r.out.saved]);
      } else {
        $("status").textContent = "回傳失敗: " + (r?.error || "");
        $("status").className = "err";
      }
      return;
    }
    if (type === "FILL_RESUME") {
      const pageType = $("pageType").value;
      const r = await bg("RPA_FIELDS", {});
      if (!r || !r.ok) throw new Error("讀取元信息失敗: " + (r?.error || ""));
      const res = await inject(
        tab,
        (entries) => window.__jrpa_sync__.fill(entries),
        [r.fields],
      );
      const filled = res ? res.filled : 0;
      const skipped = res ? res.skipped : [];
      $("status").textContent = `✅ 已填寫 ${filled} 個欄位` + (skipped.length ? `（未匹配 ${skipped.length} 個）` : "");
      $("status").className = "ok";
      return;
    }
    if (type === "VERIFY") {
      const pageType = $("pageType").value;
      const compareWith = $("compareWith").value;
      const fields = await inject(tab, () => window.__jrpa_sync__.collect());
      const r = await bg("RPA_VERIFY", {
        site: tab.url ? new URL(tab.url).hostname : "",
        pageType,
        compareWith,
        fields: fields || [],
      });
      if (r && r.ok && r.out.ok) {
        $("status").textContent = r.out.summary;
        $("status").className = "ok";
      } else {
        $("status").textContent = "校驗失敗: " + ((r && r.out && r.out.error) || r?.error || "");
        $("status").className = "err";
      }
      return;
    }
    if (type === "FILL") {
      const r = await bg("FILL_PLAN", { taskId: extra.taskId });
      if (!r || !r.ok) throw new Error("獲取填寫方案失敗: " + (r?.error || ""));
      const res = await inject(
        tab,
        (machine) => window.__jrpa_sync__.fill(machine),
        [r.plan.machine_fields || []],
      );
      let note = `✅ 已填寫 ${res ? res.filled : 0} 個欄位`;
      if (res && res.skipped.length) note += "，未匹配: " + res.skipped.slice(0, 6).join("、");
      $("status").textContent = note;
      $("status").className = "ok";
      return;
    }
    $("status").textContent = "未知操作";
    $("status").className = "err";
  } catch (e) {
    $("status").textContent = "操作失敗: " + (e?.message || e);
    $("status").className = "err";
  }
}

$("scrape").addEventListener("click", () => runAction("SCRAPE", {}));
$("fillResume").addEventListener("click", () => runAction("FILL_RESUME", {}));
$("verify").addEventListener("click", () => runAction("VERIFY", {}));
