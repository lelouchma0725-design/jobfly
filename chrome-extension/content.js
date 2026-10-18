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
      out.push({
        el,
        label: labelFor(el),
        context: contextFor(el),
        type: (el.type || el.tagName.toLowerCase()),
        isFile: el.type === "file",
        isSelect: el.tagName.toLowerCase() === "select",
      });
    });
    return out;
  }

  /** 精確提取欄位標籤：label 元素 → 表單項 label → placeholder/name，避免抓到整塊長文本。 */
  function labelFor(el) {
    const ok = (t) => t && t.length >= 1 && t.length <= 40;
    if (el.labels && el.labels[0]) {
      const t = el.labels[0].innerText.trim();
      if (ok(t)) return t;
    }
    const item = el.closest(".el-form-item, .form-item, .ant-form-item, .ivu-form-item, .form-group");
    if (item) {
      const lab = item.querySelector(":scope > label, .el-form-item__label, .form-label, .label, .ant-form-item-label");
      if (lab) {
        const t = lab.innerText.trim();
        if (ok(t)) return t;
      }
    }
    if (el.placeholder && ok(el.placeholder.trim())) return el.placeholder.trim();
    if (el.name && ok(el.name)) return el.name;
    return "";
  }

  /** 上下文聯想：重複 label 時（如父親/母親的工作單位）取前面緊鄰的說明文本。 */
  function contextFor(el) {
    const item = el.closest(".el-form-item, .form-item, .ant-form-item, .ivu-form-item");
    if (!item || !item.parentElement) return "";
    const siblings = Array.from(item.parentElement.children);
    const idx = siblings.indexOf(item);
    for (let i = idx - 1; i >= 0 && i >= idx - 2; i--) {
      const t = (siblings[i].innerText || "").trim();
      if (t && t.length <= 20 && !t.includes("：") && t !== item.innerText.trim()) {
        return t.slice(0, 20);
      }
    }
    return "";
  }

  function matchScore(label, field) {
    const l = label.toLowerCase();
    const f = (field.label || "").toLowerCase();
    const k = (field.key || "").toLowerCase();
    const short = (s) => s.length >= 1 && s.length <= 12;
    // 精確/包含匹配僅限短標籤（長文本 label 不得參與模糊包含，防止誤填）
    if (short(l) && short(f) && (l.includes(f) || f.includes(l))) return 3;
    if (short(l) && short(k) && (l.includes(k) || k.includes(l))) return 3;
    if (l === f) return 3;
    const map = {
      name: ["姓名", "名字", "name"],
      phone: ["手機", "电话", "电话", "mobile", "phone", "联系方式"],
      email: ["郵箱", "邮箱", "email", "电子邮箱", "電子郵箱"],
      visa: ["簽證", "签证", "visa"],
      salary: ["薪資", "薪资", "薪酬", "期望薪", "salary"],
      availability: ["到崗", "到岗", "入職", "入职", "available"],
      skills: ["技能", "特长", "擅長", "skill"],
      experience: ["工作經歷", "工作经历", "實習經歷", "实习经历", "工作經驗", "experience"],
      education: ["教育", "学历", "學歷", "學校", "学校", "毕业", "education"],
    };
    if (short(l)) {
      const kws = map[field.key] || [];
      if (kws.some((w) => l.includes(w))) return 1;
    }
    return 0;
  }

  /** 姓/名拆分與下拉值適配。 */
  function adaptValue(fieldInfo, field, value) {
    const l = (fieldInfo.label || "").toLowerCase();
    if (field.key === "name" && (l === "姓" || l === "姓氏")) return String(value || "").slice(0, 1);
    if (field.key === "name" && l === "名") return String(value || "").slice(1);
    return value;
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
      .map((f) => ({
        // 上下文聯想：重複 label 加前綴（如「父親｜工作單位」）
        label: f.context ? `${f.context}｜${f.label}` : f.label,
        value: f.el.value || "",
      }));
  }

  function syncFill(entries) {
    const fields = collectFields();
    let filled = 0;
    const skipped = [];
    for (const f of fields) {
      if (f.isFile) continue;
      if (!f.label) continue;
      // 拼音欄位無數據源，永不自動填（列入手動清單）
      if (f.label.includes("拼音")) {
        skipped.push(f.label);
        continue;
      }
      const best = (entries || [])
        .map((m) => {
          const parts = String(m.label || "").split("｜");
          const ctx = parts.length > 1 ? parts[0] : "";
          const plainLabel = parts.pop();
          let s = matchScore(f.label, { ...m, label: plainLabel });
          // 上下文聯想優先：父親/母親等前綴一致 +5
          if (ctx && f.context && (f.context.includes(ctx) || ctx.includes(f.context))) s += 5;
          else if (ctx && f.label.includes("父") && ctx.includes("父")) s += 5;
          else if (ctx && f.label.includes("母") && ctx.includes("母")) s += 5;
          else if (ctx && f.label.includes(ctx)) s += 5;
          return { m, plainLabel, s };
        })
        .filter((x) => x.s > 0 && x.m.value)
        .sort((a, b) => b.s - a.s)[0];
      if (best) {
        const v = adaptValue(f, best.m, String(best.m.value));
        if (fillValue(f, v)) filled++;
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
