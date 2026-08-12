export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const prefix = API_BASE.replace(/\/$/, "");
  return `${prefix}${path.startsWith("/") ? path : `/${path}`}`;
}

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(apiUrl(path), { ...init, headers, credentials: "include" });
}

export type AuthUser = {
  id: string;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
};
