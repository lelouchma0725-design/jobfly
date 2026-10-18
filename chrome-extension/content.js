/** JobsComing RPA 填報引擎 v0.6.1 — 單一 IIFE，全同步微操作 + 消息監聽。 */
(() => {
  const GUARD = "__jobsfly_rpa_v2__";
  if (window[GUARD]) return;
  window[GUARD] = true;

  /** 從網址自動識別中信簡歷類型（name=xiaozhao-cn 等） */
  function detectPageType() {
    try {
      const u = new URL(location.href);
      const name = u.searchParams.get("name") || "";
      const map = {
        "xiaozhao-cn": "校園招聘簡歷",
        "xiaozhao-fz": "分支校園招聘簡歷",
        "shezhao-cn": "社會招聘簡歷",
        "shezhao-fz": "分支社會招聘簡歷",
      };
      return map[name] || "";
    } catch {
      return "";
    }
  }

  let panel = null;

  function log(text, ok) {
    if (!panel) return;
    const line = document.createElement("div");
    line.textContent = text;
    line.style.color = ok === false ? "#dc2626" : ok ? "#15803d" : "#374151";
    panel.querySelector(".jrpa-log").appendChild(line);
  }

  function showPanel(title) {
    if (panel && panel.isConnected) return;
    panel = document.createElement("div");
    panel.style.cssText = [
      "position:fixed;right:16px;bottom:16px;z-index:99999;width:300px;",
      "background:#fff;border:1px solid #e5e7eb;border-radius:10px;",
      "box-shadow:0 8px 30px rgba(0,0,0,.18);padding:12px;font:13px/1.5 system-ui;",
    ].join("");
    panel.innerHTML =
      `<b>🤖 JobsComing RPA 填報</b><div style="color:#6b7280;margin:2px 0 6px">${title}</div>` +
      `<div class="jrpa-log" style="max-height:180px;overflow:auto"></div>`;
    document.body.appendChild(panel);
  }

  function collectFields() {
    const out = [];
    document.querySelectorAll("input:not([type=hidden]), textarea, select").forEach((el) => {
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
    const map = {
      name: ["姓名", "名字", "name"],
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

  function fillValue(fieldInfo, value) {
    const { el, isSelect } = fieldInfo;
    if (el.readOnly || el.disabled) return false;
    try {
      if (isSelect) {
        const opts = Array.from(el.options);
        const target = opts.find((o) => o.text.includes(value) || value.includes(o.text));
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

  // ── 同步 API（popup 以 executeScript 直接調用，頁面側零異步）──

  function syncCollect() {
    return collectFields()
      .filter((f) => !f.isFile)
      .map((f) => ({ label: f.label, value: f.el.value || "" }));
  }

  function syncFill(entries) {
    const fields = collectFields();
    let filled = 0;
    const skipped = [];
    for (const f of fields) {
      if (f.isFile) continue;
      if (!f.label) continue;
      const best = (entries || [])
        .map((m) => ({ m, s: matchScore(f.label, m) }))
        .filter((x) => x.s > 0 && x.m.value)
        .sort((a, b) => b.s - a.s)[0];
      if (best) {
        if (fillValue(f, best.m.value)) filled++;
      } else {
        skipped.push(f.label);
      }
    }
    return { filled, skipped };
  }

  function syncUploadResume(fileInfo) {
    const inputs = collectFields().filter((f) => f.isFile).map((f) => f.el);
    if (!inputs.length) return { uploaded: false, note: "本頁無文件上傳欄位" };
    if (!fileInfo || !fileInfo.dataUrl) return { uploaded: false, note: "無簡歷文件" };
    try {
      const b64 = fileInfo.dataUrl.split(",")[1];
      const bin = atob(b64);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      const file = new File([arr], fileInfo.name || "resume.pdf", { type: "application/pdf" });
      const dt = new DataTransfer();
      dt.items.add(file);
      inputs[0].files = dt.files;
      inputs[0].dispatchEvent(new Event("change", { bubbles: true }));
      inputs[0].style.outline = "2px solid #16a34a";
      return { uploaded: true, name: file.name };
    } catch (e) {
      return { uploaded: false, note: String(e) };
    }
  }

  function syncPanel(title, lines) {
    showPanel(title);
    for (const l of lines || []) log(l.text, l.ok);
  }

  window.__jrpa_sync__ = {
    collect: syncCollect,
    fill: syncFill,
    upload: syncUploadResume,
    panel: syncPanel,
    detectPageType,
  };
  window.__jrpa_run_v3__ = true;
})();
