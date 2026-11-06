/** 兩層密鑰：第二層（核心功能）解鎖狀態。密鑰在內存/會話中，服務器只存包裝密文。 */

const KEY = "jobfly_unlocked";
const GATE_KEY = "jobfly_gate";

/** 是否已設置安全密鑰（設置過 → 核心功能需要解鎖）。 */
export function gateEnabled(): boolean {
  try {
    return sessionStorage.getItem(GATE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setGateEnabled(v: boolean): void {
  try {
    if (v) sessionStorage.setItem(GATE_KEY, "1");
    else sessionStorage.removeItem(GATE_KEY);
  } catch {
    /* 忽略 */
  }
}

/** 從服務器刷新「是否已設置安全密鑰」狀態。 */
export async function refreshGate(): Promise<boolean> {
  try {
    const r = await fetch("/api/me/e2ee/unlock-status", {
      headers: { Authorization: `Bearer ${sessionStorage.getItem("access_token") ?? localStorage.getItem("access_token") ?? ""}` },
    });
    if (r.ok) {
      const d = await r.json();
      setGateEnabled(!!d.has_unlock_key);
      return !!d.has_unlock_key;
    }
  } catch {
    /* 忽略 */
  }
  return gateEnabled();
}

export function isUnlocked(): boolean {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setUnlocked(v: boolean): void {
  try {
    if (v) sessionStorage.setItem(KEY, "1");
    else sessionStorage.removeItem(KEY);
  } catch {
    /* 忽略 */
  }
}

export function listenUnlocked(fn: (v: boolean) => void): () => void {
  const fire = () => fn(isUnlocked());
  window.addEventListener("jobfly-unlock-change", fire);
  return () => window.removeEventListener("jobfly-unlock-change", fire);
}

export function emitUnlockChange(): void {
  window.dispatchEvent(new Event("jobfly-unlock-change"));
}
