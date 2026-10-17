import { Fragment, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type DragEvent, type Ref } from "react";
import type {
  AppSettings, Asset, AttachedImage, Conversation, CreationMode, InteractionMode, RunOptions, Step, StepResponse, Turn, TurnStreamCallbacks,
} from "../api";
import {
  cancelJob, deleteAsset, deleteConversation, deleteTurn, fetchConversations, fetchJobs, fetchTurns, getFileUrl, isRoleConfigured,
  isStoryboardEnabled, renameConversation, resumeTurn, retryTurn, sendMessage, setStepVerdict, stopChat, uploadImage,
} from "../api";
import { useLang, useLightbox, useNow, useToast } from "../hooks";
import { DRAG_ASSET_TYPE } from "../lib/assets";
import { isNetworkError } from "../lib/errors";
import { formatDuration } from "../lib/format";
import { fileName } from "../lib/media";
import { readStorage, writeStorage } from "../lib/storage";
import { GENERATION_TOOLS, toolLabel, toolStatus } from "../lib/tools";
import {
  appendDelta, applyJob, assetToAttachment, draftTurn, isImageAttachment, isJobActive, isPendingStep, isWaiting, markStopped, newId,
  outputPath, patchStep, patchTurn, stepDomId, stepMedia, upsertStep, upsertTurn,
} from "../lib/turns";
import ApprovalDock from "./ApprovalDock";
import ChatEmptyState from "./ChatEmptyState";
import { AssistantTurn, UserTurn, type StepHandlers } from "./ChatTurns";
import Composer from "./Composer";
import ConfirmDialog from "./ConfirmDialog";
import ConversationHistory from "./ConversationHistory";
import Icon, { Spinner } from "./Icon";
import type { SettingsTab } from "./SettingsModal";

export interface ChatPanelHandle {
  addAttachments: (items: AttachedImage[]) => void;
}

interface Props {
  ref?: Ref<ChatPanelHandle>;
  project: string;
  /** 打开时恢复的对话（上次打开的那个） */
  initialConversationId?: string | null;
  onConversationChange?: (id: string | null) => void;
  onAssetsChanged: () => void;
  /** 在预览面板打开项目里的某个文件；不在素材库里时返回 false */
  onPreviewPath: (path: string) => boolean;
  /** 模型回复里的链接：指向素材时在预览面板打开 */
  onOpenLink: (url: string) => boolean;
  settings: AppSettings | null;
  onSettingsChange: (settings: AppSettings) => void;
  onOpenSettings: (tab?: SettingsTab) => void;
  onBusyChange: (busy: boolean) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const MODE_KEY = "animegent-mode";
const INTERACTION_KEY = "animegent-interaction";

/** 记住的交互模式；旧版的「单步 / 计划」都按「生成前确认」。 */
function savedInteraction(): InteractionMode {
  const saved = readStorage(INTERACTION_KEY);
  return saved === "ask" || saved === "auto" ? saved : "confirm";
}

type PendingAction = { kind: "switch"; run: () => void } | { kind: "delete"; turnId: string };
type StreamSession = { abort: AbortController; turnId: string; stopTimer?: number };

const errorMessage = (err: unknown) => (err instanceof Error ? err.message : String(err));

export default function ChatPanel({
  ref, project, initialConversationId, onConversationChange, onAssetsChanged, onPreviewPath, onOpenLink, settings, onSettingsChange, onOpenSettings, onBusyChange,
  sidebarOpen, onToggleSidebar,
}: Props) {
  const { lang, t } = useLang();
  const toast = useToast();
  const openLightbox = useLightbox();

  const [turns, setTurns] = useState<Turn[]>([]);
  const turnsRef = useRef<Turn[]>([]);
  useEffect(() => { turnsRef.current = turns; }, [turns]);

  const [conversationId, setConversationIdState] = useState<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const onConversationChangeRef = useRef(onConversationChange);
  useEffect(() => { onConversationChangeRef.current = onConversationChange; });
  const setConversationId = useCallback((id: string | null) => {
    conversationIdRef.current = id;
    setConversationIdState(id);
    onConversationChangeRef.current?.(id);
  }, []);
  const [restoring, setRestoring] = useState(Boolean(initialConversationId));
  const initialConversationRef = useRef(initialConversationId);
  const [title, setTitle] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);

