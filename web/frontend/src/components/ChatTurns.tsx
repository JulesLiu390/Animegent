import { memo, useEffect, useRef, useState } from "react";
import type { AttachedImage, CharacterOption, FaceInfo, Step, StepResponse, Turn } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../hooks";
import { selectionOf, stepDomId, turnText } from "../lib/turns";
import CharacterSelectCard from "./CharacterSelectCard";
import FaceSelectCard from "./FaceSelectCard";
import Icon from "./Icon";
import LegacyPlanCard from "./LegacyPlanCard";
import MarkdownText from "./MarkdownText";
import MessageActions from "./MessageActions";
import ToolCallCard from "./ToolCallCard";

// ==================== 用户消息 ====================

interface UserTurnProps {
  turn: Turn;
  editing: boolean;
  busy: boolean;
  onEditStart: (turnId: string) => void;
  onEditSubmit: (turnId: string, text: string) => void;
  onEditCancel: () => void;
  onRetry: (turnId: string) => void;
  onDelete: (turnId: string) => void;
  onAttachmentClick: (attachment: AttachedImage, all: AttachedImage[]) => void;
}

export const UserTurn = memo(function UserTurn({ turn, editing, busy, onEditStart, onEditSubmit, onEditCancel, onRetry, onDelete, onAttachmentClick }: UserTurnProps) {
  const { t } = useLang();
  const attachments = turn.input.attachments || [];
  const text = turn.input.display ?? turn.input.text;
  const [expanded, setExpanded] = useState(false);
  const long = text.length > 900 || text.split("\n").length > 16;
  if (!text && attachments.length === 0) return null;

  return (
    <div className="group flex flex-col items-end">
      {attachments.length > 0 && (
        <div className="mb-1.5 flex max-w-[85%] flex-wrap justify-end gap-1.5">
          {attachments.map((att, i) => {
            const isImg = !att.fileType || att.fileType === "image";
            return (
              <button
                key={`${att.path}-${i}`}
                onClick={() => onAttachmentClick(att, attachments)}
                className="overflow-hidden rounded-xl border border-zinc-200 bg-white transition-opacity hover:opacity-90 dark:border-zinc-700 dark:bg-zinc-900"
                title={att.name}
              >
                {isImg ? (
                  <img src={att.previewUrl || getFileUrl(att.url)} alt="" className={`${attachments.length === 1 ? "max-h-56 max-w-[240px]" : "h-24 w-24 object-cover"}`} />
                ) : (
                  <div className="flex items-center gap-2 px-3 py-2">
                    <Icon name={att.fileType === "json" ? "braces" : att.fileType === "video" ? "video" : "file-text"} className="h-4 w-4 text-zinc-400" />
                    <span className="max-w-[160px] truncate text-xs text-zinc-600 dark:text-zinc-300">{att.name}</span>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {editing ? (
        <EditBox initial={turn.input.text} onSubmit={(value) => onEditSubmit(turn.id, value)} onCancel={onEditCancel} />
      ) : text ? (
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-brand-500 to-brand-600 px-4 py-2.5 text-[14px] leading-relaxed text-white shadow-sm">
          <div className="relative">
            <div className={`whitespace-pre-wrap break-words ${long && !expanded ? "max-h-72 overflow-hidden" : ""}`}>{text}</div>
            {long && !expanded && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-brand-600 to-transparent" />}
          </div>
          {long && (
            <button onClick={() => setExpanded(!expanded)} className="mt-1.5 text-xs font-medium text-white/85 underline-offset-2 hover:text-white hover:underline">
              {expanded ? t("common.showLess") : t("common.showMore")}
            </button>
          )}
        </div>
      ) : null}

      {!editing && (
        <MessageActions
          align="end"
          disabled={busy}
          onCopy={text ? () => navigator.clipboard?.writeText(text) : undefined}
          // 旧版对话只能看，不能回退
          onEdit={turn.legacy ? undefined : () => onEditStart(turn.id)}
          onRetry={turn.legacy ? undefined : () => onRetry(turn.id)}
          onDelete={turn.legacy ? undefined : () => onDelete(turn.id)}
        />
      )}
    </div>
  );
});

function EditBox({ initial, onSubmit, onCancel }: { initial: string; onSubmit: (text: string) => void; onCancel: () => void }) {
  const { t } = useLang();
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [value]);

  useEffect(() => {
    const el = ref.current;
    el?.focus();
    el?.setSelectionRange(el.value.length, el.value.length);
  }, []);

  return (
    <div className="w-full max-w-[85%] rounded-2xl border border-brand-300 bg-white p-2 shadow-sm dark:border-brand-500/40 dark:bg-zinc-900">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(e) => {
          if (composing.current || e.nativeEvent.isComposing) return;
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (value.trim()) onSubmit(value.trim());
          }
          if (e.key === "Escape") onCancel();
        }}
        className="block w-full resize-none bg-transparent px-2 py-1 text-[14px] leading-relaxed text-zinc-800 focus:outline-none dark:text-zinc-100"
      />
      <div className="mt-1 flex items-center justify-between gap-2 px-1">
        <span className="text-[11px] text-zinc-400">{t("chat.editHint")}</span>
        <div className="flex gap-1.5">
          <button onClick={onCancel} className="btn-secondary">{t("common.cancel")}</button>
          <button onClick={() => value.trim() && onSubmit(value.trim())} disabled={!value.trim()} className="btn-primary">{t("chat.resend")}</button>
        </div>
      </div>
    </div>
  );
}

// ==================== 助手回复 ====================

export interface StepHandlers {
  /** 回应等待中的 step：批准 / 拒绝生成，或者卡片里的选择 */
  onRespond: (turnId: string, stepId: string, response: StepResponse) => void;
  onAccept: (step: Step) => void;
  onDiscard: (step: Step) => void;
  onRevise: (step: Step, prompt: string) => void;
  onCancelJob: (step: Step) => void;
}

interface AssistantTurnProps {
  turn: Turn;
  streaming: boolean;
  busy: boolean;
  project: string;
  handlers: StepHandlers;
  onOpenLink: (url: string) => boolean;
  onOpenSettings: () => void;
  onRetry: (turnId: string) => void;
  onDelete: (turnId: string) => void;
}

export const AssistantTurn = memo(function AssistantTurn({ turn, streaming, busy, project, handlers, onOpenLink, onOpenSettings, onRetry, onDelete }: AssistantTurnProps) {
  const { t } = useLang();
  const steps = turn.steps;
  const last = steps[steps.length - 1];
  const working = steps.some((s) => s.status === "running");
  const thinking = streaming && !working && (!last || last.kind === "tool");
  const failed = turn.status === "failed" && turn.error;
  const stopped = turn.status === "cancelled";
  if (steps.length === 0 && !streaming && !failed && !stopped) return null;

  const respond = (step: Step, response: StepResponse) => handlers.onRespond(turn.id, step.id, response);

  const renderTool = (step: Step) => {
    const display = step.display || {};
    const interactive = step.status === "awaiting_input" && !turn.legacy;
    if (step.tool === "propose_plan" && display.plan) return <LegacyPlanCard plan={display.plan} />;
    if (step.tool === "select_characters" && display.options) {
      return (
        <CharacterSelectCard
          options={display.options}
          selection={selectionOf(step)}
          interactive={interactive}
          busy={busy}
          onConfirm={(selected: CharacterOption[]) => respond(step, { value: { selected: selected.map((c) => ({ path: c.path, label: c.label })) } })}
        />
      );
    }
    if (step.tool === "select_faces" && display.faces) {
      return (
        <FaceSelectCard
          faces={display.faces.map((f: FaceInfo) => ({ ...f, crop_url: f.crop_url || "" }))}
          selection={selectionOf(step)}
          interactive={interactive}
          busy={busy}
          onConfirm={(selected: FaceInfo[]) => respond(step, { value: { selected: selected.map((f) => f.crop_path) } })}
          onSkip={() => respond(step, { value: { skipped: true } })}
        />
      );
    }
    return (
      <ToolCallCard
        step={step}
        busy={busy}
        project={project}
        onOpenLink={onOpenLink}
        onApprove={() => respond(step, { approve: true })}
        onReject={() => respond(step, { approve: false })}
        onAccept={() => handlers.onAccept(step)}
        onDiscard={() => handlers.onDiscard(step)}
        onRevise={(prompt) => handlers.onRevise(step, prompt)}
        onCancelJob={() => handlers.onCancelJob(step)}
      />
    );
  };

  const errorText = turn.error === "connection-lost" ? t("chat.connectionLost") : turn.error;
  const copyText = turnText(turn);

  return (
    <div className="group flex gap-3">
      <div className="mt-0.5 h-7 w-7 shrink-0 overflow-hidden rounded-full ring-1 ring-zinc-200 dark:ring-zinc-700">
        <img src="/logo-64.png" alt="" className="h-full w-full scale-110 object-cover" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="space-y-2.5">
          {steps.map((step) => step.kind === "message" ? (
            step.text?.trim() ? (
              <MarkdownText
                key={step.id}
                text={step.text}
                project={project}
                onOpenLink={onOpenLink}
                streaming={streaming && step.status === "running"}
              />
            ) : null
          ) : (
            <div key={step.id} id={stepDomId(step.id)} className="scroll-mt-4">{renderTool(step)}</div>
          ))}
        </div>

        {thinking && (
          <div className="flex h-7 items-center gap-1.5 text-xs text-zinc-400">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400" />
            </span>
            {steps.length === 0 && t("chat.thinking")}
          </div>
        )}

        {failed && (
          <div className="mt-2.5 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
            <Icon name="alert-circle" className="mt-0.5 h-4 w-4" />
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium">{t("chat.errorPrefix")}</div>
              <div className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-relaxed opacity-90">{errorText}</div>
            </div>
            {turn.error_kind === "config" && (
              <button onClick={onOpenSettings} className="btn shrink-0 bg-white text-red-600 shadow-sm hover:bg-red-100 dark:bg-red-500/20 dark:text-red-200 dark:hover:bg-red-500/30">
                <Icon name="settings" className="h-3.5 w-3.5" />{t("chat.configError")}
              </button>
            )}
          </div>
        )}

        {stopped && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-zinc-100 px-2 py-1 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            <Icon name="stop" className="h-3 w-3" />{t("chat.stopped")}
          </div>
        )}

        {!streaming && (
          <MessageActions
            disabled={busy}
            onCopy={copyText ? () => navigator.clipboard?.writeText(copyText) : undefined}
            onRetry={turn.legacy ? undefined : () => onRetry(turn.id)}
            onDelete={turn.legacy ? undefined : () => onDelete(turn.id)}
          />
        )}
      </div>
    </div>
  );
});
