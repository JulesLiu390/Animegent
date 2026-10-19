// 默认走同源（Vite 开发服务器把 /api、/files 代理到后端）；需要直连时设置 VITE_API_BASE
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export type AssetType = "image" | "markdown" | "json" | "video";

export interface Asset {
  name: string;          // 文件名
  path: string;
  url: string;
  type?: AssetType;
  title?: string;        // assets.json 里的显示名
  content?: string;
  description?: string;
  source_face?: string;
  thumbnail?: string;
  /** 技能：内置的只读，项目自己的（projects/<项目>/skills/）可以改 */
  readonly?: boolean;
  source?: string;
}

export interface Assets {
  [category: string]: Asset[];
}

export interface AttachedImage {
  path: string;
  url: string;
  name: string;
  previewUrl?: string;  // local blob URL for preview before upload
  fileType?: AssetType;  // default "image"
  content?: string;     // text content for md/json
  description?: string;
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
  source_face?: string;
}

export interface FaceInfo {
  index: number;
  name: string;
  description: string;
  age: number | null;
  gender: string | null;
  crop_path: string;
  crop_url: string;
}

export type ImageVerdict = "accepted" | "rejected" | "revised";
export type CreationMode = "comic" | "storyboard";
/** ask 讨论（只读）/ confirm 生成前确认 / auto 自动执行 */
export type InteractionMode = "ask" | "confirm" | "auto";

/** 选择卡片（选角色 / 选人脸）确认后的结果。 */
export interface SelectionState {
  confirmed: boolean;
  skipped?: boolean;
  items: { path: string; url: string; name: string; label?: string }[];
}

export interface MediaItem {
  path: string;
  url: string;
  tool: string;
}

/** 旧版对话里保存的计划（只读显示）。 */
export interface LegacyPlan {
  status?: string;
  steps: { id: number; label: string; status?: string; needs_confirm?: boolean; error?: string }[];
}

// ========== Session（对话）→ Turn（用户一次输入）→ Step（一段文字 / 一次工具调用） ==========

export type TurnStatus = "running" | "awaiting_approval" | "awaiting_input" | "completed" | "failed" | "cancelled";
export type StepStatus = "running" | "pending_approval" | "awaiting_input" | "completed" | "failed" | "rejected" | "cancelled";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/** 生成类工具的后台任务。 */
export interface Job {
  id: string;
  turn_id: string | null;
  step_id: string | null;
  tool: string;
  status: JobStatus;
  error?: string | null;
  result?: Record<string, unknown> | null;
  media: MediaItem[];
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface StepDisplay {
  media?: MediaItem[];
  options?: CharacterOption[];
  faces?: FaceInfo[];
  plan?: LegacyPlan;
  selection?: SelectionState;
  [key: string]: unknown;
}

export interface Step {
  id: string;
  turn_id: string;
  seq: number;
  kind: "message" | "tool";
  status: StepStatus;
  text?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  display?: StepDisplay | null;
  verdict?: ImageVerdict | null;
  job?: Job | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
}

export interface TurnInput {
  text: string;
  /** 界面上显示的文字（和发给模型的 text 不同时才有） */
  display?: string;
  attachments: AttachedImage[];
}

export interface Turn {
  id: string;
  conversation_id: string;
  seq: number;
  status: TurnStatus;
  input: TurnInput;
  error?: string | null;
  error_kind?: string | null;
  /** 旧版对话转换来的：只读，不能重试 / 编辑 / 删除 */
  legacy: boolean;
  steps: Step[];
  created_at: string;
}

/** 对等待中的 step 的回应：批准 / 拒绝生成，或者卡片里的选择。 */
export type StepResponse = { approve: boolean; note?: string } | { value: unknown };

export interface Project {
  name: string;
  cover?: string | null;
  image_count?: number;
  updated_at?: string;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") throw new Error(detail);
    if (Array.isArray(detail)) throw new Error(detail.map((d: { msg?: string }) => d.msg || "").join("; "));
    throw new Error(`HTTP ${res.status}`);
  }
  return data as T;
}

function sendJson(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

// ========== 项目管理 ==========

export async function fetchProjects(): Promise<Project[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/projects`));
}

export async function createProject(name: string): Promise<{ name: string; created: boolean }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/projects`, sendJson("POST", { name })));
}

export async function renameProject(name: string, newName: string): Promise<{ renamed: boolean; new_name?: string; error?: string }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/projects/${encodeURIComponent(name)}`, sendJson("PUT", { new_name: newName })));
}

export async function deleteProject(name: string): Promise<{ deleted: boolean; error?: string }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/projects/${encodeURIComponent(name)}`, { method: "DELETE" }));
}

// ========== 素材 ==========