  const streamRef = useRef<StreamSession | null>(null);
  const [streamingTurnId, setStreamingTurnId] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const loading = streamingTurnId !== null;

  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<AttachedImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [editingTurnId, setEditingTurnId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);
  const [focusKey, setFocusKey] = useState(0);

  const [mode, setModeState] = useState<CreationMode>(() => (readStorage(MODE_KEY) === "storyboard" ? "storyboard" : "comic"));
  const [interactionMode, setInteractionState] = useState<InteractionMode>(savedInteraction);
  const modeRef = useRef(mode);
  const interactionRef = useRef(interactionMode);
  const setMode = useCallback((value: CreationMode) => {
    modeRef.current = value;
    setModeState(value);
    writeStorage(MODE_KEY, value);
  }, []);
  const setInteractionMode = useCallback((value: InteractionMode) => {
    interactionRef.current = value;
    setInteractionState(value);
    writeStorage(INTERACTION_KEY, value);
  }, []);
  // 分镜模式休眠时一律按条漫模式（浏览器里记住的选择不动，重新开放后恢复）
  const storyboard = isStoryboardEnabled(settings);
  const activeMode: CreationMode = storyboard ? mode : "comic";
  const storyboardRef = useRef(storyboard);
  useEffect(() => { storyboardRef.current = storyboard; }, [storyboard]);
  const runOptions = useCallback((): RunOptions => ({
    lang,
    mode: storyboardRef.current ? modeRef.current : "comic",
    interactionMode: interactionRef.current,
  }), [lang]);

  useEffect(() => { onBusyChange(loading); }, [loading, onBusyChange]);

  // ---------- 对话列表 ----------

  const loadConversations = useCallback(() => {
    fetchConversations(project).then(setConversations).catch(() => {});
  }, [project]);

  // 打开项目时加载对话列表，并恢复上次打开的对话
  useEffect(() => {
    let cancelled = false;
    fetchConversations(project)
      .then((list) => {
        if (cancelled) return;
        setConversations(list);
        const initial = initialConversationRef.current;
        initialConversationRef.current = null;
        const conv = initial ? list.find((c) => c.id === initial) : undefined;
        if (conv) return implRef.current.loadConversation(conv);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; };
  }, [project]);

  /** 按后端的数据刷新当前对话（流异常结束后对齐状态）；后端没收到的那一轮保留本地的出错提示。 */
  const refresh = useCallback(async () => {
    const cid = conversationIdRef.current;
    if (!cid) return;
    try {
      const fresh = await fetchTurns(cid);
      if (conversationIdRef.current !== cid || streamRef.current) return;
      setTurns((prev) => {
        const known = new Set(fresh.map((turn) => turn.id));
        const merged = fresh.reduce((acc, turn) => upsertTurn(acc, turn), prev.filter((turn) => known.has(turn.id)));
        return [...merged, ...prev.filter((turn) => !known.has(turn.id) && turn.status === "failed")];
      });
    } catch { /* 后端连不上时保留界面现状 */ }
  }, []);

  // ---------- 滚动 ----------

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const lastScrollTop = useRef(0);
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    // 只有用户往上滚才取消「跟随到底部」；平滑滚动过程中的中间位置不算
    if (el.scrollTop < lastScrollTop.current - 4 && distance > 80) stickRef.current = false;
    else if (distance < 80) stickRef.current = true;
    lastScrollTop.current = el.scrollTop;
    setShowJump(distance > 320);
  };

