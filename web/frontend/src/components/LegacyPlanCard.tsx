import { useState } from "react";
import type { LegacyPlan } from "../api";
import { useLang } from "../hooks";
import Icon from "./Icon";

/** 旧版对话里的任务计划：现在已经没有计划这一步了，只读显示，默认收起。 */
export default function LegacyPlanCard({ plan }: { plan: LegacyPlan }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const steps = plan.steps || [];

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/70">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          <Icon name="list-checks" className="h-3.5 w-3.5" />
        </span>
        <span className="text-[13px] font-medium text-zinc-800 dark:text-zinc-100">{t("plan.title")}</span>
        <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{t("plan.legacy")}</span>
        <span className="flex-1" />
        <span className="text-[11px] tabular-nums text-zinc-400">{t("plan.steps", { count: steps.length })}</span>
        <Icon name="chevron-down" className={`h-3.5 w-3.5 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ol className="space-y-1 px-3.5 pb-3">
          {steps.map((step) => (
            <li key={step.id} className={`flex items-start gap-2 text-[13px] leading-snug ${step.status === "skipped" ? "opacity-45" : ""}`}>
              <span className="mt-px tabular-nums text-zinc-400">{step.id}.</span>
              <span className="min-w-0 flex-1 text-zinc-600 dark:text-zinc-300">{step.label}</span>
              {step.status === "done" && <Icon name="check" className="mt-0.5 h-3.5 w-3.5 text-emerald-500" />}
              {step.status === "failed" && <Icon name="x" className="mt-0.5 h-3.5 w-3.5 text-red-500" />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
