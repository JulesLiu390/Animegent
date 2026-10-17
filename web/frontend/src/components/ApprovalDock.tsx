import { useRef, useState } from "react";
import type { Turn } from "../api";
import { useLang } from "../hooks";
import { toolLabel } from "../lib/tools";
import Icon from "./Icon";

interface Props {
  turn: Turn;
  busy: boolean;
  onApproveAll: () => void;
  onRejectAll: (note: string) => void;
  /** 滚动到等待处理的卡片 */
  onJump: () => void;
}

/** 输入框上方的提示条：这一轮在等你批准生成，或者等你在卡片里做选择。 */
export default function ApprovalDock({ turn, busy, onApproveAll, onRejectAll, onJump }: Props) {
  const { t } = useLang();
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const composingRef = useRef(false);

  const pending = turn.steps.filter((s) => s.status === "pending_approval");
  const waitingInput = turn.status === "awaiting_input" || turn.steps.some((s) => s.status === "awaiting_input");
  // 同一个工具合并显示：生成条漫 ×4
  const counts = new Map<string, number>();
  for (const step of pending) counts.set(step.tool || "", (counts.get(step.tool || "") || 0) + 1);
  const label = [...counts].map(([tool, n]) => `${toolLabel(tool, t)}${n > 1 ? ` ×${n}` : ""}`).join("、");

  const reject = () => {
    onRejectAll(note.trim());
    setRejecting(false);
    setNote("");
  };

  return (
    <div className="mb-2 animate-slide-up rounded-xl border border-amber-200 bg-amber-50/90 px-3 py-2 shadow-sm backdrop-blur dark:border-amber-500/25 dark:bg-amber-500/10">
      <div className="flex items-center gap-3">
        <button onClick={onJump} className="flex min-w-0 flex-1 items-center gap-2.5 text-left" title={t("approval.jump")}>
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300">
            <Icon name={pending.length ? "pause" : "users"} className="h-3.5 w-3.5" />
          </span>
          <span className="min-w-0 text-xs">
            <span className="font-medium text-amber-900 dark:text-amber-100">
              {pending.length ? t("approval.summary", { count: pending.length }) : t("approval.selectHint")}
            </span>
            {pending.length > 0 && <span className="ml-2 truncate text-amber-800/70 dark:text-amber-200/70">{label}</span>}
          </span>
        </button>
        {pending.length > 0 && (
          <>
            <button onClick={onApproveAll} disabled={busy} className="btn-primary shrink-0">
              <Icon name="play" className="h-3 w-3" />{pending.length > 1 ? t("approval.approveAll", { count: pending.length }) : t("approval.approve")}
            </button>
            <button onClick={() => setRejecting(!rejecting)} disabled={busy} className="btn-ghost shrink-0 text-amber-800 dark:text-amber-200">
              {t("approval.reject")}
            </button>
          </>
        )}
        {!pending.length && waitingInput && (
          <button onClick={onJump} className="btn-secondary shrink-0">{t("approval.jump")}</button>
        )}
      </div>
      {rejecting && (
        <div className="mt-2 flex gap-2">
          <input
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !composingRef.current && !e.nativeEvent.isComposing) {
                e.preventDefault();
                reject();
              }
              if (e.key === "Escape") setRejecting(false);
            }}
            placeholder={t("approval.notePlaceholder")}
            className="field min-w-0 flex-1"
          />
          <button onClick={reject} disabled={busy} className="btn-secondary">{t("approval.rejectAll")}</button>
        </div>
      )}
    </div>
  );
}
