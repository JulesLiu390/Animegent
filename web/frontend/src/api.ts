const API_BASE = "http://localhost:8000";

export interface Asset {
  name: string;
  path: string;
  url: string;
  type?: "image" | "markdown" | "json";
  content?: string;
}

export interface Assets {
  [category: string]: Asset[];
}

export interface AttachedImage {
  path: string;
  url: string;
  name: string;
  previewUrl?: string;  // local blob URL for preview before upload
}

export interface CharacterOption {
  path: string;
  url: string;
  filename: string;
  category: "characters" | "faces";
  name: string;
  description: string;
  selected: boolean;
  label: string;
}

export interface ToolCallInfo {
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  duration_ms?: number;
  pending?: boolean;
  images?: { path: string; url: string; tool: string }[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  turnId: string;
  type?: "image" | "text";  // user messages only
  content: string;
  images?: { path: string; url: string; tool: string }[];
  attachedImages?: AttachedImage[];
  toolCalls?: ToolCallInfo[];
}

export interface Project {
  name: string;
}

// ========== 项目管理 ==========

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${API_BASE}/api/projects`);
  return res.json();
}

export async function createProject(name: string): Promise<{ name: string; created: boolean }> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return res.json();
}

export async function deleteProject(name: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  return res.json();
}

// ========== 素材 ==========

export async function fetchAssets(project: string): Promise<Assets> {
  const res = await fetch(`${API_BASE}/api/assets?project=${encodeURIComponent(project)}`);
  return res.json();
}

export async function uploadImage(file: File, project: string): Promise<{ path: string; url: string; name: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload?project=${encodeURIComponent(project)}`, {
    method: "POST",
    body: formData,
  });
  return res.json();
}

export async function deleteAsset(filePath: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_BASE}/api/assets`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: filePath }),
  });
  return res.json();
}

// ========== 对话 (SSE 流式) ==========

export interface StreamCallbacks {
  onConversationId: (cid: string) => void;
  onTextDelta: (delta: string) => void;
  onToolStart: (index: number, tool: string, args: Record<string, unknown>) => void;
  onToolEnd: (index: number, tool: string, result: Record<string, unknown>, durationMs: number, images?: { path: string; url: string; tool: string }[]) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

export async function streamMessage(
  message: string,
  conversationId: string | null,
  callbacks: StreamCallbacks,
  imagePaths?: string[],
  project?: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      image_paths: imagePaths,
      project,
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    callbacks.onError(`HTTP ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const lines = buffer.split("\n");
    buffer = lines.pop() || ""; // keep incomplete line

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7);
      } else if (line.startsWith("data: ")) {
        const dataStr = line.slice(6);
        try {
          const data = JSON.parse(dataStr);
          switch (currentEvent) {
            case "conversation_id":
              callbacks.onConversationId(data.conversation_id);
              break;
            case "text_delta":
              callbacks.onTextDelta(data.delta);
              break;
            case "tool_start":
              callbacks.onToolStart(data.index, data.tool, data.args);
              break;
            case "tool_end":
              callbacks.onToolEnd(data.index, data.tool, data.result, data.duration_ms, data.images);
              break;
            case "done":
              callbacks.onDone();
              break;
            case "error":
              callbacks.onError(data.message || "Unknown error");
              break;
          }
        } catch {
          // ignore malformed JSON
        }
        currentEvent = "";
      }
    }
  }
}

export function getFileUrl(url: string): string {
  return `${API_BASE}${url}`;
}