export async function fetchAssets(project: string): Promise<Assets> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/assets?project=${encodeURIComponent(project)}`));
}

export async function uploadImage(file: File, project: string): Promise<{ path: string; url: string; name: string }> {
  const formData = new FormData();
  formData.append("file", file);
  return jsonOrThrow(await fetch(`${API_BASE}/api/upload?project=${encodeURIComponent(project)}`, {
    method: "POST",
    body: formData,
  }));
}

export async function updateAsset(filePath: string, content: string): Promise<{ updated: boolean; error?: string }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/assets`, sendJson("PUT", { path: filePath, content })));
}

export async function deleteAsset(filePath: string): Promise<{ deleted: boolean; error?: string }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/assets`, sendJson("DELETE", { path: filePath })));
}

// ========== 对话 (SSE 流式) ==========

export interface TurnStreamCallbacks {
  onConversation?: (conversationId: string) => void;
  /** turn 新建或状态变化（不带 steps） */
  onTurn: (turn: Omit<Turn, "steps"> & { steps?: Step[] }) => void;
  /** step 新建或更新 */
  onStep: (step: Step) => void;
  /** message step 的流式文字 */
  onDelta: (stepId: string, text: string) => void;
  /** 后台生成任务的进度 */
  onJob: (job: Job) => void;
  onDone: () => void;
  onError: (error: string, kind?: string) => void;
}

export interface RunOptions {
  lang: string;
  mode: CreationMode;
  interactionMode: InteractionMode;
}

/** 解析一个 SSE 事件块（event: / data: 行），注释行（心跳）忽略。 */
function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

function dispatch(event: string, data: Record<string, unknown>, cb: TurnStreamCallbacks): boolean {
  switch (event) {
    case "conversation": cb.onConversation?.(data.conversation_id as string); break;
    case "turn": cb.onTurn(data.turn as Turn); break;
    case "step": cb.onStep(data.step as Step); break;
    case "delta": cb.onDelta(data.step_id as string, data.text as string); break;
    case "job": cb.onJob(data.job as Job); break;
    case "done": cb.onDone(); return true;
    case "error": cb.onError(String(data.message || "Unknown error"), data.kind as string | undefined); return true;
  }
  return false;
}

/** 发起一个流式请求并逐个回调 SSE 事件。连接中途断开（没收到 done / error）时会回调 onError。 */
async function streamTurn(path: string, body: unknown, callbacks: TurnStreamCallbacks, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { ...sendJson("POST", body), signal });
  if (!res.ok || !res.body) {
    let message = `HTTP ${res.status}`;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === "string") message = detail;
    } catch { /* not json */ }
    callbacks.onError(message, "network");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const flush = (final: boolean) => {
    buffer = buffer.replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = final ? "" : blocks.pop() ?? "";
    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (!parsed) continue;
      try {
        if (dispatch(parsed.event, JSON.parse(parsed.data), callbacks)) finished = true;
      } catch (err) {
        console.warn("Bad SSE event", parsed.event, err);
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    flush(false);
  }
  buffer += decoder.decode();
  flush(true);
  if (!finished) callbacks.onError("connection-lost", "network");
}

const runBody = (opts: RunOptions) => ({ lang: opts.lang, mode: opts.mode, interaction_mode: opts.interactionMode });

/** 发送一条消息，开始新的一轮。没有 conversationId 时后端新建对话。 */
export function sendMessage(
  opts: RunOptions & {
    conversationId: string | null;
    project: string;
    turnId: string;
    text: string;
    display?: string;
    attachments: AttachedImage[];
    title?: string;
  },
  callbacks: TurnStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return streamTurn("/api/chat", {
    ...runBody(opts),
    conversation_id: opts.conversationId,
    project: opts.project,
    turn_id: opts.turnId,
    text: opts.text,
    display: opts.display,
    // 本地预览用的 blob URL 刷新后就失效了，不发给后端
    attachments: opts.attachments.map((a) => ({ ...a, previewUrl: undefined })),
    title: opts.title,
  }, callbacks, signal);
}

/** 回应等待中的 step（批准 / 拒绝生成、卡片里的选择），这一轮接着执行。 */
export function resumeTurn(turnId: string, responses: Record<string, StepResponse>, opts: RunOptions, callbacks: TurnStreamCallbacks, signal?: AbortSignal): Promise<void> {
  return streamTurn(`/api/turns/${encodeURIComponent(turnId)}/resume`, { ...runBody(opts), responses }, callbacks, signal);
}

/** 从这一轮重新开始（text 不传则原样重试）：这一轮及之后的内容会被替换。 */
export function retryTurn(turnId: string, next: { turnId: string; text?: string }, opts: RunOptions, callbacks: TurnStreamCallbacks, signal?: AbortSignal): Promise<void> {
  return streamTurn(`/api/turns/${encodeURIComponent(turnId)}/retry`, { ...runBody(opts), turn_id: next.turnId, text: next.text }, callbacks, signal);
}

export async function deleteTurn(turnId: string): Promise<{ deleted: string[] }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/turns/${encodeURIComponent(turnId)}`, { method: "DELETE" }));
}

