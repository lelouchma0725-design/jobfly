/** 兩層密鑰：第二層（核心功能）解鎖狀態。密鑰在內存/會話中，服務器只存包裝密文。 */

const KEY = "jobfly_unlocked";

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
