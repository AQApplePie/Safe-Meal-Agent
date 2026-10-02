export const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, "");
}

export function buildUrl(baseUrl, path) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${normalizeBaseUrl(baseUrl)}${path.startsWith("/") ? path : `/${path}`}`;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function errorDetail(data) {
  if (!data || typeof data !== "object") return String(data || "请求失败");
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("；");
  return data.detail || data.message || data.error || JSON.stringify(data);
}

function parseSseFrame(frame) {
  let event = "message";
  const data = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  const raw = data.join("\n");
  try { return { event, data: JSON.parse(raw) }; } catch { return { event, data: raw }; }
}

export async function apiRequest(baseUrl, path, options = {}) {
  const response = await fetch(buildUrl(baseUrl, path), options);
  const data = response.status === 204 ? null : await parseResponse(response);
  if (!response.ok) throw new ApiError(response.status, errorDetail(data), data);
  return { data, status: response.status };
}

export async function streamSse(baseUrl, path, options = {}, onEvent = () => {}) {
  const response = await fetch(buildUrl(baseUrl, path), {
    ...options,
    headers: { Accept: "text/event-stream", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const data = response.status === 204 ? null : await parseResponse(response);
    throw new ApiError(response.status, errorDetail(data), data);
  }
  if (!response.body) throw new Error("浏览器未提供流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const parsed = parseSseFrame(frame);
        if (parsed) await onEvent(parsed);
      }
      if (done) {
        const parsed = parseSseFrame(buffer);
        if (parsed) await onEvent(parsed);
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
  return { status: response.status };
}
