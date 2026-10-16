import { refreshSession, token } from "./auth";
import { beginRequest, endRequest } from "./loading";

/** 後端基址：生產構建注入 VITE_API_BASE_URL（跨域）；本地開發留空走 Vite 代理。 */
const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

/** 帶 JWT 的後端請求封裝；401 時自動嘗試刷新會話並重試一次；自動全局 Loading。 */
export async function api<T = unknown>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  if (!retried) beginRequest();
  const isForm = init.body instanceof FormData;
  try {
    const res = await fetch(BASE + path, {
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
  } finally {
    if (!retried) endRequest();
  }
}