  const scrollToBottom = useCallback((smooth = true) => {
    stickRef.current = true;
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    });
  }, []);

  const hasTurns = turns.length > 0;
  // 内容变高（流式输出、图片加载完）时，如果本来就在底部就保持在底部
  useEffect(() => {
    const content = contentRef.current;
    const el = scrollRef.current;
    if (!content || !el) return;
    const observer = new ResizeObserver(() => {
      if (stickRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [hasTurns]);

  // ---------- 流式请求 ----------

  /**
   * 执行一个流式请求，按后端推送的事件更新这一轮。
   * existing：这一轮在后端已经存在（继续执行 / 回应等待中的 step），出错时以后端的状态为准。
   */
  const runStream = useCallback(async (
    turnId: string,
    start: (callbacks: TurnStreamCallbacks, signal: AbortSignal) => Promise<void>,
    { existing = false, title: newTitle }: { existing?: boolean; title?: string } = {},
  ) => {
    const abort = new AbortController();
    const session: StreamSession = { abort, turnId };
    streamRef.current = session;
    setStreamingTurnId(turnId);
    setStopping(false);
    const alive = () => streamRef.current === session;
    let acknowledged = existing;
    let finished = false;

    const finish = (error?: { message: string; kind?: string }) => {
      if (finished) return;
      finished = true;
      if (!alive()) return; // 已经切换到别的对话
      window.clearTimeout(session.stopTimer);
      if (error && !acknowledged) {
        setTurns((prev) => patchTurn(prev, turnId, (turn) => ({ ...turn, status: "failed", error: error.message, error_kind: error.kind ?? "generic" })));
      } else if (error && error.message !== "connection-lost") {
        toast(error.message, "error");
      }
      // 停止或断线时可能没收到最后的状态：先把还在转圈的标成已停止，再按后端刷新
      setTurns((prev) => patchTurn(prev, turnId, (turn) => (turn.status === "running" ? markStopped(turn) : turn)));
      streamRef.current = null;
      setStreamingTurnId(null);
      setStopping(false);
      loadConversations();
      onAssetsChanged();
      if (error && acknowledged) refresh();
    };

    const callbacks: TurnStreamCallbacks = {
      onConversation: (cid) => {
        if (!alive() || conversationIdRef.current === cid) return;
        setConversationId(cid);
        if (newTitle) setTitle((prev) => prev || newTitle.slice(0, 60));
      },
      onTurn: (turn) => {
        if (!alive()) return;
        if (turn.id === turnId) acknowledged = true;
        setTurns((prev) => upsertTurn(prev, turn));
      },
      onStep: (step) => {
        if (!alive()) return;
        setTurns((prev) => upsertStep(prev, step));
        if (step.kind === "tool" && step.status === "completed") onAssetsChanged();
      },
      onDelta: (stepId, text) => {
        if (alive()) setTurns((prev) => appendDelta(prev, stepId, text));
      },
      onJob: (job) => {
        if (!alive()) return;
        setTurns((prev) => applyJob(prev, job));
        if (!isJobActive(job)) onAssetsChanged();
      },
      onDone: () => finish(),
      onError: (message, kind) => finish({ message, kind }),
    };

    try {
      await start(callbacks, abort.signal);
    } catch (err) {
      if (abort.signal.aborted) finish();
      else finish({ message: isNetworkError(err) ? t("app.backendDown") : errorMessage(err), kind: "network" });
    }
    finish();
  }, [loadConversations, onAssetsChanged, refresh, setConversationId, t, toast]);

  const stop = useCallback(() => {
    const session = streamRef.current;
    if (!session) return;
    setStopping(true);
    const cid = conversationIdRef.current;
    if (cid) stopChat(cid);
    // 后端一般很快收尾并推送最后的状态；连接卡住时直接断开（断开也会让后端停止）
    session.stopTimer = window.setTimeout(() => session.abort.abort(), 4000);
  }, []);

  /** 离开当前对话（切换对话 / 新对话 / 切换项目）：停止还在跑的任务。 */
  const leaveCurrent = useCallback(() => {
    const session = streamRef.current;
    if (!session) return;
    streamRef.current = null;
    setStreamingTurnId(null);
    setStopping(false);
    window.clearTimeout(session.stopTimer);
    const cid = conversationIdRef.current;
    if (cid) stopChat(cid);
    session.abort.abort();
  }, []);

  useEffect(() => () => leaveCurrent(), [leaveCurrent]);

  // ---------- 发送 ----------

  const send = useCallback(async ({ text, display, attachments: atts = [] }: { text: string; display?: string; attachments?: AttachedImage[] }) => {
    if (streamRef.current) return;
    const turnId = newId();
    const last = turnsRef.current[turnsRef.current.length - 1];
    setTurns((prev) => [...prev, draftTurn(turnId, conversationIdRef.current, (last?.seq ?? -1) + 1, { text, display, attachments: atts })]);
    scrollToBottom();
    const shown = (display ?? text).trim();
    await runStream(turnId, (callbacks, signal) => sendMessage({
      ...runOptions(),
      conversationId: conversationIdRef.current,
      project,
      turnId,
      text,
      display,
      attachments: atts,
      title: shown || undefined,
    }, callbacks, signal), { title: shown || undefined });
  }, [project, runOptions, runStream, scrollToBottom]);

  const handleSend = () => {
    const text = input.trim();
    if ((!text && attachments.length === 0) || streamRef.current || uploading) return;
    const atts = attachments;
    setInput("");
    setAttachments([]);
    send({ text, attachments: atts });
  };

  /** 回应等待中的 step（批准 / 拒绝生成、卡片里的选择）：这一轮接着执行。 */
  const respond = useCallback(async (turnId: string, responses: Record<string, StepResponse>) => {
    if (streamRef.current) return;
    setTurns((prev) => patchTurn(prev, turnId, (turn) => ({ ...turn, status: "running" })));
    await runStream(turnId, (callbacks, signal) => resumeTurn(turnId, responses, runOptions(), callbacks, signal), { existing: true });
  }, [runOptions, runStream]);

  const respondAll = useCallback((turn: Turn, response: StepResponse) => {
    const pending = turn.steps.filter((s) => s.status === "pending_approval");
    respond(turn.id, Object.fromEntries(pending.map((s) => [s.id, response])));
  }, [respond]);

  // ---------- 附件 ----------

  const addAttachments = useCallback((items: AttachedImage[]) => {
    setAttachments((prev) => {
      const existing = new Set(prev.map((a) => a.path));
      return [...prev, ...items.filter((a) => !existing.has(a.path))];
    });
    setFocusKey((k) => k + 1);
  }, []);

  useImperativeHandle(ref, () => ({ addAttachments }), [addAttachments]);

  const uploadFiles = useCallback(async (files: File[]) => {
    const images = files.filter((f) => f.type.startsWith("image/"));
    if (images.length === 0) return;
    setUploading(true);
    try {
      for (const file of images) {
        const previewUrl = URL.createObjectURL(file);
        try {
          const res = await uploadImage(file, project);
          setAttachments((prev) => [...prev, { path: res.path, url: res.url, name: res.name, previewUrl }]);
        } catch (err) {
          URL.revokeObjectURL(previewUrl);
          toast(t("chat.uploadFailed", { error: errorMessage(err) }), "error");
        }
      }
      onAssetsChanged();
    } finally {
      setUploading(false);
    }
  }, [onAssetsChanged, project, t, toast]);

  const removeAttachment = (index: number) => {
    setAttachments((prev) => {
      const att = prev[index];
      if (att?.previewUrl) URL.revokeObjectURL(att.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  };

  const openAttachment = useCallback((att: AttachedImage, all?: AttachedImage[]) => {
    if (onPreviewPath(att.path)) return;
    const images = (all || [att]).filter(isImageAttachment);
    const index = Math.max(0, images.indexOf(att));
    openLightbox(images.map((a) => ({ url: a.previewUrl || getFileUrl(a.url), name: a.name })), index);
  }, [onPreviewPath, openLightbox]);

  const handleDragEnter = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer.types).some((type) => type === "Files" || type === DRAG_ASSET_TYPE)) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragOver(true);
  };
  const handleDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragOver(false);
  };
  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    const raw = e.dataTransfer.getData(DRAG_ASSET_TYPE);
    if (raw) {
      try {
        addAttachments([assetToAttachment(JSON.parse(raw) as Asset)]);
      } catch { /* ignore */ }
      return;
    }
    uploadFiles(Array.from(e.dataTransfer.files));
  };

  // ---------- 重试 / 编辑 / 删除 ----------

  /** 从这一轮重新开始：text 不传则原样重试，传了就是编辑后重新发送。 */
  const retry = useCallback(async (turnId: string, text?: string) => {
    if (streamRef.current) return;
    const idx = turnsRef.current.findIndex((turn) => turn.id === turnId);
    const old = turnsRef.current[idx];
    if (!old || old.legacy) return;
    const newTurnId = newId();
    const nextInput = text === undefined ? old.input : { ...old.input, text, display: undefined };
    setEditingTurnId(null);
    setTurns((prev) => [...prev.slice(0, idx), draftTurn(newTurnId, old.conversation_id, old.seq, nextInput)]);
    scrollToBottom();
    await runStream(newTurnId, (callbacks, signal) => retryTurn(turnId, { turnId: newTurnId, text }, runOptions(), callbacks, signal));
  }, [runOptions, runStream, scrollToBottom]);

  const removeTurn = useCallback(async (turnId: string) => {
    try {
      await deleteTurn(turnId);
      setTurns((prev) => {
        const idx = prev.findIndex((turn) => turn.id === turnId);
        return idx < 0 ? prev : prev.slice(0, idx);
      });
      loadConversations();
    } catch (err) {
      toast(t("chat.rewindFailed", { error: errorMessage(err) }), "error");
    }
  }, [loadConversations, t, toast]);

  const requestDelete = useCallback((turnId: string) => setPendingAction({ kind: "delete", turnId }), []);
  const startEdit = useCallback((turnId: string) => setEditingTurnId(turnId), []);
  const cancelEdit = useCallback(() => setEditingTurnId(null), []);

  // ---------- 生成结果：满意 / 删除 / 修改，后台任务取消 ----------

  const setVerdict = useCallback((step: Step, verdict: "accepted" | "rejected" | "revised") => {
    setTurns((prev) => patchStep(prev, step.id, (s) => ({ ...s, verdict })));
    setStepVerdict(step.id, verdict).catch(() => {});
  }, []);

  const acceptStep = useCallback((step: Step) => setVerdict(step, "accepted"), [setVerdict]);

  const discardStep = useCallback(async (step: Step) => {
    setVerdict(step, "rejected");
    let failed = 0;
    for (const item of stepMedia(step)) {
      try {
        await deleteAsset(item.path);
      } catch {
        failed += 1;
      }
    }
    toast(failed ? t("common.error") : t("sidebar.deleted"), failed ? "error" : "success");
    onAssetsChanged();
  }, [onAssetsChanged, setVerdict, t, toast]);

  const reviseStep = useCallback((step: Step, prompt: string) => {
    setVerdict(step, "revised");
    const output = outputPath(step);
    const turn = turnsRef.current.find((item) => item.id === step.turn_id);
    const kept = (turn?.steps || [])
      .filter((other) => other.id !== step.id && GENERATION_TOOLS.has(other.tool || "") && other.verdict !== "rejected")
      .map(outputPath)
      .filter(Boolean);
    let text = output ? `请修改这张图片 (${output})：${prompt}` : `请重新生成：${prompt}`;
    text += "\n注意：只修改这一个素材，不要重新生成其他素材。";
    if (kept.length) text += `以下素材用户已接受，不要修改：${kept.join("、")}`;
    send({ text, display: t("chat.reviseRequest", { name: output ? fileName(output) : toolLabel(step.tool || "", t), prompt }) });
  }, [send, setVerdict, t]);

  const cancelStepJob = useCallback(async (step: Step) => {
    if (!step.job) return;
    try {
      const job = await cancelJob(step.job.id);
      setTurns((prev) => applyJob(prev, job));
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }, [toast]);

  // ---------- 后台任务进度：对话流结束后轮询 ----------

  const activeJobIds = useMemo(
    () => turns.flatMap((turn) => turn.steps).filter((s) => isJobActive(s.job)).map((s) => s.job!.id),
    [turns],
  );
  const activeJobKey = activeJobIds.join(",");
  const runningElsewhere = !loading && turns.some((turn) => turn.status === "running");
  useEffect(() => {
    const cid = conversationId;
    if (loading || !cid || (!activeJobKey && !runningElsewhere)) return;
    const timer = window.setInterval(async () => {
      try {
        if (activeJobKey) {
          const jobs = await fetchJobs(cid, activeJobKey.split(","));
          if (conversationIdRef.current !== cid || streamRef.current) return;
          setTurns((prev) => jobs.reduce(applyJob, prev));
          if (jobs.some((job) => !isJobActive(job))) onAssetsChanged();
        }
        if (runningElsewhere) refresh(); // 例如在另一个标签页里执行中
      } catch { /* 后端暂时连不上：下次再试 */ }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJobKey, conversationId, loading, onAssetsChanged, refresh, runningElsewhere]);

  // ---------- 对话切换 ----------

  const resetChat = useCallback(() => {
    turnsRef.current = [];
    setTurns([]);
    setConversationId(null);
    setTitle("");
    setEditingTurnId(null);
  }, [setConversationId]);

  const guard = (action: () => void) => {
    if (streamRef.current) setPendingAction({ kind: "switch", run: action });
    else action();
  };

  const loadConversation = async (conv: Conversation) => {
    try {
      const list = await fetchTurns(conv.id);
      turnsRef.current = list;
      setTurns(list);
      setConversationId(conv.id);
      setTitle(conv.title || "");
      setEditingTurnId(null);
      scrollToBottom(false);
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  const restoreConversation = (conv: Conversation) => guard(() => {
    leaveCurrent();
    loadConversation(conv);
  });

  const newChat = () => guard(() => {
    leaveCurrent();
    resetChat();
    setFocusKey((k) => k + 1);
  });

  const removeConversation = async (id: string) => {
    const run = async () => {
      if (id === conversationIdRef.current) {
        leaveCurrent();
        resetChat();
      }
      try {
        await deleteConversation(id);
      } catch (err) {
        toast(errorMessage(err), "error");
      }
      loadConversations();
    };
    if (id === conversationIdRef.current) guard(run);
    else run();
  };

  const renameConv = async (id: string, value: string) => {
    try {
      await renameConversation(id, value);
      if (id === conversationIdRef.current) setTitle(value);
      loadConversations();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  const confirmPending = async () => {
    const action = pendingAction;
    setPendingAction(null);
    if (!action) return;
    if (action.kind === "switch") action.run();
    else await removeTurn(action.turnId);
  };

  // 给消息组件的回调保持引用不变，没变的消息就不会重新渲染
  const impl = {
    respond, acceptStep, discardStep, reviseStep, cancelStepJob, retry, requestDelete, startEdit, cancelEdit, openAttachment, loadConversation,
  };
  const implRef = useRef(impl);
  useEffect(() => { implRef.current = impl; });
  const handlers = useMemo<StepHandlers>(() => ({
    onRespond: (turnId, stepId, response) => implRef.current.respond(turnId, { [stepId]: response }),
    onAccept: (step) => implRef.current.acceptStep(step),
    onDiscard: (step) => implRef.current.discardStep(step),
    onRevise: (step, prompt) => implRef.current.reviseStep(step, prompt),
    onCancelJob: (step) => implRef.current.cancelStepJob(step),
  }), []);
  const turnCallbacks = useMemo(() => ({
    retry: (turnId: string) => implRef.current.retry(turnId),
    remove: (turnId: string) => implRef.current.requestDelete(turnId),
    editStart: (turnId: string) => implRef.current.startEdit(turnId),
    editCancel: () => implRef.current.cancelEdit(),
    editSubmit: (turnId: string, text: string) => implRef.current.retry(turnId, text),
    openAttachment: (att: AttachedImage, all: AttachedImage[]) => implRef.current.openAttachment(att, all),
    openSettings: () => onOpenSettings("models"),
  }), [onOpenSettings]);

  // ---------- 渲染 ----------

  const chatConfigured = !settings || isRoleConfigured(settings, "chat");
  const lastTurn = turns[turns.length - 1];
  const waitingTurn = !loading && lastTurn && isWaiting(lastTurn) && !lastTurn.legacy ? lastTurn : null;

  const streamingTurn = streamingTurnId ? turns.find((turn) => turn.id === streamingTurnId) : undefined;
  const runningTools = (streamingTurn?.steps || []).filter((s) => s.kind === "tool" && s.status === "running");
  const now = useNow(loading || activeJobIds.length > 0);
  const startedAt = runningTools[0]?.started_at ? Date.parse(runningTools[0].started_at) : now;
  let status = null;
  if (loading) {
    status = (
      <span className="flex items-center gap-1.5 text-brand-500 dark:text-brand-400">
        <Spinner className="h-3 w-3" />
        {stopping
          ? t("chat.stopping")
          : runningTools.length > 0
            ? `${toolStatus(runningTools[0].tool || "", t)}${runningTools.length > 1 ? ` ×${runningTools.length}` : ""} · ${formatDuration(Math.max(0, now - startedAt))}`
            : `${t("chat.thinking")}…`}
      </span>
    );
  } else if (activeJobIds.length > 0) {
    status = (
      <span className="flex items-center gap-1.5 text-brand-500 dark:text-brand-400">
        <Spinner className="h-3 w-3" />
        {t("chat.backgroundJobs", { count: activeJobIds.length })}
      </span>
    );
  }

  const composer = (
    <Composer
      value={input}
      onChange={setInput}
      attachments={attachments}
      uploading={uploading}
      onFiles={uploadFiles}
      onRemoveAttachment={removeAttachment}
      onAttachmentClick={(att) => openAttachment(att, attachments)}
      onSend={handleSend}
      onStop={stop}
      loading={loading}
      blocked={!chatConfigured}
      mode={activeMode}
      onModeChange={setMode}
      interactionMode={interactionMode}
      onInteractionModeChange={setInteractionMode}
      settings={settings}
      onSettingsChange={onSettingsChange}
      onOpenSettings={onOpenSettings}
      dragOver={dragOver}
      status={status}
      focusKey={focusKey}
    />
  );

  const configBanner = !chatConfigured && settings && (
    <div className="mb-2 flex items-center gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
      <Icon name="alert-triangle" className="h-4 w-4 text-amber-500" />
      <span className="min-w-0 flex-1">{t("settings.chatMissing")}</span>
      <button onClick={() => onOpenSettings(settings.providers.length === 0 ? "providers" : "models")} className="btn bg-white text-amber-700 shadow-sm hover:bg-amber-100 dark:bg-amber-500/20 dark:text-amber-100 dark:hover:bg-amber-500/30">
        {t("settings.goConfigure")}
      </button>
    </div>
  );

  const jumpToPending = () => {
    const step = waitingTurn?.steps.find(isPendingStep);
    if (step) document.getElementById(stepDomId(step.id))?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div
      className="relative flex h-full min-w-0 flex-col"
      onDragEnter={handleDragEnter}
      onDragOver={(e) => { if (dragOver) e.preventDefault(); }}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200/80 px-3 dark:border-zinc-800/80">
        <button
          onClick={onToggleSidebar}
          className={`icon-btn ${sidebarOpen ? "" : "text-brand-500 dark:text-brand-400"}`}
          title={t("chat.toggleSidebar")}
        >
          <Icon name="panel-left" className="h-[18px] w-[18px]" />
        </button>
        <div className="flex min-w-0 flex-1 justify-center">
          <ConversationHistory
            conversations={conversations}
            currentId={conversationId}
            currentTitle={title}
            onSelect={restoreConversation}
            onNew={newChat}
            onDelete={removeConversation}
            onRename={renameConv}
            onRefresh={loadConversations}
          />
        </div>
        <button onClick={newChat} className="icon-btn" title={t("chat.newChat")}>
          <Icon name="new-chat" className="h-[18px] w-[18px]" />
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onWheel={(e) => { if (e.deltaY < 0) stickRef.current = false; }}
        className="relative min-h-0 flex-1 overflow-y-auto"
      >
        {hasTurns ? (
          <div ref={contentRef} className="mx-auto w-full max-w-3xl space-y-6 px-4 pb-4 pt-6 sm:px-6">
            {turns.map((turn) => (
              <Fragment key={turn.id}>
                <UserTurn
                  turn={turn}
                  editing={editingTurnId === turn.id}
                  busy={loading}
                  onEditStart={turnCallbacks.editStart}
                  onEditSubmit={turnCallbacks.editSubmit}
                  onEditCancel={turnCallbacks.editCancel}
                  onRetry={turnCallbacks.retry}
                  onDelete={turnCallbacks.remove}
                  onAttachmentClick={turnCallbacks.openAttachment}
                />
                <AssistantTurn
                  turn={turn}
                  streaming={turn.id === streamingTurnId}
                  busy={loading}
                  project={project}
                  handlers={handlers}
                  onOpenLink={onOpenLink}
                  onOpenSettings={turnCallbacks.openSettings}
                  onRetry={turnCallbacks.retry}
                  onDelete={turnCallbacks.remove}
                />
              </Fragment>
            ))}
          </div>
        ) : restoring ? (
          <div className="flex h-full items-center justify-center text-brand-500"><Spinner className="h-6 w-6" /></div>
        ) : (
          <div className="flex min-h-full flex-col items-center justify-center px-4 py-10 sm:px-6">
            <div className="w-full max-w-2xl">
              <ChatEmptyState mode={activeMode} onSuggestion={(text) => { setInput(text); setFocusKey((k) => k + 1); }} />
              <div className="mt-8">
                {configBanner}
                {composer}
              </div>
            </div>
          </div>
        )}
      </div>

      {hasTurns && (
        <div className="relative shrink-0 px-4 pb-3 sm:px-6">
          <div className="pointer-events-none absolute inset-x-0 -top-6 h-6 bg-gradient-to-t from-zinc-50 to-transparent dark:from-zinc-950" />
          {showJump && (
            <button
              onClick={() => scrollToBottom()}
              title={t("chat.scrollToBottom")}
              className="absolute -top-11 left-1/2 z-10 flex h-8 w-8 -translate-x-1/2 animate-fade-in items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-600 shadow-soft transition-colors hover:text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:text-white"
            >
              <Icon name="arrow-down" className="h-4 w-4" />
            </button>
          )}
          <div className="mx-auto w-full max-w-3xl">
            {configBanner}
            {waitingTurn && (
              <ApprovalDock
                turn={waitingTurn}
                busy={loading}
                onApproveAll={() => respondAll(waitingTurn, { approve: true })}
                onRejectAll={(note) => respondAll(waitingTurn, { approve: false, note })}
                onJump={jumpToPending}
              />
            )}
            {composer}
          </div>
        </div>
      )}

      {dragOver && (
        <div className="pointer-events-none absolute inset-2 z-20 flex animate-fade-in items-center justify-center rounded-2xl border-2 border-dashed border-brand-400 bg-brand-50/70 backdrop-blur-[1px] dark:bg-brand-500/10">
          <div className="flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-medium text-brand-600 shadow-soft dark:bg-zinc-900 dark:text-brand-300">
            <Icon name="image-plus" className="h-5 w-5" />
            {t("chat.dropHint")}
          </div>
        </div>
      )}

      {pendingAction?.kind === "switch" && (
        <ConfirmDialog
          title={t("app.busyTitle")}
          message={t("app.busySwitch")}
          confirmLabel={t("app.stopAndSwitch")}
          onConfirm={confirmPending}
          onCancel={() => setPendingAction(null)}
        />
      )}
      {pendingAction?.kind === "delete" && (
        <ConfirmDialog
          title={t("chat.deleteTitle")}
          message={t("chat.deleteConfirm")}
          confirmLabel={t("common.delete")}
          onConfirm={confirmPending}
          onCancel={() => setPendingAction(null)}
        />
      )}
    </div>
  );
}
