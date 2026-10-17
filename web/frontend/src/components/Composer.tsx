import { useEffect, useRef, type ChangeEvent, type ClipboardEvent, type KeyboardEvent, type ReactNode } from "react";
import type { AppSettings, AttachedImage, CreationMode, InteractionMode } from "../api";
import { getFileUrl, isStoryboardEnabled } from "../api";
import { useLang } from "../hooks";
import Icon, { Spinner } from "./Icon";
import InteractionModeSelector from "./InteractionModeSelector";
import ModeSelector from "./ModeSelector";
import type { SettingsTab } from "./SettingsModal";
import VideoModelSelector from "./VideoModelSelector";

interface Props {
  value: string;
  onChange: (value: string) => void;
  attachments: AttachedImage[];
  uploading: boolean;
  onFiles: (files: File[]) => void;
  onRemoveAttachment: (index: number) => void;
  onAttachmentClick: (attachment: AttachedImage) => void;
  onSend: () => void;
  onStop: () => void;
  loading: boolean;
  /** 没配置对话模型时不能发送 */
  blocked: boolean;
  mode: CreationMode;
  onModeChange: (mode: CreationMode) => void;
  interactionMode: InteractionMode;
  onInteractionModeChange: (mode: InteractionMode) => void;
  settings: AppSettings | null;
  onSettingsChange: (settings: AppSettings) => void;
  onOpenSettings: (tab?: SettingsTab) => void;
  dragOver: boolean;
  status?: ReactNode;
  focusKey?: number;
}

export default function Composer(props: Props) {
  const {
    value, onChange, attachments, uploading, onFiles, onRemoveAttachment, onAttachmentClick, onSend, onStop,
    loading, blocked, mode, onModeChange, interactionMode, onInteractionModeChange, settings, onSettingsChange,
    onOpenSettings, dragOver, status, focusKey,
  } = props;
  const { t } = useLang();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composingRef = useRef(false);

  // 内容变化（包括外部填入示例、发送后清空）时调整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  useEffect(() => {
    if (focusKey) textareaRef.current?.focus();
  }, [focusKey]);

  const canSend = !loading && !blocked && !uploading && (value.trim().length > 0 || attachments.length > 0);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // 输入法组合中按 Enter 是确认候选词，不发送
    if (composingRef.current || e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handlePaste = (e: ClipboardEvent) => {
    const files = Array.from(e.clipboardData.items)
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((f): f is File => Boolean(f));
    if (files.length > 0) {
      e.preventDefault();
      onFiles(files);
    }
  };

  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (files.length) onFiles(files);
  };

  return (
    <div className="w-full">
      <div
        className={`rounded-2xl border bg-white shadow-soft transition-all dark:bg-zinc-900 ${
          dragOver
            ? "border-brand-400 ring-4 ring-brand-400/15"
            : "border-zinc-200 focus-within:border-brand-300 focus-within:ring-4 focus-within:ring-brand-400/10 dark:border-zinc-800 dark:focus-within:border-brand-500/50"
        }`}
      >
        {(attachments.length > 0 || uploading) && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachments.map((att, i) => {
              const isImg = !att.fileType || att.fileType === "image";
              return (
                <div key={`${att.path}-${i}`} className="group relative">
                  <button
                    type="button"
                    onClick={() => onAttachmentClick(att)}
                    className="block overflow-hidden rounded-xl border border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800"
                    title={att.name}
                  >
                    {isImg ? (
                      <img src={att.previewUrl || getFileUrl(att.url)} alt="" className="h-16 w-16 object-cover" />
                    ) : (
                      <div className="flex h-16 w-28 flex-col justify-center gap-1 px-2.5 text-left">
                        <Icon name={att.fileType === "json" ? "braces" : att.fileType === "video" ? "video" : "file-text"} className="h-4 w-4 text-zinc-400" />
                        <span className="truncate text-[11px] text-zinc-600 dark:text-zinc-300">{att.name}</span>
                      </div>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(i)}
                    className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-white opacity-0 shadow transition-opacity hover:bg-red-500 group-hover:opacity-100 dark:bg-zinc-600"
                  >
                    <Icon name="x" className="h-3 w-3" strokeWidth={3} />
                  </button>
                </div>
              );
            })}
            {uploading && (
              <div className="flex h-16 w-16 items-center justify-center rounded-xl border border-dashed border-zinc-300 text-brand-500 dark:border-zinc-700">
                <Spinner className="h-5 w-5" />
              </div>
            )}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={() => { composingRef.current = false; }}
          onPaste={handlePaste}
          placeholder={interactionMode === "ask" ? t("chat.inputPlaceholderAsk") : t("chat.inputPlaceholder")}
          rows={2}
          className="block max-h-[220px] min-h-[52px] w-full resize-none border-0 bg-transparent px-4 pb-1 pt-3 text-[14px] leading-relaxed text-zinc-800 placeholder-zinc-400 focus:outline-none focus:ring-0 dark:text-zinc-100 dark:placeholder-zinc-500"
        />

        <div className="flex items-center gap-1.5 px-2 pb-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="icon-btn"
            title={t("chat.uploadImage")}
          >
            <Icon name="paperclip" className="h-[18px] w-[18px]" />
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileSelect} className="hidden" />
          <div className="mx-0.5 h-5 w-px bg-zinc-200 dark:bg-zinc-700" />
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            {/* 分镜模式休眠时只有条漫一种创作模式，不显示切换 */}
            {isStoryboardEnabled(settings) && <ModeSelector mode={mode} onChange={onModeChange} disabled={loading} />}
            <InteractionModeSelector mode={interactionMode} onChange={onInteractionModeChange} disabled={loading} />
            {mode === "storyboard" && (
              <VideoModelSelector
                settings={settings}
                onChange={onSettingsChange}
                onOpenSettings={() => onOpenSettings("models")}
                disabled={loading}
              />
            )}
          </div>
          {loading ? (
            <button type="button" onClick={onStop} className="flex h-8 w-8 items-center justify-center rounded-xl bg-zinc-900 text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white" title={t("chat.stop")}>
              <Icon name="stop" className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-500 text-white shadow-sm transition-all hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400 disabled:shadow-none dark:disabled:bg-zinc-800 dark:disabled:text-zinc-600"
              title={t("common.send")}
            >
              <Icon name="arrow-up" className="h-4 w-4" strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
      <div className="mt-1.5 flex h-4 items-center justify-between gap-3 px-2 text-[11px] text-zinc-400">
        <div className="min-w-0 truncate">{status}</div>
        <div className="hidden shrink-0 sm:block">{t("chat.inputHint")}</div>
      </div>
    </div>
  );
}