export async function stopChat(conversationId: string): Promise<void> {
  await fetch(`${API_BASE}/api/chat/stop`, sendJson("POST", { conversation_id: conversationId })).catch(() => {});
}

export async function setStepVerdict(stepId: string, verdict: ImageVerdict | null): Promise<Step> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/steps/${encodeURIComponent(stepId)}`, sendJson("PATCH", { verdict })));
}

export async function fetchJobs(conversationId: string, ids: string[]): Promise<Job[]> {
  const query = new URLSearchParams({ ids: ids.join(",") });
  return jsonOrThrow(await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/jobs?${query}`));
}

export async function cancelJob(jobId: string): Promise<Job> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }));
}

// ========== 对话历史 ==========

export interface Conversation {
  id: string;
  project: string;
  lang: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export async function fetchConversations(project: string): Promise<Conversation[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/conversations?project=${encodeURIComponent(project)}`));
}

export async function deleteConversation(conversationId: string): Promise<{ deleted: boolean }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" }));
}

export async function renameConversation(conversationId: string, title: string): Promise<void> {
  await jsonOrThrow(await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}`, sendJson("PUT", { title })));
}

export async function fetchTurns(conversationId: string): Promise<Turn[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/turns`));
}

export function getFileUrl(url: string): string {
  return url.startsWith("http") || url.startsWith("blob:") || url.startsWith("data:") ? url : `${API_BASE}${url}`;
}

// ========== API 设置（服务商与模型） ==========

export type ApiFormat = "openai_compatible" | "gemini_official" | "anthropic_native";
export type ModelRole = "chat" | "vision" | "image" | "video";

export interface ProviderInfo {
  id: string;
  name: string;
  api_format: ApiFormat;
  base_url: string;
  models: string[];
  key_count: number;
  key_previews: string[];  // API Key 只返回脱敏预览
  max_concurrency: number;  // 同一种用途同时最多几个请求
}

export interface ModelAssignment {
  provider_id: string;
  model: string;
  format: string;  // image: gemini | openai；video: unified | openai | gemini；"" = 按服务商推断
  size: string;    // 仅 OpenAI Images
}

export interface AppSettings {
  providers: ProviderInfo[];
  models: Record<ModelRole, ModelAssignment>;
  /** 后端的功能开关（src/web/features.py），休眠的功能不显示入口 */
  features?: { storyboard?: boolean };
}

export interface ProviderInput {
  name: string;
  api_format: ApiFormat;
  base_url: string;
  api_keys: string[] | null;  // null：保留已保存的 Key
  models: string[];
  max_concurrency: number;
}

export interface ProviderProbe {
  provider_id: string | null;  // 编辑已有服务商时可以不重新填 Key
  api_format: ApiFormat;
  base_url: string;
  api_keys: string[] | null;
  model?: string;
}

export async function fetchSettings(): Promise<AppSettings> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings`));
}

export async function createProvider(provider: ProviderInput): Promise<AppSettings> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/providers`, sendJson("POST", provider)));
}

export async function updateProvider(id: string, provider: ProviderInput): Promise<AppSettings> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/providers/${encodeURIComponent(id)}`, sendJson("PUT", provider)));
}

export async function deleteProvider(id: string): Promise<AppSettings> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/providers/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

export async function updateModelSettings(models: Partial<Record<ModelRole, ModelAssignment>>): Promise<AppSettings> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/models`, sendJson("PUT", models)));
}

export async function fetchProviderModels(probe: ProviderProbe): Promise<{ models: string[]; error?: string }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/models/fetch`, sendJson("POST", probe)));
}

export async function testProvider(probe: ProviderProbe): Promise<{ ok: boolean; results: { key: string; ok: boolean; message: string }[] }> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/settings/test`, sendJson("POST", probe)));
}

/** 某个用途是否已配置（vision 未配置时会用 chat）。 */
export function isRoleConfigured(settings: AppSettings, role: ModelRole): boolean {
  const assignment = settings.models[role];
  return Boolean(
    assignment?.model && settings.providers.some((p) => p.id === assignment.provider_id),
  );
}

/** 分镜模式（分镜 → 首帧 → 视频片段 → 成片）是否开放；默认休眠，后端用 ANIMEGENT_STORYBOARD=1 启动时才开放。 */
export function isStoryboardEnabled(settings: AppSettings | null | undefined): boolean {
  return settings?.features?.storyboard === true;
}
