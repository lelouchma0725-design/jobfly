/** 客戶端 E2EE（隱私第二層）：PBKDF2(密碼, 郵箱) → AES-GCM。密鑰僅存 sessionStorage。 */
const _b64 = (buf: ArrayBuffer) =>
  btoa(String.fromCharCode(...new Uint8Array(buf)));
const _unb64 = (s: string): ArrayBuffer =>
  Uint8Array.from(atob(s), (c) => c.charCodeAt(0)).buffer as ArrayBuffer;

export async function deriveKeyB64(password: string, salt: string): Promise<string> {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: enc.encode(salt), iterations: 100000, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  return _b64(await crypto.subtle.exportKey("raw", key));
}

export function getKeyB64(): string | null {
  return sessionStorage.getItem("jobfly_e2ee_key");
}

export function setKeyB64(key: string | null) {
  if (key) sessionStorage.setItem("jobfly_e2ee_key", key);
  else sessionStorage.removeItem("jobfly_e2ee_key");
}

export async function encryptText(keyB64: string, text: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", _unb64(keyB64), "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12)).buffer as ArrayBuffer;
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(text));
  return `${_b64(iv)}|${_b64(ct)}`;
}

export async function decryptText(keyB64: string, data: string): Promise<string | null> {
  if (!data || !data.includes("|")) return null;
  try {
    const [ivS, ctS] = data.split("|");
    const key = await crypto.subtle.importKey("raw", _unb64(keyB64), "AES-GCM", false, ["decrypt"]);
    const pt = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: _unb64(ivS) },
      key,
      _unb64(ctS),
    );
    return new TextDecoder().decode(pt);
  } catch {
    return null;
  }
}

export const SENSITIVE_RE =
  /證件|证件|身份證|身份证|護照|护照|家庭|親屬|亲属|緊急聯繫|紧急联系|證件號|证件号|地址|邮编|郵編|電話|电话|手機|手机|姓名拼音|父|母/;

export function generateRecoveryCode(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const arr = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(arr, (b) => chars[b % chars.length]).join("");
}

async function _codeKey(code: string): Promise<CryptoKey> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(code.trim()));
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]);
}

/** 用恢復碼包裝 E2EE 密鑰（存服務器，供新設備/改密碼後恢復）。 */
export async function wrapKeyWithCode(keyB64: string, code: string): Promise<string> {
  const key = await _codeKey(code);
  const iv = crypto.getRandomValues(new Uint8Array(12)).buffer as ArrayBuffer;
  const ct = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(keyB64),
  );
  return _b64(iv) + "." + _b64(ct);
}

/** 用恢復碼解出 E2EE 密鑰。碼錯誤時拋出。 */
export async function unwrapKeyWithCode(wrapped: string, code: string): Promise<string> {
  const [ivB64, ctB64] = wrapped.split(".");
  const key = await _codeKey(code);
  const iv = new Uint8Array(_unb64(ivB64));
  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv.buffer as ArrayBuffer },
    key,
    _unb64(ctB64),
  );
  return new TextDecoder().decode(pt);
}

/** 生成安全密鑰（32 字符，僅顯示一次）。 */
export function generateSecretKey(): string {
  return generateRecoveryCode();
}
