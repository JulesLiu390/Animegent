import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { ToastContext, type ToastKind } from "../hooks";
import Icon from "./Icon";

interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

const STYLES: Record<ToastKind, { icon: "check" | "alert-circle" | "info"; className: string }> = {
  success: { icon: "check", className: "text-emerald-500" },
  error: { icon: "alert-circle", className: "text-red-500" },
  info: { icon: "info", className: "text-brand-500" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => setItems((prev) => prev.filter((i) => i.id !== id)), []);

  const toast = useCallback((message: string, kind: ToastKind = "info") => {
    const id = ++counter.current;
    setItems((prev) => [...prev.slice(-3), { id, message, kind }]);
    window.setTimeout(() => dismiss(id), kind === "error" ? 6000 : 2600);
  }, [dismiss]);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-14 z-[80] flex flex-col items-center gap-2 px-4">
        {items.map((item) => {
          const style = STYLES[item.kind];
          return (
            <div
              key={item.id}
              role="status"
              className="pointer-events-auto flex max-w-md animate-pop-in items-start gap-2.5 rounded-xl border border-zinc-200 bg-white/95 px-3.5 py-2.5 text-sm text-zinc-800 shadow-pop backdrop-blur dark:border-zinc-700 dark:bg-zinc-800/95 dark:text-zinc-100"
            >
              <Icon name={style.icon} className={`mt-0.5 h-4 w-4 ${style.className}`} />
              <span className="min-w-0 break-words">{item.message}</span>
              <button onClick={() => dismiss(item.id)} className="-mr-1 ml-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
                <Icon name="x" className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
