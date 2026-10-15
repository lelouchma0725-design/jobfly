import { refreshSession, token } from "./auth";

/** 帶 JWT 的後端請求封裝；401 時自動嘗試刷新會話並重試一次。 */
export async function api<T = unknown>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 401 && !retried) {
    const fresh = await refreshSession();
    if (fresh) return api<T>(path, init, true);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
