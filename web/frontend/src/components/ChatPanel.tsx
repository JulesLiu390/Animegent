import { useState, useRef, useEffect, useCallback } from "react";
import type { AttachedImage, CharacterOption, ChatMessage, Conversation, ImageVerdict, PlanStep, ToolCallInfo } from "../api";
import { deleteAsset, deleteConversation, fetchConversations, fetchUIMessages, getFileUrl, saveUIMessages, streamMessage, uploadImage } from "../api";
import ToolCallCard from "./ToolCallCard";
import MessageActions from "./MessageActions";
import CharacterSelectCard from "./CharacterSelectCard";
import FaceSelectCard from "./FaceSelectCard";
import TaskPlanCard from "./TaskPlanCard";
import ConversationHistory from "./ConversationHistory";
import ModeSelector from "./ModeSelector";
import InteractionModeSelector from "./InteractionModeSelector";
import type { InteractionMode } from "./InteractionModeSelector";
import type { FaceInfo } from "./FaceSelectCard";
import { useLang } from "../LanguageContext";
import MarkdownText from "./MarkdownText";

interface Props {
  project: string;
  onNewImages?: () => void;
  pendingAssets?: AttachedImage[];
  onClearPendingAssets?: () => void;
  onPendingAssetClick?: (path: string) => void;
}

let turnCounter = 0;
function newTurnId(): string {
  return `turn-${++turnCounter}-${Date.now()}`;
}

