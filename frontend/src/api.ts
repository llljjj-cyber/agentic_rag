export const API = import.meta.env.VITE_API_URL ?? "";

export type Conversation = {
  id: number;
  title: string;
  created_at: string;
};

export type SourceStatus = "pending" | "processing" | "ready" | "failed";

export type SourceMeta = {
  id: string;
  title: string;
  modality: string;
  summary?: string;
  created_at?: string;
  status?: SourceStatus;
  error_message?: string | null;
  shelf_id?: string | null;
  shelf_name?: string | null;
  chunk_count?: number;
};

export type Shelf = {
  id: string;
  name: string;
  created_at: string;
  source_count?: number;
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export function formatApiDetail(detail: unknown, fallback: string) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .join("；");
  }
  return fallback;
}

export async function apiFetch<T = unknown>(
  path: string,
  token: string | null,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API}${path}`, { ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(
      formatApiDetail((data as { detail?: unknown }).detail, `请求失败（${res.status}）`),
    );
    (error as Error & { status?: number }).status = res.status;
    throw error;
  }
  return data as T;
}

export async function listConversations(token: string): Promise<Conversation[]> {
  return apiFetch<Conversation[]>("/conversations", token);
}

export async function listMessages(token: string, convId: number): Promise<ChatMessage[]> {
  return apiFetch<ChatMessage[]>(`/conversations/${convId}/messages`, token);
}

export async function deleteConversation(token: string, convId: number): Promise<void> {
  await apiFetch(`/conversations/${convId}`, token, { method: "DELETE" });
}

export async function renameConversation(
  token: string,
  convId: number,
  title: string,
): Promise<Conversation> {
  return apiFetch<Conversation>(`/conversations/${convId}/title`, token, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function listShelves(token: string): Promise<Shelf[]> {
  return apiFetch<Shelf[]>("/shelves", token);
}

export async function createShelf(token: string, name: string): Promise<Shelf> {
  return apiFetch<Shelf>("/shelves", token, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function renameShelf(token: string, shelfId: string, name: string): Promise<Shelf> {
  return apiFetch<Shelf>(`/shelves/${shelfId}`, token, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function deleteShelf(token: string, shelfId: string): Promise<void> {
  await apiFetch(`/shelves/${shelfId}`, token, { method: "DELETE" });
}

export async function deleteSource(token: string, sourceId: string): Promise<void> {
  await apiFetch(`/sources/${sourceId}`, token, { method: "DELETE" });
}

export async function renameSource(
  token: string,
  sourceId: string,
  title: string,
): Promise<{ source: SourceMeta; space?: unknown }> {
  return apiFetch(`/sources/${sourceId}/title`, token, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function moveSourceToShelf(
  token: string,
  sourceId: string,
  shelfId: string | null,
): Promise<{ source: SourceMeta; space?: unknown }> {
  return apiFetch(`/sources/${sourceId}/shelf`, token, {
    method: "PATCH",
    body: JSON.stringify({ shelf_id: shelfId }),
  });
}

export async function getSource(token: string, sourceId: string): Promise<SourceMeta> {
  const data = await apiFetch<{ source: SourceMeta }>(`/sources/${sourceId}`, token);
  return data.source;
}

export type SourceDetailResult =
  | { kind: "busy"; status: "pending" | "processing" }
  | { kind: "ready"; source: SourceMeta }
  | { kind: "failed"; message: string };

export async function getSourceDetail(token: string, sourceId: string): Promise<SourceDetailResult> {
  const res = await fetch(`${API}/sources/${sourceId}/detail`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 500) {
    return {
      kind: "failed",
      message: formatApiDetail((data as { detail?: unknown }).detail, "入库失败"),
    };
  }
  if (!res.ok) {
    const error = new Error(
      formatApiDetail((data as { detail?: unknown }).detail, `请求失败（${res.status}）`),
    );
    (error as Error & { status?: number }).status = res.status;
    throw error;
  }

  const status = (data as { status?: string }).status;
  if (status === "pending" || status === "processing") {
    return { kind: "busy", status };
  }

  const source = (data as { source?: SourceMeta }).source;
  if (source?.id) {
    return { kind: "ready", source: { ...source, status: source.status ?? "ready" } };
  }

  return { kind: "failed", message: "未返回资料详情" };
}

const POLL_INTERVAL_MS = 2500;
const POLL_MAX_ATTEMPTS = 72; // ~3 minutes

export async function waitForSourceReady(
  token: string,
  sourceId: string,
): Promise<SourceMeta> {
  for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
    const result = await getSourceDetail(token, sourceId);
    if (result.kind === "ready") return result.source;
    if (result.kind === "failed") {
      throw new Error(result.message);
    }
    await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error("入库超时，请稍后在知识库中查看");
}

export type IngestInput =
  | { kind: "text"; title: string; text: string; shelf_id?: string | null }
  | { kind: "url"; url: string; title?: string; shelf_id?: string | null }
  | { kind: "file"; file: File; title: string; shelf_id?: string | null };

export async function ingestSource(token: string, input: IngestInput): Promise<SourceMeta> {
  if (input.kind === "text") {
    const data = await apiFetch<{ source: SourceMeta }>("/sources/text", token, {
      method: "POST",
      body: JSON.stringify({
        title: input.title || "未命名",
        text: input.text,
        modality: "text",
        shelf_id: input.shelf_id ?? null,
      }),
    });
    return data.source;
  }

  if (input.kind === "url") {
    const data = await apiFetch<{ source: SourceMeta }>("/sources/url", token, {
      method: "POST",
      body: JSON.stringify({
        url: input.url,
        title: input.title || undefined,
        shelf_id: input.shelf_id ?? null,
      }),
    });
    return data.source;
  }

  const form = new FormData();
  form.append("title", input.title);
  form.append("file", input.file);
  if (input.shelf_id) form.append("shelf_id", input.shelf_id);
  const data = await apiFetch<{ source: SourceMeta }>("/sources/file", token, {
    method: "POST",
    body: form,
  });
  return data.source;
}

export async function fetchSourceFile(token: string, sourceId: string): Promise<Blob> {
  const res = await fetch(`${API}/sources/${sourceId}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const error = new Error(
      formatApiDetail((data as { detail?: unknown }).detail, `无法读取文件（${res.status}）`),
    );
    (error as Error & { status?: number }).status = res.status;
    throw error;
  }
  return res.blob();
}

