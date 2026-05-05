export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API ${status}`);
  }
}

function getApiBaseUrl() {
  const explicit = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "");
  if (explicit) return explicit.endsWith("/api") ? explicit : `${explicit}/api`;

  if (process.env.NODE_ENV === "development" && typeof window !== "undefined") {
    return "http://localhost:8000/api";
  }

  return "/api";
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getApiBaseUrl();
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const res = await fetch(`${base}${normalizedPath}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body);
  }
  return res.json() as Promise<T>;
}

export interface UserMe {
  id: string;
  email: string;
  name: string;
  plan: string;
  credits: { used: number; total: number; unit: string };
  youtube_channel_ids: string[];
}
