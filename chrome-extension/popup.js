const $ = (id) => document.getElementById(id);

/* ── E2EE 密鑰（隱私第二層）：PBKDF2(密碼, 郵箱) → AES-GCM ── */
const _b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const _unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function deriveKeyB64(password, salt) {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: enc.encode(salt), iterations: 100000, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"],
  );
  const raw = await crypto.subtle.exportKey("raw", key);
  return _b64(raw);
}

async function encryptText(keyB64, text) {
  const key = await crypto.subtle.importKey("raw", _unb64(keyB64), "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(text));
  return _b64(iv) + "|" + _b64(ct);
}

async function decryptText(keyB64, data) {
  if (!data || !data.includes("|")) return null;
  try {
    const [ivS, ctS] = data.split("|");
    const key = await crypto.subtle.importKey("raw", _unb64(keyB64), "AES-GCM", false, ["decrypt"]);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: _unb64(ivS) }, key, _unb64(ctS));
    return new TextDecoder().decode(pt);
  } catch {
    return null;
  }
}

const SENSITIVE_RE = /證件|证件|身份證|身份证|護照|护照|家庭|親屬|亲属|緊急聯繫|紧急联系|證件號|证件号|地址|邮编|郵編|電話|电话|手機|手机|姓名拼音/;

async function getKeyB64() {
  const st = await chrome.storage.session.get("rawKeyB64");
  return st.rawKeyB64 || null;
}

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
  const email = $("email").value.trim();
  const password = $("password").value;
  const r = await chrome.runtime.sendMessage({
    type: "SIGNIN",
    email,
    password,
  });
  if (r && r.ok) {
    // 派生 E2EE 密鑰（僅存瀏覽器 session，關閉瀏覽器即清除）
    const keyB64 = await deriveKeyB64(password, "jobfly:" + email);
    await chrome.storage.session.set({ rawKeyB64: keyB64 });
    $("password").value = "";
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

/** 頁面注入：全幀執行同步小函數並返回各幀結果數組（覆蓋 iframe 表單）。 */
async function inject(tab, func, args = []) {
  // 全幀注入庫（表單可能在 iframe 中）
  try {
    const probe = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => !!(window.__jrpa_sync__ && window.__jrpa_run_v3__),
    });
    const missing = probe.some((r) => !(r && r.result));
    if (missing) {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files: ["content.js"],
      });
      await new Promise((r) => setTimeout(r, 400));
    }
  } catch {
    /* 部分幀不可注入（跨域），退回頂層幀 */
  }
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func,
      args,
    });
    return (out || []).map((o) => o.result).filter((r) => r != null);
  } catch {
    const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func, args });
    return [(out || [])[0] ? out[0].result : null].filter((r) => r != null);
  }
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
      const frames = await inject(
        tab,
        () => window.__jrpa_sync__.collect(),
      );
      const fields = (frames || []).flat();
      const panelArgs = [[{ text: `頁面共識別到 ${fields ? fields.length : 0} 個欄位`, ok: null },
          { text: "正在連線 JobsComing 後台…", ok: null }]];
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (ls) => {
          window.__jrpa_sync__.panel("回傳簡歷資料", ls);
          return true;
        },
        args: panelArgs,
      });
      const r = await bg("SCRAPE_SAVE", { site: tab.url ? new URL(tab.url).hostname : "", pageType, fields: fields || [] });
      if (r && r.ok) {
        $("status").textContent = `✅ 已回傳 ${r.out.saved} 個字段到元信息表`;
        $("status").className = "ok";
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: (n) => {
            window.__jrpa_sync__.panel("回傳簡歷資料", [{ text: `✅ 已回傳 ${n} 個字段到元信息表`, ok: true }]);
            return true;
          },
          args: [r.out.saved],
        });
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
      // 敏感字段本地解密
      const keyB64 = await getKeyB64();
      let entries = r.fields || [];
      if (keyB64) {
        entries = await Promise.all(entries.map(async (e) => {
          if (e.encrypted) {
            const pt = await decryptText(keyB64, e.encrypted);
            if (pt != null) return { ...e, value: pt };
          }
          return e;
        }));
      }
      const frames = await inject(
        tab,
        (ents) => window.__jrpa_sync__.fill(ents),
        [entries],
      );
      let filled = 0;
      const skipped = [];
      for (const res of frames || []) {
        filled += res ? res.filled : 0;
        if (res) skipped.push(...(res.skipped || []));
      }
      $("status").textContent = `✅ 已填寫 ${filled} 個欄位` + (skipped.length ? `（未匹配 ${skipped.length} 個）` : "");
      $("status").className = "ok";
      return;
    }
    if (type === "VERIFY") {
      const pageType = $("pageType").value;
      const compareWith = $("compareWith").value;
      const frames = await inject(tab, () => window.__jrpa_sync__.collect());
      const fields = (frames || []).flat();
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
      const frames = await inject(
        tab,
        (machine) => window.__jrpa_sync__.fill(machine),
        [r.plan.machine_fields || []],
      );
      let filled = 0;
      const skipped = [];
      for (const res of frames || []) {
        filled += res ? res.filled : 0;
        if (res) skipped.push(...(res.skipped || []));
      }
      let note = `✅ 已填寫 ${filled} 個欄位`;
      if (skipped.length) note += "，未匹配: " + skipped.slice(0, 6).join("、");
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
