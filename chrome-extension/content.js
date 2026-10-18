/** JobsComing RPA 填報引擎 — 在已登錄的官網申請頁上自動填寫全部欄位。 */
(() => {
  if (window.__jobsfly_rpa__) return;
  window.__jobsfly_rpa__ = true;

  let panel = null;

  function log(text, ok) {
    if (!panel) return;
    const line = document.createElement("div");
    line.textContent = text;
    line.style.color = ok === false ? "#dc2626" : ok ? "#15803d" : "#374151";
    panel.querySelector(".jrpa-log").appendChild(line);
  }

  function showPanel(title) {
    panel = document.createElement("div");
    panel.style.cssText = [
      "position:fixed;right:16px;bottom:16px;z-index:99999;width:300px;",
      "background:#fff;border:1px solid #e5e7eb;border-radius:10px;",
      "box-shadow:0 8px 30px rgba(0,0,0,.18);padding:12px;font:13px/1.5 system-ui;",
    ].join("");
    panel.innerHTML =
      `<b>🤖 JobsComing RPA 填報</b><div style="color:#6b7280;margin:2px 0 6px">${title}</div>` +
      `<div class="jrpa-log" style="max-height:180px;overflow:auto"></div>` +
      `<button style="margin-top:8px;width:100%;padding:6px;background:#1d4ed8;color:#fff;border:none;border-radius:6px">我已檢查，標記為已投遞</button>`;
    panel.querySelector("button").addEventListener("click", markDone);
    document.body.appendChild(panel);
  }

  async function markDone() {
    const taskId = window.__jobsfly_task__;
    if (!taskId) return;
    const r = await chrome.runtime.sendMessage({
      type: "COMPLETE",
      taskId,
      answer: { confirmed: true, external_ref: "" },
    });
    if (r && r.ok) {
      log("✅ 已通知 JobsComing 標記為已投遞", true);
      panel.querySelector("button").disabled = true;
    } else {
      log("回傳失敗: " + (r?.error || ""), false);
    }
  }

  function collectFields() {
    const out = [];
    document.querySelectorAll("input:not([type=hidden]), textarea, select").forEach((el, i) => {
      const label =
        (el.labels && el.labels[0] && el.labels[0].innerText.trim()) ||
        (el.closest("label") ? el.closest("label").innerText.trim() : "") ||
        el.placeholder ||
        el.name ||
        "";
      out.push({
        el,
        label: label.slice(0, 60),
        type: (el.type || el.tagName.toLowerCase()),
        isFile: el.type === "file",
        isSelect: el.tagName.toLowerCase() === "select",
      });
    });
    return out;
  }

  function matchScore(label, field) {
    const l = label.toLowerCase();
    const f = (field.label || "").toLowerCase();
    const k = (field.key || "").toLowerCase();
    if (l.includes(k) || k.includes(l)) return 3;
    if (l.includes(f) || f.includes(l)) return 2;
    // 關鍵字映射
    const map = {
      name: ["姓名", "name", "名字"],
      phone: ["手機", "电话", "电话", "mobile", "phone", "联系方式"],
      email: ["郵箱", "邮箱", "email", "电子邮箱", "電子郵箱"],
      visa: ["簽證", "签证", "visa"],
      salary: ["薪資", "薪资", "薪酬", "期望薪", "salary"],
      availability: ["到崗", "到岗", "入職", "入职", "available", "時間"],
      skills: ["技能", "特长", "擅長", "skill"],
      experience: ["經歷", "经历", "工作", "实习", "经验", "experience"],
      education: ["教育", "学历", "學歷", "學校", "学校", "毕业", "education"],
    };
    const kws = map[field.key] || [];
    if (kws.some((w) => l.includes(w))) return 1;
    return 0;
  }

  async function fillValue(fieldInfo, value) {
    const { el, isSelect } = fieldInfo;
    if (el.readOnly || el.disabled) return false;
    try {
      if (isSelect) {
        const opts = Array.from(el.options);
        const target = opts.find(
          (o) => o.text.includes(value) || value.includes(o.text),
        );
        if (target) {
          el.value = target.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        }
        return false;
      }
      const proto = el.tagName.toLowerCase() === "textarea"
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.style.outline = "2px solid #16a34a";
      el.style.outlineOffset = "2px";
      return true;
    } catch {
      return false;
    }
  }

  async function uploadResume(fileInputs, resume) {
    if (!fileInputs.length || !resume || !resume.download_url) {
      log(fileInputs.length ? "⚠️ 簡歷無下載地址，請手動上傳" : "ℹ️ 本頁無文件上傳欄位");
      return;
    }
    const r = await chrome.runtime.sendMessage({
      type: "DOWNLOAD",
      url: resume.download_url,
    });
    if (!r || !r.ok) {
      log("簡歷下載失敗: " + (r?.error || ""), false);
      return;
    }
    const b64 = r.dataUrl.split(",")[1];
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const file = new File([arr], resume.name || "resume.pdf", { type: "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    const input = fileInputs[0];
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.style.outline = "2px solid #16a34a";
    log(`📎 已上傳簡歷「${file.name}」`, true);
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    (async () => {
      if (msg.type === "PING") {
        sendResponse({ ok: true });
        return;
      }
      // ── 簡歷維護助手：回傳 / 填報 / 校驗 ──
      if (msg.type === "SCRAPE") {
        const fields = collectFields()
          .filter((f) => !f.isFile)
          .map((f) => ({ label: f.label, value: f.el.value || "" }));
        const r = await chrome.runtime.sendMessage({
          type: "SCRAPE_SAVE",
          site: location.hostname,
          pageType: msg.pageType,
          fields,
        });
        showPanel(`回傳「${msg.pageType}」`);
        if (r && r.ok) log(`✅ 已回傳 ${r.out.saved} 個字段到元信息表`, true);
        else log("回傳失敗: " + (r?.error || ""), false);
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "FILL_RESUME") {
        const r = await chrome.runtime.sendMessage({ type: "RPA_FIELDS" });
        if (!r || !r.ok) {
          alert("讀取元信息失敗: " + (r?.error || ""));
          sendResponse({ ok: false });
          return;
        }
        showPanel(`填報「${msg.pageType}」`);
        const fields = collectFields();
        let filled = 0;
        const skipped = [];
        for (const f of fields) {
          if (f.isFile) continue;
          if (!f.label) continue;
          const best = r.fields
            .map((m) => ({ m, s: matchScore(f.label, m) }))
            .filter((x) => x.s > 0 && x.m.value)
            .sort((a, b) => b.s - a.s)[0];
          if (best) {
            if (await fillValue(f, best.m.value)) filled++;
          } else {
            skipped.push(f.label);
          }
        }
        log(`✅ 已填寫 ${filled} 個欄位`, true);
        if (skipped.length) log("未匹配（需手動填）: " + skipped.slice(0, 12).join("、"), false);
        sendResponse({ ok: true, filled });
        return;
      }
      if (msg.type === "VERIFY") {
        const fields = collectFields()
          .filter((f) => !f.isFile)
          .map((f) => ({ label: f.label, value: f.el.value || "" }));
        const r = await chrome.runtime.sendMessage({
          type: "RPA_VERIFY",
          site: location.hostname,
          pageType: msg.pageType,
          compareWith: msg.compareWith,
          fields,
        });
        showPanel(`校驗「${msg.pageType}」`);
        if (r && r.ok && r.out.ok) {
          log(r.out.summary, true);
          for (const d of r.out["不一致"] || []) {
            log(`⚠️ ${d.label}: 已存「${d.base}」≠ 當前「${d.current}」`, false);
          }
          for (const m of r.out["缺失"] || []) {
            log(`❌ 缺失: ${m.label}（已存值「${m.base}」未填入）`, false);
          }
        } else {
          log("校驗失敗: " + ((r && r.out && r.out.error) || r?.error || ""), false);
        }
        sendResponse({ ok: true });
        return;
      }
      // ── 申請頁填報（原有流程）──
      if (msg.type !== "FILL") return;
    (async () => {
      const taskId = msg.taskId;
      window.__jobsfly_task__ = taskId;
      const r = await chrome.runtime.sendMessage({ type: "FILL_PLAN", taskId });
      if (!r || !r.ok) {
        alert("獲取填寫方案失敗: " + (r?.error || ""));
        sendResponse({ ok: false });
        return;
      }
      const plan = r.plan;
      showPanel(`${plan.company} · ${plan.title}`);
      log(`開始填報「${plan.title}」`);
      const fields = collectFields();
      const machine = plan.machine_fields || [];
      const fileInputs = fields.filter((f) => f.isFile).map((f) => f.el);

      let filled = 0;
      const skipped = [];
      for (const f of fields) {
        if (f.isFile) continue;
        const best = machine
          .map((m) => ({ m, s: matchScore(f.label, m) }))
          .filter((x) => x.s > 0 && x.m.value)
          .sort((a, b) => b.s - a.s)[0];
        if (best) {
          const ok = await fillValue(f, best.m.value);
          if (ok) filled++;
        } else if (f.label) {
          skipped.push(f.label);
        }
      }
      log(`✅ 已自動填寫 ${filled} 個欄位`, true);
      if (skipped.length) log("未匹配欄位（請手動填）: " + skipped.slice(0, 8).join("、"), false);
      await uploadResume(fileInputs, plan.resume);
      log("檢查高亮欄位無誤後點「提交」，再回面板點「標記為已投遞」");
      sendResponse({ ok: true, filled });
    })();
    return true;
  });
})();
