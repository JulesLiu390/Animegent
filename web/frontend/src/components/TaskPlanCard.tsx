import { useRef, useState } from "react";
import type { PlanStep } from "../api";
import { useLang } from "../LanguageContext";

interface Props {
  steps: PlanStep[];
  onConfirm: (steps: PlanStep[], autoExecute: boolean) => void;
  onRevise: (prompt: string) => void;
  onContinue?: (prompt?: string) => void;
  onCancel?: () => void;
  paused?: boolean;
  disabled?: boolean;
}

export default function TaskPlanCard({ steps: propSteps, onConfirm, onRevise, onContinue, onCancel, paused, disabled }: Props) {
  const { t } = useLang();
  // Local state only for the unconfirmed proposal view (checkbox toggling)
  const [localSteps] = useState<PlanStep[]>(() =>
    propSteps.map((s) => ({ ...s, status: s.status || "pending" }))
  );
  const [confirmed, setConfirmed] = useState(false);
  const [revising, setRevising] = useState(false);
  const [reviseText, setReviseText] = useState("");
  const composingRef = useRef(false);

  const [enabled, setEnabled] = useState<Set<number>>(() => new Set(localSteps.map((s) => s.id)));
  const [autoExec, setAutoExec] = useState(true);

  // In confirmed view, use props (live-updated by parent from SSE events)
  // In proposal view, use localSteps (user can toggle checkboxes)
  const steps = confirmed ? propSteps : localSteps;

  const toggleStep = (id: number) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirm = () => {
    setConfirmed(true);
    const finalSteps = localSteps.map((s) => ({
      ...s,
      status: enabled.has(s.id) ? "pending" as const : "skipped" as const,
    }));
    onConfirm(finalSteps, autoExec);
  };

  const handleReviseSubmit = () => {
    const text = reviseText.trim();
    if (!text) return;
    setConfirmed(true);
    onRevise(text);
  };

  const [gateRevising, setGateRevising] = useState(false);
  const [gateReviseText, setGateReviseText] = useState("");
  const gateComposingRef = useRef(false);

  const handleGateContinue = () => {
    const text = gateReviseText.trim();
    setGateRevising(false);
    setGateReviseText("");
    onContinue?.(text || undefined);
  };

  if (confirmed) {
    const nextPendingStep = steps.find((s) => s.status === "pending");

    const totalActive = steps.filter((s) => s.status !== "skipped" && enabled.has(s.id)).length;
    const doneCount = steps.filter((s) => s.status === "done" && enabled.has(s.id)).length;
    const progress = totalActive > 0 ? Math.round((doneCount / totalActive) * 100) : 0;

    return (
      <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-3 my-2">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-medium text-gray-600 dark:text-gray-300">{t("plan.title")}</div>
          <div className="text-[10px] text-gray-400 dark:text-gray-500">{doneCount}/{totalActive}</div>
        </div>
        <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full mb-2 overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="space-y-1">
          {steps.map((step) => {
            const isSkipped = step.status === "skipped" || !enabled.has(step.id);
            const isDone = step.status === "done";
            const isActive = step.status === "active";
            return (
              <div key={step.id} className={`flex items-center gap-2 text-xs ${isSkipped ? "opacity-40" : ""}`}>
                <span className="w-4 text-center flex-shrink-0">
                  {isDone ? (
                    <span className="text-green-500">✓</span>
                  ) : isActive ? (
                    <span className="inline-block w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  ) : isSkipped ? (
                    <span className="text-gray-300 dark:text-gray-600">—</span>
                  ) : (
                    <span className="text-gray-300 dark:text-gray-600">○</span>
                  )}
                </span>
                <span className={`${isDone ? "text-gray-500 dark:text-gray-400" : isActive ? "text-blue-600 dark:text-blue-400 font-medium" : "text-gray-500 dark:text-gray-400"}`}>
                  {step.label}
                </span>
                {step.needs_confirm && !isSkipped && !isDone && (
                  <span className="text-[10px] text-blue-400 bg-blue-50 px-1 rounded">{t("plan.needsConfirm")}</span>
                )}
              </div>
            );
          })}
        </div>

        {paused && nextPendingStep && (
          <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
            <div className="text-xs text-blue-600 font-medium mb-2">
              {t("plan.nextStep")}{nextPendingStep.label}
            </div>

            {gateRevising && (
              <div className="mb-2 flex gap-2">
                <input
                  type="text"
                  value={gateReviseText}
                  onChange={(e) => setGateReviseText(e.target.value)}
                  onCompositionStart={() => { gateComposingRef.current = true; }}
                  onCompositionEnd={() => { gateComposingRef.current = false; }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !gateComposingRef.current) {
                      e.preventDefault();
                      handleGateContinue();
                    }
                  }}
                  placeholder={t("plan.instructionPlaceholder")}
                  className="flex-1 px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 dark:bg-gray-700 dark:text-gray-200"
                  autoFocus
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => gateRevising ? handleGateContinue() : onContinue?.()}
                disabled={disabled}
                className="flex-1 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 transition-colors"
              >
                {gateRevising && gateReviseText.trim() ? t("plan.sendAndContinue") : t("plan.continue")}
              </button>
              <button
                onClick={() => { setGateRevising(false); setGateReviseText(""); onCancel?.(); }}
                disabled={disabled}
                className="px-3 py-1.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-xs font-medium rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-30 transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={() => setGateRevising(!gateRevising)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  gateRevising ? "bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-400" : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                }`}
              >
                {t("plan.addInstruction")}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 my-2">
      <div className="text-xs font-medium text-blue-600 mb-2">{t("plan.proposalTitle")}</div>
      <div className="space-y-1 mb-3">
        {steps.map((step) => {
          const isEnabled = enabled.has(step.id);
          return (
            <button
              key={step.id}
              onClick={() => toggleStep(step.id)}
              className={`w-full flex items-center gap-2 text-xs text-left px-2 py-1.5 rounded-lg transition-colors ${
                isEnabled ? "bg-white dark:bg-gray-800 border border-blue-200 dark:border-blue-700" : "bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 opacity-50"
              }`}
            >
              <div className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${
                isEnabled ? "bg-blue-500 border-blue-500 text-white" : "border-gray-300 dark:border-gray-600"
              }`}>
                {isEnabled && <span className="text-[10px]">✓</span>}
              </div>
              <span className="text-gray-700 dark:text-gray-200">{step.id}. {step.label}</span>
              {step.needs_confirm && (
                <span className="text-[10px] text-blue-400 bg-blue-50 px-1 rounded ml-auto">{t("plan.needsConfirm")}</span>
              )}
            </button>
          );
        })}
      </div>

      {revising && (
        <div className="mb-3 flex gap-2">
          <input
            type="text"
            value={reviseText}
            onChange={(e) => setReviseText(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !composingRef.current) {
                e.preventDefault();
                handleReviseSubmit();
              }
            }}
            placeholder={t("plan.revisePlaceholder")}
            className="flex-1 px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 dark:bg-gray-700 dark:text-gray-200"
            autoFocus
          />
          <button
            onClick={handleReviseSubmit}
            disabled={!reviseText.trim()}
            className="px-3 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 transition-colors"
          >
            {t("common.send")}
          </button>
        </div>
      )}

      <div className="flex gap-2 items-center">
        <button
          onClick={handleConfirm}
          disabled={enabled.size === 0 || disabled}
          className="flex-1 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 transition-colors"
        >
          {t("plan.execute")} ({enabled.size} {t("plan.steps")})
        </button>
        <label className="flex items-center gap-1 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoExec}
            onChange={(e) => setAutoExec(e.target.checked)}
            className="w-3.5 h-3.5 rounded border-gray-300 text-blue-500 focus:ring-blue-400"
          />
          <span className="text-[10px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{t("plan.autoExecute")}</span>
        </label>
        <button
          onClick={() => setRevising(!revising)}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
            revising ? "bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-400" : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
          }`}
        >
          {t("plan.modifyPlan")}
        </button>
      </div>
    </div>
  );
}
