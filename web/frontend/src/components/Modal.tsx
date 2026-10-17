import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  onClose: () => void;
  children: ReactNode;
  className?: string;
  /** 点遮罩是否关闭（有未保存内容的弹窗可以关掉） */
  closeOnBackdrop?: boolean;
  labelledBy?: string;
}

/** 居中的弹窗：Esc 关闭，打开时把焦点移进弹窗。 */
export default function Modal({ onClose, children, className = "max-w-sm", closeOnBackdrop = true, labelledBy }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; });

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const focusable = ref.current?.querySelector<HTMLElement>("[autofocus], [data-autofocus], input, textarea, button");
    focusable?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      previous?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[60] flex animate-fade-in items-center justify-center bg-zinc-950/40 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => { if (closeOnBackdrop && e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={`w-full animate-pop-in rounded-2xl border border-zinc-200 bg-white shadow-pop dark:border-zinc-700/80 dark:bg-zinc-900 ${className}`}
      >
        {children}
      </div>
    </div>
  );
}
