const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// FastAPI's HTTPException responses are {"detail": "..."} — surface that
// text directly when present, since it's already a human-readable message
// (see backend/app/api/imports.py), instead of a generic "failed with 400".
async function unwrap<T>(path: string, resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail: string | undefined;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // body wasn't JSON (or was empty) - fall through to the generic message.
    }
    throw new ApiError(resp.status, detail ?? `Request to ${path} failed with ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  return unwrap<T>(path, resp);
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return unwrap<T>(path, resp);
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  return unwrap<T>(path, resp);
}