export default function ChatPanel({ project, onNewImages, pendingAssets, onClearPendingAssets, onPendingAssetClick }: Props) {
  const { lang, t } = useLang();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [editingTurnId, setEditingTurnId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Plan tracking — state driven by backend SSE events
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [planPaused, setPlanPaused] = useState(false);
  const [planTurnId, setPlanTurnId] = useState<string | null>(null);
  // Conversation history
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationTitle, setConversationTitle] = useState("");
  const [mode, setMode] = useState<"comic" | "storyboard">("comic");
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("ask");
  const [videoMode, setVideoMode] = useState<"grok" | "veo">("grok");
  const conversationIdRef = useRef<string | null>(null);
  useEffect(() => { conversationIdRef.current = conversationId; }, [conversationId]);

  const loadConversations = useCallback(() => {
    fetchConversations(project).then(setConversations).catch(() => {});
  }, [project]);

  // Reset chat when project changes
  useEffect(() => {
    setMessages([]);
    setConversationId(null);
    setConversationTitle("");
    setInput("");
    setAttachedImages([]);
    setEditingTurnId(null);
    setPlanSteps([]);
    setPlanPaused(false);
    setPlanTurnId(null);
    loadConversations();
  }, [project, loadConversations]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Receive assets from sidebar
  useEffect(() => {
    if (pendingAssets && pendingAssets.length > 0) {
      setAttachedImages((prev) => {
        const existing = new Set(prev.map((i) => i.path));
        const newOnes = pendingAssets.filter((a) => !existing.has(a.path));
        return [...prev, ...newOnes];
      });
      onClearPendingAssets?.();
    }
  }, [pendingAssets, onClearPendingAssets]);

  const addImageFiles = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      for (const file of files) {
        const previewUrl = URL.createObjectURL(file);
        const result = await uploadImage(file, project);
        setAttachedImages((prev) => [
          ...prev,
          { path: result.path, url: result.url, name: result.name, previewUrl },
        ]);
      }
      onNewImages?.();
    } catch (err) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    await addImageFiles(Array.from(files));
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    const imageFiles: File[] = [];
    for (const item of Array.from(items)) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault();
      await addImageFiles(imageFiles);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.type.startsWith("image/")
    );
    if (files.length > 0) {
      await addImageFiles(files);
    }
  };

  const [dragOver, setDragOver] = useState(false);

  const removeAttached = (index: number) => {
    setAttachedImages((prev) => {
      const img = prev[index];
      if (img.previewUrl) URL.revokeObjectURL(img.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  };

  // Helper to update the last assistant message
  const updateLastAssistant = useCallback((updater: (msg: ChatMessage) => ChatMessage) => {
    setMessages((prev) => {
      const copy = [...prev];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].role === "assistant") {
          copy[i] = updater(copy[i]);
          return copy;
        }
      }
      return prev;
    });
  }, []);

  // Build a context summary from prior messages (for retry/edit with fresh Agent)
  const buildContext = useCallback((priorMessages: ChatMessage[]): string => {
    if (priorMessages.length === 0) return "";
    const lines: string[] = [];
    let lastTurnId = "";
    for (const msg of priorMessages) {
      if (msg.turnId === lastTurnId) continue; // one line per turn
      lastTurnId = msg.turnId;
      if (msg.role === "user") {
        const turnMsgs = priorMessages.filter((m) => m.turnId === msg.turnId);
        const text = turnMsgs.map((m) => m.content).filter(Boolean).join(" ");
        const imgs = turnMsgs.flatMap((m) => m.attachedImages || []);
        const imgNote = imgs.length > 0 ? `[${imgs.length}张图片] ` : "";
        if (text || imgNote) lines.push(`用户: ${imgNote}${text}`);
      } else {
        const turnMsgs = priorMessages.filter((m) => m.turnId === msg.turnId);
        const text = turnMsgs.map((m) => m.content).filter(Boolean).join(" ");
        const tools = turnMsgs.flatMap((m) => m.toolCalls || []);
        const toolNotes = tools.map((tc) => {
          const status = tc.result?.error ? "失败" : "完成";
          return `[${tc.tool} ${status}]`;
        });
        const combined = [...toolNotes, text].filter(Boolean).join(" ");
        if (combined) lines.push(`助手: ${combined}`);
      }
    }
    if (lines.length === 0) return "";
    return `[以下是之前的对话记录，请基于此上下文继续]\n${lines.join("\n")}\n[对话记录结束]\n\n`;
  }, []);

  // Common SSE callbacks shared by doSend, plan actions, etc.
  const makeCallbacks = useCallback((_extraOpts?: {
    planAction?: string;
  }) => ({
    onConversationId: (cid: string) => {
      setConversationId(cid);
      // Set title from first user message if this is a new conversation
      if (!conversationIdRef.current) {
        setMessages((prev) => {
          const firstUserMsg = prev.find(m => m.role === "user" && m.content);
          if (firstUserMsg) setConversationTitle(firstUserMsg.content.slice(0, 50));
          return prev;
        });
      }
    },
    onTextDelta: (delta: string) => {
      updateLastAssistant((msg) => ({
        ...msg,
        content: msg.content + delta,
      }));
    },
    onToolStart: (_index: number, tool: string, args: Record<string, unknown>) => {
      const tc: ToolCallInfo = { tool, args, pending: true };
      updateLastAssistant((msg) => ({
        ...msg,
        toolCalls: [...(msg.toolCalls || []), tc],
      }));
    },
    onToolEnd: (_index: number, tool: string, result: Record<string, unknown>, durationMs: number, toolImages?: { path: string; url: string; tool: string }[]) => {
      updateLastAssistant((msg) => {
        const toolCalls = [...(msg.toolCalls || [])];
        const tcIdx = toolCalls.findIndex(
          (tc) => tc.tool === tool && tc.pending
        );
        if (tcIdx >= 0) {
          toolCalls[tcIdx] = {
            ...toolCalls[tcIdx],
            result,
            duration_ms: durationMs,
            pending: false,
            images: toolImages,
          };
        }
        const newImages = toolImages
          ? [...(msg.images || []), ...toolImages]
          : msg.images;
        return { ...msg, toolCalls, images: newImages };
      });
      onNewImages?.();
    },
    onStepStart: (stepId: number) => {
      setPlanSteps((prev) => prev.map((s) =>
        s.id === stepId ? { ...s, status: "active" as const } : s
      ));
    },
    onStepDone: (stepId: number) => {
      setPlanSteps((prev) => prev.map((s) =>
        s.id === stepId ? { ...s, status: "done" as const } : s
      ));
    },
    onPlanGate: () => {
      setPlanPaused(true);
      setLoading(false);
    },
    onPlanDone: () => {
      setPlanPaused(false);
      setPlanTurnId(null);
    },
    onDone: () => {
      setLoading(false);
      onNewImages?.();
      // Save all UI messages to DB for conversation restore
      const cid = conversationIdRef.current;
      if (cid) {
        setMessages((prev) => {
          saveUIMessages(cid, prev).catch(() => {});
          return prev;
        });
      }
    },
    onError: (error: string) => {
      updateLastAssistant((msg) => ({
        ...msg,
        content: msg.content + `\n${t("chat.errorPrefix")}: ${error}`,
      }));
      setLoading(false);
    },
  }), [onNewImages, updateLastAssistant, t]);

  // Send a message (used by handleSend, handleRetry, handleEditConfirm)
  const doSend = useCallback(async (
    text: string,
    images: AttachedImage[],
    turnId: string,
    overrideConversationId?: string | null,
    hiddenContext?: string,
  ) => {
    // Separate image vs non-image attachments
    const imageAttachments = images.filter((i) => !i.fileType || i.fileType === "image");
    const fileAttachments = images.filter((i) => i.fileType && i.fileType !== "image");
    const imagePaths = imageAttachments.map((i) => i.path);

    // Inject non-image file contents into the message text
    let finalText = text;
    if (fileAttachments.length > 0) {
      const fileParts = fileAttachments.map((f) => {
        const label = f.fileType === "json" ? "JSON" : "Markdown";
        return `[附件: ${f.name} (${label})]\n${f.content || "(无内容)"}`;
      });
      finalText = fileParts.join("\n\n") + (text ? "\n\n" + text : "");
    }

    const cidToUse = overrideConversationId !== undefined ? overrideConversationId : conversationId;

    // Create abort controller for this request
    const abort = new AbortController();
    abortRef.current = abort;

    // Build user messages for this turn
    const userMsgs: ChatMessage[] = [];
    if (imageAttachments.length > 0) {
      userMsgs.push({
        role: "user",
        turnId,
        type: "image",
        content: "",
        attachedImages: imageAttachments,
      });
    }
    if (fileAttachments.length > 0) {
      userMsgs.push({
        role: "user",
        turnId,
        type: "text",
        content: "",
        attachedImages: fileAttachments,
      });
    }
    userMsgs.push({
      role: "user",
      turnId,
      type: "text",
      content: text || (imageAttachments.length > 0 ? t("chat.imageLabel") : ""),
    });

    const assistantMsg: ChatMessage = {
      role: "assistant",
      turnId: newTurnId(),
      content: "",
      toolCalls: [],
      images: [],
    };

    setMessages((prev) => [...prev, ...userMsgs, assistantMsg]);
    setLoading(true);

    // API message includes hidden context (not shown in UI)
    const apiText = hiddenContext
      ? `${hiddenContext}${finalText || "请分析这些图片"}`
      : (finalText || "请分析这些图片");

    try {
      await streamMessage(
        apiText,
        cidToUse,
        makeCallbacks(),
        imagePaths.length > 0 ? imagePaths : undefined,
        project,
        abort.signal,
        lang,
        { mode, interactionMode, videoMode },
      );
    } catch (err) {
      if (abort.signal.aborted) {
        setLoading(false);
        abortRef.current = null;
        return;
      }
      updateLastAssistant((msg) => ({
        ...msg,
        content: msg.content + `\n${t("chat.errorPrefix")}: ${err}`,
      }));
      setLoading(false);
    }
  }, [conversationId, project, onNewImages, updateLastAssistant, makeCallbacks, lang, t, mode, interactionMode]);

  const handleSend = async () => {
    const text = input.trim();
    if ((!text && attachedImages.length === 0) || loading) return;

    const currentAttached = [...attachedImages];
    setInput("");
    setAttachedImages([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const turnId = newTurnId();
    await doSend(text, currentAttached, turnId);
  };

  // ========== Message Actions ==========

  const handleCopy = (turnId: string) => {
    const turnMsgs = messages.filter((m) => m.turnId === turnId);
    const text = turnMsgs.map((m) => m.content).filter(Boolean).join("\n");
    navigator.clipboard.writeText(text);
  };

  const handleDelete = (turnId: string) => {
    const idx = messages.findIndex((m) => m.turnId === turnId);
    if (idx < 0) return;
    setMessages((prev) => prev.slice(0, idx));
    setConversationId(null); // reset agent since context is lost
  };

  const handleRetry = async (turnId: string, role: "user" | "assistant") => {
    if (loading) return;

    let userTurnId: string;
    if (role === "user") {
      userTurnId = turnId;
    } else {
      // Find the user turn right before this assistant turn
      const idx = messages.findIndex((m) => m.turnId === turnId);
      if (idx < 0) return;
      // Walk backwards to find the preceding user turn
      let userIdx = idx - 1;
      while (userIdx >= 0 && messages[userIdx].role !== "user") userIdx--;
      if (userIdx < 0) return;
      userTurnId = messages[userIdx].turnId;
    }

    // Collect the user turn's data
    const turnMsgs = messages.filter((m) => m.turnId === userTurnId);
    const text = turnMsgs.find((m) => m.type === "text")?.content || "";
    const images = turnMsgs.find((m) => m.type === "image")?.attachedImages || [];

    // Build context from all messages before the retry point
    const idx = messages.findIndex((m) => m.turnId === userTurnId);
    const priorMessages = messages.slice(0, idx);
    const context = buildContext(priorMessages);

    // Delete from this user turn onwards
    setMessages((prev) => prev.slice(0, idx));
    setConversationId(null);

    // Re-send with context injected into API call (not shown in UI)
    const newTurn = newTurnId();
    await doSend(text, images, newTurn, null, context);
  };

  const handleEditStart = (turnId: string) => {
    const textMsg = messages.find((m) => m.turnId === turnId && m.type === "text");
    setEditingTurnId(turnId);
    setEditText(textMsg?.content || "");
  };

  const handleEditConfirm = async () => {
    if (!editingTurnId || loading) return;
    const turnId = editingTurnId;
    const newText = editText.trim();
    if (!newText) return;

    // Collect images from this turn
    const turnMsgs = messages.filter((m) => m.turnId === turnId);
    const images = turnMsgs.find((m) => m.type === "image")?.attachedImages || [];

    // Build context from messages before this turn
    const idx = messages.findIndex((m) => m.turnId === turnId);
    const priorMessages = messages.slice(0, idx);
    const context = buildContext(priorMessages);

    // Delete from this turn onwards
    setMessages((prev) => prev.slice(0, idx));
    setConversationId(null);

    setEditingTurnId(null);
    setEditText("");

    const newTurn = newTurnId();
    await doSend(newText, images, newTurn, null, context);
  };

  const handleEditCancel = () => {
    setEditingTurnId(null);
    setEditText("");
  };

  const handleCharacterConfirm = async (selected: CharacterOption[]) => {
    if (loading || selected.length === 0) return;
    const lines = selected.map(
      (c) => `- ${c.label || c.name}: ${c.path}`
    );
    const text = `已确认角色：\n${lines.join("\n")}`;
    const turnId = newTurnId();
    await doSend(text, [], turnId);
  };

  const handleFaceConfirm = async (selected: FaceInfo[]) => {
    if (loading) return;
    if (selected.length === 0) {
      const turnId = newTurnId();
      await doSend("用户跳过了风格化，不需要风格化任何人脸。", [], turnId);
      return;
    }
    const lines = selected.map(
      (f) => `- ${f.name}: ${f.crop_path}`
    );
    const text = `请风格化以下人脸：\n${lines.join("\n")}`;
    const turnId = newTurnId();
    await doSend(text, [], turnId);
  };

  // ========== Plan Actions (backend-driven) ==========

  const handlePlanConfirm = async (turnId: string, steps: PlanStep[], autoExecute = true) => {
    if (loading || !conversationId) return;
    setPlanTurnId(turnId);
    setPlanSteps(steps);
    setPlanPaused(false);
    setLoading(true);

    const abort = new AbortController();
    abortRef.current = abort;

    // Add assistant message for streaming responses
    const assistantMsg: ChatMessage = {
      role: "assistant",
      turnId: newTurnId(),
      content: "",
      toolCalls: [],
      images: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await streamMessage(
        "",
        conversationId,
        makeCallbacks(),
        undefined,
        project,
        abort.signal,
        lang,
        { planAction: "confirm", planSteps: steps, planAuto: autoExecute, mode, interactionMode, videoMode },
      );
    } catch (err) {
      if (!abort.signal.aborted) {
        updateLastAssistant((msg) => ({
          ...msg,
          content: msg.content + `\n${t("chat.errorPrefix")}: ${err}`,
        }));
        setLoading(false);
      }
    }
  };

  const handlePlanRevise = async (prompt: string) => {
    if (loading) return;
    setPlanTurnId(null);
    setPlanSteps([]);
    const tid = newTurnId();
    await doSend(`用户要求修改计划：${prompt}`, [], tid);
  };

  const handlePlanContinue = async (prompt?: string) => {
    if (loading || !conversationId) return;
    setPlanPaused(false);
    setLoading(true);

    const abort = new AbortController();
    abortRef.current = abort;

    const assistantMsg: ChatMessage = {
      role: "assistant",
      turnId: newTurnId(),
      content: "",
      toolCalls: [],
      images: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await streamMessage(
        "",
        conversationId,
        makeCallbacks(),
        undefined,
        project,
        abort.signal,
        lang,
        { planAction: "continue", planPrompt: prompt, mode, interactionMode, videoMode },
      );
    } catch (err) {
      if (!abort.signal.aborted) {
        updateLastAssistant((msg) => ({
          ...msg,
          content: msg.content + `\n${t("chat.errorPrefix")}: ${err}`,
        }));
        setLoading(false);
      }
    }
  };

  const handlePlanCancel = async () => {
    setPlanSteps((prev) => prev.map((s) =>
      s.status === "pending" || s.status === "active"
        ? { ...s, status: "skipped" as const }
        : s
    ));
    setPlanPaused(false);
    if (conversationId) {
      // Fire-and-forget cancel to backend
      fetch(`http://localhost:8000/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          plan_action: "cancel",
          project,
          lang,
        }),
      }).catch(() => {});
    }
  };

  // ========== Verdict Actions ==========

  const setToolVerdict = (turnId: string, toolIndex: number, verdict: ImageVerdict) => {
    setMessages((prev) => {
      const updated = prev.map((msg) => {
        if (msg.turnId !== turnId || !msg.toolCalls) return msg;
        const toolCalls = msg.toolCalls.map((tc, i) =>
          i === toolIndex ? { ...tc, verdict } : tc
        );
        return { ...msg, toolCalls };
      });
      const cid = conversationIdRef.current;
      if (cid) saveUIMessages(cid, updated).catch(() => {});
      return updated;
    });
  };

  const handleAccept = (turnId: string, toolIndex: number) => {
    setToolVerdict(turnId, toolIndex, "accepted");
  };

  const handleRejectImage = async (turnId: string, toolIndex: number) => {
    // Find the tool call to get the output path
    const msg = messages.find((m) => m.turnId === turnId && m.toolCalls);
    const tc = msg?.toolCalls?.[toolIndex];
    if (tc?.images) {
      for (const img of tc.images) {
        try { await deleteAsset(img.path); } catch { /* ignore */ }
      }
    }
    setToolVerdict(turnId, toolIndex, "rejected");
    onNewImages?.();
    // Tell agent user rejected
    const toolName = tc?.tool || "generate";
    const rejectTurn = newTurnId();
    await doSend(`用户拒绝了 ${toolName} 的生成结果，请不要再使用同样的方式。`, [], rejectTurn);
  };

  const handleRevise = async (turnId: string, toolIndex: number, prompt: string) => {
    const msg = messages.find((m) => m.turnId === turnId && m.toolCalls);
    const tc = msg?.toolCalls?.[toolIndex];
    const outputPath = tc?.result?.output_path as string | undefined;
    setToolVerdict(turnId, toolIndex, "rejected");

    // Build context about other tool results so agent knows what NOT to redo
    const otherAccepted: string[] = [];
    if (msg?.toolCalls) {
      for (let i = 0; i < msg.toolCalls.length; i++) {
        if (i === toolIndex) continue;
        const other = msg.toolCalls[i];
        const otherPath = other?.result?.output_path as string | undefined;
        const verdict = other?.verdict;
        if (otherPath && verdict !== "rejected") {
          otherAccepted.push(otherPath);
        }
      }
    }

    // Send revise request with clear instruction to only modify this one
    let reviseText = outputPath
      ? `请修改这张图片 (${outputPath})：${prompt}`
      : `请重新生成：${prompt}`;
    reviseText += "\n注意：只修改这一个素材，不要重新生成其他素材。";
    if (otherAccepted.length > 0) {
      reviseText += `以下素材用户已接受，不要修改：${otherAccepted.join("、")}`;
    }
    const reviseTurn = newTurnId();
    await doSend(reviseText, [], reviseTurn);
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setLoading(false);
      onNewImages?.();
      // Mark any still-pending tool calls as completed (remove spinner)
      updateLastAssistant((msg) => {
        if (!msg.toolCalls?.some((tc) => tc.pending)) return msg;
        return {
          ...msg,
          toolCalls: msg.toolCalls.map((tc) =>
            tc.pending ? { ...tc, pending: false, result: { error: "stopped" } } : tc
          ),
        };
      });
    }
  };

  // ========== Conversation History Actions ==========

  const handleRestoreConversation = async (conv: Conversation) => {
    try {
      const msgs = await fetchUIMessages(conv.id);
      setMessages(msgs);
      setConversationId(conv.id);
      setConversationTitle(conv.title || "");
      setPlanSteps([]);
      setPlanPaused(false);
    } catch (err) {
      console.error("Failed to restore conversation:", err);
    }
  };

  const handleNewChat = () => {
    setMessages([]);
    setConversationId(null);
    setConversationTitle("");
    setPlanSteps([]);
    setPlanPaused(false);
    setPlanTurnId(null);
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) handleNewChat();
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  const composingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (composingRef.current) return; // IME 输入中，忽略 Enter
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Group consecutive messages by turnId for rendering
  const renderGroups: { turnId: string; role: "user" | "assistant"; msgs: ChatMessage[] }[] = [];
  for (const msg of messages) {
    const last = renderGroups[renderGroups.length - 1];
    if (last && last.turnId === msg.turnId) {
      last.msgs.push(msg);
    } else {
      renderGroups.push({ turnId: msg.turnId, role: msg.role, msgs: [msg] });
    }
  }

  return (
    <div className="flex flex-col h-full relative">
      {/* Header with conversation history dropdown */}
      <div className="flex items-center justify-center px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shrink-0">
        <ConversationHistory
          conversations={conversations}
          currentId={conversationId}
          currentTitle={conversationTitle}
          onSelect={handleRestoreConversation}
          onNew={handleNewChat}
          onDelete={handleDeleteConversation}
          onRefresh={loadConversations}
        />
      </div>
      {/* Messages / Empty state */}
      <div className={`flex-1 overflow-y-auto px-44 py-4 ${messages.length === 0 ? "flex flex-col items-center justify-center" : "space-y-4"}`}>
        {messages.length === 0 && (
          <div className="text-center text-gray-400 dark:text-gray-500 mb-6 w-full max-w-2xl">
            <div className="relative w-48 mb-4 mx-auto">
              <img src="/hero.png" alt="Animegent" className="w-full" />
              <div className="absolute inset-0 pointer-events-none" style={{
                background: "radial-gradient(circle, transparent 30%, rgb(249 250 251) 75%)"
              }} />
            </div>
            <div className="text-lg font-medium">{t("chat.appName")}</div>
            <div className="text-sm mt-1">{t("chat.appSubtitle")}</div>
          </div>
        )}

        {renderGroups.map((group) => {
          const { turnId, role, msgs } = group;
          const isUser = role === "user";
          const isAssistant = role === "assistant";

          // Skip empty assistant messages that haven't started streaming
          if (
            isAssistant &&
            msgs.every((m) => !m.content && (!m.toolCalls || m.toolCalls.length === 0)) &&
            !loading
          ) {
            return null;
          }

          const isEditing = editingTurnId === turnId;

          // Collect data across sub-messages
          const allAttachedImages = msgs.flatMap((m) => m.attachedImages || []);
          const textContent = msgs.map((m) => m.content).filter(Boolean).join("\n");
          const allToolCalls = msgs.flatMap((m) => m.toolCalls || []);
          const allImages = msgs.flatMap((m) => m.images || []);

          // Check if this is the last group and assistant is streaming
          const isLastGroup = group === renderGroups[renderGroups.length - 1];
          const isStreaming = isAssistant && loading && isLastGroup;

          return (
            <div
              key={turnId}
              className={`flex ${isUser ? "justify-end" : "justify-start"} group`}
            >
              <div className="flex flex-col max-w-[80%]">
                <div
                  className={`rounded-2xl px-4 py-2.5 ${
                    isUser
                      ? "bg-blue-500 text-white"
                      : "bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-800 dark:text-gray-200"
                  }`}
                >
                  {/* Attached images (user message) */}
                  {allAttachedImages.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {allAttachedImages.map((img, j) => (
                        <img
                          key={j}
                          src={img.previewUrl || getFileUrl(img.url)}
                          alt={img.name}
                          className="w-16 h-16 object-cover rounded-lg border border-blue-300"
                        />
                      ))}
                    </div>
                  )}

                  {/* Tool calls (assistant) */}
                  {allToolCalls.length > 0 && (
                    <div className="mb-2 space-y-1.5">
                      {allToolCalls.map((tc, j) =>
                        tc.tool === "propose_plan" && tc.result?.type === "task_plan" ? (
                          <TaskPlanCard
                            key={j}
                            steps={planTurnId === turnId ? planSteps : (tc.result.steps as PlanStep[]) || []}
                            onConfirm={(steps, auto) => handlePlanConfirm(turnId, steps, auto)}
                            onRevise={handlePlanRevise}
                            onContinue={handlePlanContinue}
                            onCancel={handlePlanCancel}
                            paused={planTurnId === turnId && planPaused}
                            disabled={loading}
                          />
                        ) : tc.tool === "select_characters" && tc.result?.type === "character_select" ? (
                          <CharacterSelectCard
                            key={j}
                            options={(tc.result.options as CharacterOption[]) || []}
                            onConfirm={handleCharacterConfirm}
                            disabled={loading}
                          />
                        ) : tc.tool === "select_faces" && tc.result?.type === "face_select" ? (
                          <FaceSelectCard
                            key={j}
                            faces={((tc.result.faces as FaceInfo[]) || []).map((f) => ({
                              ...f,
                              crop_url: f.crop_url || "",
                            }))}
                            skippedSmall={0}
                            skippedBlurry={0}
                            onConfirm={handleFaceConfirm}
                            disabled={loading}
                          />
                        ) : (
                          <ToolCallCard
                            key={j}
                            toolCall={tc}
                            onAccept={() => handleAccept(turnId, j)}
                            onReject={() => handleRejectImage(turnId, j)}
                            onRevise={(prompt) => handleRevise(turnId, j, prompt)}
                          />
                        )
                      )}
                    </div>
                  )}

                  {/* Text content (or edit mode) */}
                  {isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="w-full bg-blue-400 text-white rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-white min-h-[60px]"
                        autoFocus
                        onCompositionStart={() => { composingRef.current = true; }}
                        onCompositionEnd={() => { composingRef.current = false; }}
                        onKeyDown={(e) => {
                          if (composingRef.current) return;
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleEditConfirm();
                          }
                          if (e.key === "Escape") handleEditCancel();
                        }}
                      />
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={handleEditCancel}
                          className="px-2 py-0.5 text-xs bg-blue-400 text-white rounded hover:bg-blue-300"
                        >
                          {t("common.cancel")}
                        </button>
                        <button
                          onClick={handleEditConfirm}
                          className="px-2 py-0.5 text-xs bg-white dark:bg-gray-800 text-blue-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                        >
                          {t("common.send")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    textContent && (
                      <MarkdownText text={textContent} />
                    )
                  )}

                  {/* Loading indicator */}
                  {isStreaming && !textContent && allToolCalls.length === 0 && (
                    <div className="flex space-x-1.5">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.1s]" />
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
                    </div>
                  )}

                  {/* Non-generation tool images — only show images not already displayed in ToolCallCards */}
                  {(() => {
                    const TOOLS_WITH_CARDS = new Set([
                      "stylize_character", "generate_asset", "generate_comic_strip", "edit_asset",
                      "generate_storyboard_strip", "generate_video_clip", "detect_faces_in_image",
                    ]);
                    const VIDEO_EXTS = [".mp4", ".webm", ".mov"];
                    const nonCardImages = allImages.filter((img) => !TOOLS_WITH_CARDS.has(img.tool) && !VIDEO_EXTS.some((ext) => img.path.toLowerCase().endsWith(ext)));
                    return nonCardImages.length > 0 ? (
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        {nonCardImages.map((img, j) => (
                          <a key={j} href={getFileUrl(img.url)} target="_blank" rel="noopener noreferrer">
                            <img src={getFileUrl(img.url)} alt={img.tool} className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-64 object-contain" />
                          </a>
                        ))}
                      </div>
                    ) : null;
                  })()}
                </div>

                {/* Message actions toolbar */}
                {!isEditing && !isStreaming && (
                  <MessageActions
                    role={role}
                    onCopy={() => handleCopy(turnId)}
                    onEdit={isUser ? () => handleEditStart(turnId) : undefined}
                    onRetry={() => handleRetry(turnId, role)}
                    onDelete={() => handleDelete(turnId)}
                  />
                )}
              </div>
            </div>
          );
        })}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className={`transition-all duration-500 ease-in-out ${messages.length === 0
        ? "px-44 pb-[30vh] relative"
        : "px-44 pt-3 pb-[72px] relative"
      }`}>
        {messages.length > 0 && (
          <div className="absolute -top-10 left-0 right-0 h-10 bg-gradient-to-t from-gray-50 dark:from-gray-900 to-transparent pointer-events-none" />
        )}
        <div
          className={`border rounded-2xl transition-colors bg-white dark:bg-gray-800 shadow-lg dark:shadow-gray-900/50 ${
            dragOver
              ? "border-blue-400 bg-blue-50 dark:bg-blue-900/30"
              : "border-gray-200 dark:border-gray-700 focus-within:border-pink-400 focus-within:ring-1 focus-within:ring-pink-400"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          {/* Attached assets inside input box */}
          {(attachedImages.length > 0 || uploading) && (
            <div className="px-3 pt-3 flex flex-wrap gap-2">
              {attachedImages.map((att, i) => {
                const ft = att.fileType || "image";
                const isImg = ft === "image";
                return (
                  <div
                    key={i}
                    className="relative group cursor-pointer"
                    onClick={() => onPendingAssetClick?.(att.path)}
                  >
                    {isImg ? (
                      <img
                        src={att.previewUrl || getFileUrl(att.url)}
                        alt={att.name}
                        className="w-16 h-16 object-cover rounded-xl border border-gray-200 dark:border-gray-700"
                      />
                    ) : (
                      <div className="h-16 flex items-center gap-1.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-2.5">
                        <span className="text-sm text-gray-400 dark:text-gray-500 font-mono">
                          {ft === "json" ? "{}" : "MD"}
                        </span>
                        <span className="text-[10px] text-gray-500 dark:text-gray-400 truncate max-w-[80px]">
                          {att.name}
                        </span>
                      </div>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); removeAttached(i); }}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm"
                    >
                      ×
                    </button>
                  </div>
                );
              })}
              {uploading && (
                <div className="w-16 h-16 rounded-xl border border-dashed border-gray-300 dark:border-gray-600 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
                  <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                </div>
              )}
            </div>
          )}

          {/* Drag overlay hint */}
          {dragOver && (
            <div className="px-3 pt-2 text-xs text-blue-500 text-center">
              {t("chat.dropHint")}
            </div>
          )}

          {/* Text input */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => { setInput(e.target.value); autoResize(); }}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            onPaste={handlePaste}
            placeholder={t("chat.inputPlaceholder")}
            className="w-full resize-none border-0 bg-transparent px-4 py-2.5 text-sm focus:outline-none dark:text-gray-200 dark:placeholder-gray-500"
            style={{ maxHeight: 160 }}
            rows={5}
          />

          {/* Bottom toolbar */}
          <div className="flex items-center justify-between px-2 pb-2">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="p-1.5 text-gray-400 dark:text-gray-500 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
                title={t("chat.uploadImage")}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="17 8 12 3 7 8"/>
                  <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />
              <div className="h-4 w-px bg-gray-200" />
              <div className="flex flex-col items-center">
                <ModeSelector mode={mode} onChange={setMode} disabled={loading} />
                <span className="text-[9px] text-gray-400 dark:text-gray-500 leading-none mt-0.5">{t("toolbar.mode")}</span>
              </div>
              <div className="flex flex-col items-center">
                <InteractionModeSelector mode={interactionMode} onChange={setInteractionMode} disabled={loading} />
                <span className="text-[9px] text-gray-400 dark:text-gray-500 leading-none mt-0.5">{t("toolbar.style")}</span>
              </div>
              {mode === "storyboard" && (
                <div className="flex flex-col items-center">
                  <div className="flex items-center bg-gray-100 dark:bg-gray-700 rounded-md p-0.5 text-[11px]">
                    {(["grok", "veo"] as const).map((v) => (
                      <button
                        key={v}
                        onClick={() => setVideoMode(v)}
                        disabled={loading}
                        className={`px-2 py-0.5 rounded transition-colors ${
                          videoMode === v
                            ? "bg-white dark:bg-gray-600 text-gray-800 dark:text-gray-100 shadow-sm font-medium"
                            : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                        } disabled:opacity-50`}
                      >
                        {v === "grok" ? "Grok" : "Veo"}
                      </button>
                    ))}
                  </div>
                  <span className="text-[9px] text-gray-400 dark:text-gray-500 leading-none mt-0.5">{t("toolbar.videoModel")}</span>
                </div>
              )}
            </div>
            {loading ? (
              <button
                onClick={handleStop}
                className="p-1.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                title={t("chat.stop")}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() && attachedImages.length === 0}
                className="p-1.5 bg-pink-500 text-white rounded-lg hover:bg-pink-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title={t("common.send")}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="19" x2="12" y2="5"/>
                  <polyline points="5 12 12 5 19 12"/>
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
