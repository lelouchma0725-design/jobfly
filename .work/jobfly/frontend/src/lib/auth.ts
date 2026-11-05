/** 會話管理：登錄/註冊走後端認證代理（瀏覽器不直連 supabase.co）。 */

export type AuthSession = {
  access_token: string;
  refresh_token: string;
  user: { id: string; email: string };
};

const KEY = "jobfly_session";

function parseSession(raw: unknown): AuthSession | null {
  if (!raw || typeof raw !== "object") return null;
  const s = raw as { access_token?: string; refresh_token?: string; user?: { id?: string; email?: string } };
  if (!s.access_token || !s.refresh_token || !s.user?.id) return null;
  return s as AuthSession;
}

export function getSession(): AuthSession | null {
  try {
    return parseSession(JSON.parse(localStorage.getItem(KEY) ?? "null"));
  } catch {
    return null;
  }
}

function saveSession(s: AuthSession | null) {
  if (s) localStorage.setItem(KEY, JSON.stringify(s));
  else localStorage.removeItem(KEY);
}

export function token(): string | null {
  return getSession()?.access_token ?? null;
}

async function post<T = unknown>(path: string, body: unknown): Promise<T> {
  const base =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
    (import.meta.env.PROD ? "https://jobscoming-backend.onrender.com" : "");
  const res = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { detail?: string }).detail || `HTTP ${res.status}`);
  return data as T;
}

export async function signIn(email: string, password: string): Promise<AuthSession> {
  const data = await post<{ access_token: string; refresh_token: string; user: { id: string; email: string } }>(
    "/api/auth/signin",
    { email, password },
  );
  const session = { access_token: data.access_token, refresh_token: data.refresh_token, user: data.user };
  saveSession(session);
  return session;
}

export async function signUp(email: string, password: string): Promise<{ status: string }> {
  const data = await post<{ status: string; session?: unknown }>("/api/auth/signup", { email, password });
  if (data.session) {
    const s = parseSession(data.session);
    if (s) saveSession(s);
  }
  return { status: data.status };
}

export async function magicLink(email: string): Promise<void> {
  await post("/api/auth/magic-link", { email });
}

export async function signOut(): Promise<void> {
  saveSession(null);
}

export async function refreshSession(): Promise<AuthSession | null> {
  const s = getSession();
  if (!s?.refresh_token) return null;
  try {
    const data = await post<{ access_token: string; refresh_token: string; user: { id: string; email: string } }>(
      "/api/auth/refresh",
      { refresh_token: s.refresh_token },
    );
    const next = { access_token: data.access_token, refresh_token: data.refresh_token, user: data.user };
    saveSession(next);
    return next;
  } catch {
    saveSession(null);
    return null;
  }
}
