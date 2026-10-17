import type { Asset, AttachedImage, Job, MediaItem, SelectionState, Step, Turn, TurnInput } from "../api";

/** 新一轮的 id：前端生成，后端沿用，这样用户消息可以先显示出来。 */
export function newId(): string {
  // 局域网 http 访问时不是安全上下文，没有 crypto.randomUUID
  const raw = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  return raw.replace(/-/g, "");
}

export const isImageAttachment = (a: AttachedImage) => !a.fileType || a.fileType === "image";

export function assetToAttachment(asset: Asset): AttachedImage {
  return {
    path: asset.path,
    url: asset.url,
    name: asset.title || asset.name,
    fileType: asset.type || "image",
    content: asset.content,
    description: asset.description,
  };
}

/** 工具卡片的 DOM id（滚动到等待处理的卡片）。 */
export const stepDomId = (stepId: string) => `step-${stepId}`;

export const isWaiting = (turn: Turn) => turn.status === "awaiting_approval" || turn.status === "awaiting_input";
export const isPendingStep = (step: Step) => step.status === "pending_approval" || step.status === "awaiting_input";
export const isJobActive = (job?: Job | null) => Boolean(job && (job.status === "queued" || job.status === "running"));

export function draftTurn(id: string, conversationId: string | null, seq: number, input: TurnInput): Turn {
  return { id, conversation_id: conversationId ?? "", seq, status: "running", input, legacy: false, steps: [], created_at: new Date().toISOString() };
}

/** 这一轮里模型说的话（复制用）。 */
export function turnText(turn: Turn): string {
  return turn.steps.filter((s) => s.kind === "message" && s.text?.trim()).map((s) => s.text).join("\n\n");
}

/** 工具产出的图片 / 视频：后台任务的结果，或者同步工具的结果。 */
export function stepMedia(step: Step): MediaItem[] {
  return step.job?.media?.length ? step.job.media : step.display?.media ?? [];
}

/** 选择卡片确认后的结果：由工具结果（用户的选择）和卡片选项拼出来；旧版对话直接保存了 selection。 */
export function selectionOf(step: Step): SelectionState | undefined {
  if (step.display?.selection) return step.display.selection;
  if (step.status !== "completed" || !step.result) return undefined;
  const result = step.result as { selected?: { path: string; name?: string; label?: string }[]; skipped?: boolean };
  if (result.skipped) return { confirmed: true, skipped: true, items: [] };
  if (!Array.isArray(result.selected)) return undefined;
  const urls = new Map<string, string>();
  for (const o of step.display?.options ?? []) urls.set(o.path, o.url);
  for (const f of step.display?.faces ?? []) urls.set(f.crop_path, f.crop_url);
  return {
    confirmed: true,
    items: result.selected.map((s) => ({ path: s.path, url: urls.get(s.path) || "", name: s.name || "", label: s.label })),
  };
}

// ---- 应用后端推送的事件（返回新数组；没变的 turn 保持同一个对象，避免重新渲染） ----

/** 后端的 input 里没有本地预览图（blob URL）：同一个附件保留本地预览，图片不会闪一下。 */
function keepPreviews(current: TurnInput, next: TurnInput): TurnInput {
  const previews = new Map(current.attachments.filter((a) => a.previewUrl).map((a) => [a.path, a.previewUrl]));
  if (previews.size === 0) return next;
  return { ...next, attachments: next.attachments.map((a) => (previews.has(a.path) ? { ...a, previewUrl: previews.get(a.path) } : a)) };
}

export function upsertTurn(turns: Turn[], turn: Omit<Turn, "steps"> & { steps?: Step[] }): Turn[] {
  const i = turns.findIndex((t) => t.id === turn.id);
  if (i < 0) return [...turns, { ...turn, steps: turn.steps ?? [] }];
  const current = turns[i];
  const next: Turn = { ...current, ...turn, steps: turn.steps ?? current.steps, input: keepPreviews(current.input, turn.input ?? current.input) };
  return turns.map((t, idx) => (idx === i ? next : t));
}

export function patchTurn(turns: Turn[], turnId: string, fn: (turn: Turn) => Turn): Turn[] {
  return turns.map((t) => (t.id === turnId ? fn(t) : t));
}

export function upsertStep(turns: Turn[], step: Step): Turn[] {
  return turns.map((turn) => {
    if (turn.id !== step.turn_id) return turn;
    const i = turn.steps.findIndex((s) => s.id === step.id);
    if (i < 0) return { ...turn, steps: [...turn.steps, step].sort((a, b) => a.seq - b.seq) };
    return { ...turn, steps: turn.steps.map((s, idx) => (idx === i ? step : s)) };
  });
}

export function appendDelta(turns: Turn[], stepId: string, text: string): Turn[] {
  return turns.map((turn) => {
    if (!turn.steps.some((s) => s.id === stepId)) return turn;
    return { ...turn, steps: turn.steps.map((s) => (s.id === stepId ? { ...s, text: (s.text || "") + text } : s)) };
  });
}

export function applyJob(turns: Turn[], job: Job): Turn[] {
  return turns.map((turn) => {
    if (job.turn_id && turn.id !== job.turn_id) return turn;
    if (!turn.steps.some((s) => s.job?.id === job.id || s.id === job.step_id)) return turn;
    return { ...turn, steps: turn.steps.map((s) => (s.job?.id === job.id || s.id === job.step_id ? { ...s, job } : s)) };
  });
}

/** 停止时还没收到后端最后的状态：先把界面上还在转圈的标成已停止。 */
export function markStopped(turn: Turn): Turn {
  return {
    ...turn,
    status: turn.status === "running" ? "cancelled" : turn.status,
    steps: turn.steps.map((s) => (s.status === "running" && s.kind === "tool" ? { ...s, status: "cancelled" as const } : s)),
  };
}

export function patchStep(turns: Turn[], stepId: string, fn: (step: Step) => Step): Turn[] {
  return turns.map((turn) => (
    turn.steps.some((s) => s.id === stepId) ? { ...turn, steps: turn.steps.map((s) => (s.id === stepId ? fn(s) : s)) } : turn
  ));
}

/** 生成结果的文件路径（后台任务的结果，或者同步工具的结果）。 */
export function outputPath(step: Step): string | undefined {
  const value = step.job?.result?.output_path ?? step.result?.output_path;
  return typeof value === "string" ? value : undefined;
}
