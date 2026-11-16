import type { ApiEnvelope } from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "bonvera.session";

let token: string | null = sessionStorage.getItem(TOKEN_KEY);

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function setSession(newToken: string | null) {
  token = newToken;
  if (newToken) sessionStorage.setItem(TOKEN_KEY, newToken);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export function hasSession(): boolean {
  return Boolean(token);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("network", "Нет соединения с сервером. Проверь интернет и попробуй ещё раз.", 0);
  }
  let payload: ApiEnvelope<T> | null = null;
  try {
    payload = (await res.json()) as ApiEnvelope<T>;
  } catch {
    payload = null;
  }
  if (!res.ok || !payload || payload.ok === false) {
    const code = payload?.err?.code ?? `http_${res.status}`;
    const message = payload?.err?.message ?? "Ошибка сервера. Попробуй позже.";
    if (res.status === 401) setSession(null);
    throw new ApiError(code, message, res.status);
  }
  return payload.data as T;
}


async function requestBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try { res = await fetch(`${BASE}${path}`, { headers }); }
  catch { throw new ApiError("network", "Нет соединения с сервером.", 0); }
  if (!res.ok) {
    let message = "Не удалось открыть файл."; let code = `http_${res.status}`;
    try { const payload = await res.json(); message = payload?.err?.message ?? message; code = payload?.err?.code ?? code; } catch {}
    if (res.status === 401) setSession(null);
    throw new ApiError(code, message, res.status);
  }
  return res.blob();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  blob: (path: string) => requestBlob(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};

export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress: (pct: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}${path}`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let payload: ApiEnvelope<T> | null = null;
      try {
        payload = JSON.parse(xhr.responseText) as ApiEnvelope<T>;
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300 && payload?.ok) {
        resolve(payload.data as T);
      } else {
        if (xhr.status === 401) setSession(null);
        reject(
          new ApiError(
            payload?.err?.code ?? `http_${xhr.status}`,
            payload?.err?.message ?? "Не удалось загрузить файлы. Попробуй ещё раз.",
            xhr.status,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new ApiError("network", "Нет соединения с сервером. Попробуй ещё раз.", 0));
    xhr.send(form);
  });
}

export { fmtDate, fmtDateTime, rub } from "./format";