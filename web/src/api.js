export const DEFAULT_API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

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
  if (data.length === 0) return null;
  const rawData = data.join("\n");
  let payload = rawData;
  try {
    payload = JSON.parse(rawData);
  } catch {
    // Non-JSON data is still a valid SSE payload.
  }
  return { event, data: payload };
}

export async function apiRequest(baseUrl, path, options = {}) {
  const startedAt = performance.now();
  const response = await fetch(buildUrl(baseUrl, path), options);
  const data = response.status === 204 ? null : await parseResponse(response);
  const elapsed = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    const detail =
      typeof data === "object" && data
        ? data.detail || data.message || JSON.stringify(data)
        : data;
    throw new Error(`${response.status} ${response.statusText}: ${detail || "请求失败"}`);
  }
  return { data, status: response.status, elapsed };
}

export async function streamSse(baseUrl, path, options = {}, onEvent = () => {}) {
  const startedAt = performance.now();
  const response = await fetch(buildUrl(baseUrl, path), {
    ...options,
    headers: {
      Accept: "text/event-stream",
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const data = response.status === 204 ? null : await parseResponse(response);
    const detail =
      typeof data === "object" && data
        ? data.detail || data.message || JSON.stringify(data)
        : data;
    throw new Error(`${response.status} ${response.statusText}: ${detail || "请求失败"}`);
  }
  if (!response.body) throw new Error("浏览器未提供可读取的流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  async function dispatchFrames(flush = false) {
    buffer = buffer.replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = flush ? "" : frames.pop() || "";
    for (const frame of frames) {
      const parsed = parseSseFrame(frame);
      if (parsed) await onEvent(parsed);
    }
    if (flush && buffer.trim()) {
      const parsed = parseSseFrame(buffer);
      if (parsed) await onEvent(parsed);
      buffer = "";
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      await dispatchFrames(done);
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }

  return {
    status: response.status,
    elapsed: Math.round(performance.now() - startedAt),
  };
}