export const READABLE_MODALITIES = new Set(["pdf", "md", "txt"]);

export function isSourceBusy(status?: SourceStatus) {
  return status === "pending" || status === "processing";
}

export type RetrievalMatch = {
  source_id: string;
  score?: number;
};

type StreamMeta = {
  conv_id?: number;
  type?: string;
  error?: string;
  detail?: string;
  query_point?: SpacePoint;
  matches?: Array<{
    source_id?: string;
    id?: string;
    score?: number;
    similarity?: number;
  }>;
  space?: unknown;
};
export type SpacePoint = {
  id: string;
  source_id: string;
  title: string;
  modality: string;
  projection: { x: number; y: number; z: number };
  color?: string;
  preview?: string;
};

export type StreamPayload =
  | { kind: "conv_id"; convId: number }
  | { kind: "retrieval"; query_point?: SpacePoint; matches: RetrievalMatch[]; space?: unknown }
  | { kind: "error"; code: string; detail?: string; message: string }
  | { kind: "text"; text: string }
  | { kind: "done" };

export function formatStreamError(code: string, detail?: string): string {
  if (code === "llm_unavailable") {
    return "模型服务暂时不可用（已触发熔断保护），请稍后重试。";
  }
  return detail?.trim() || "对话失败，请稍后重试。";
}

function normalizeRetrievalMatches(
  matches: StreamMeta["matches"],
): RetrievalMatch[] {
  if (!matches?.length) return [];
  const out: RetrievalMatch[] = [];
  for (const m of matches) {
    const sourceId = m.source_id || m.id;
    if (!sourceId) continue;
    const score =
      typeof m.score === "number"
        ? m.score
        : typeof m.similarity === "number"
          ? m.similarity
          : undefined;
    out.push({ source_id: String(sourceId), score });
  }
  return out;
}

export function parseStreamPayload(raw: string): StreamPayload | null {
  const payload = raw.trim();
  if (!payload) return null;
  if (payload === "[DONE]") return { kind: "done" };
  if (payload.startsWith("{")) {
    try {
      const meta = JSON.parse(payload) as StreamMeta;
      if (typeof meta.conv_id === "number") {
        return { kind: "conv_id", convId: meta.conv_id };
      }
      if (typeof meta.error === "string" && meta.error) {
        return {
          kind: "error",
          code: meta.error,
          detail: typeof meta.detail === "string" ? meta.detail : undefined,
          message: formatStreamError(
            meta.error,
            typeof meta.detail === "string" ? meta.detail : undefined,
          ),
        };
      }
      if (meta.type === "retrieval") {
        return {
          kind: "retrieval",
          query_point: meta.query_point,
          matches: normalizeRetrievalMatches(meta.matches),
          space: meta.space,
        };
      }
    } catch {
      return { kind: "text", text: payload };
    }
  }
  return { kind: "text", text: payload };
}

export async function streamChat(
  token: string,
  body: { message: string; conv_id?: number | null },
  onPayload: (payload: StreamPayload) => void,
): Promise<void> {
  const headers = new Headers({
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  });
  const res = await fetch(`${API}/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const error = new Error(
      formatApiDetail((data as { detail?: unknown }).detail, `请求失败（${res.status}）`),
    );
    (error as Error & { status?: number }).status = res.status;
    throw error;
  }
  if (!res.body) throw new Error("浏览器不支持流式响应。");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk
        .split("\n")
        .map((row) => row.trim())
        .find((row) => row.startsWith("data:"));
      if (!line) continue;
      const rawPayload = line.slice(5).trimStart();
      const parsed = parseStreamPayload(rawPayload);
      if (parsed) onPayload(parsed);
    }
  }
}
