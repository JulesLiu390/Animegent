import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { LightboxContext, useLang, type LightboxItem } from "../hooks";
import Icon from "./Icon";

export function LightboxProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ items: LightboxItem[]; index: number } | null>(null);
  const open = useCallback((items: LightboxItem[], index = 0) => {
    if (items.length > 0) setState({ items, index: Math.min(Math.max(index, 0), items.length - 1) });
  }, []);
  const value = useMemo(() => ({ open }), [open]);

  return (
    <LightboxContext.Provider value={value}>
      {children}
      {state && <Viewer items={state.items} index={state.index} onIndex={(index) => setState({ ...state, index })} onClose={() => setState(null)} />}
    </LightboxContext.Provider>
  );
}

function Viewer({ items, index, onIndex, onClose }: {
  items: LightboxItem[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const { t } = useLang();
  const item = items[index];
  const many = items.length > 1;
  const go = useCallback((delta: number) => onIndex((index + delta + items.length) % items.length), [index, items.length, onIndex]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && many) go(1);
      else if (e.key === "ArrowLeft" && many) go(-1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [go, many, onClose]);

  const name = item.name || decodeURIComponent(item.url.split("?")[0].split("/").pop() || "");

  return (
    <div className="fixed inset-0 z-[70] flex animate-fade-in flex-col bg-zinc-950/90 backdrop-blur-sm" onClick={onClose}>
      <div className="flex shrink-0 items-center gap-2 px-4 py-3 text-zinc-200" onClick={(e) => e.stopPropagation()}>
        <div className="min-w-0 flex-1 truncate text-sm font-medium">
          {name}
          {many && <span className="ml-2 text-xs text-zinc-400">{index + 1} / {items.length}</span>}
        </div>
        <a href={item.url} target="_blank" rel="noopener noreferrer" title={t("common.openNewTab")} className="icon-btn text-zinc-300 hover:bg-white/10 hover:text-white">
          <Icon name="external-link" />
        </a>
        <a href={item.url} download={name} title={t("common.download")} className="icon-btn text-zinc-300 hover:bg-white/10 hover:text-white">
          <Icon name="download" />
        </a>
        <button onClick={onClose} title={t("common.close")} className="icon-btn text-zinc-300 hover:bg-white/10 hover:text-white">
          <Icon name="x" className="h-5 w-5" />
        </button>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center px-4 pb-4">
        {item.video ? (
          <video key={item.url} src={item.url} controls autoPlay className="max-h-full max-w-full rounded-lg shadow-2xl" onClick={(e) => e.stopPropagation()} />
        ) : (
          <img key={item.url} src={item.url} alt={name} className="max-h-full max-w-full animate-fade-in rounded-lg object-contain shadow-2xl" onClick={(e) => e.stopPropagation()} />
        )}
        {many && (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); go(-1); }}
              className="absolute left-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20"
            >
              <Icon name="chevron-left" className="h-5 w-5" />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); go(1); }}
              className="absolute right-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20"
            >
              <Icon name="chevron-right" className="h-5 w-5" />
            </button>
          </>
        )}
      </div>

      {many && items.length <= 40 && (
        <div className="flex shrink-0 justify-center gap-1.5 overflow-x-auto px-4 pb-4" onClick={(e) => e.stopPropagation()}>
          {items.map((it, i) => (
            <button
              key={`${it.url}-${i}`}
              onClick={() => onIndex(i)}
              className={`h-12 w-12 shrink-0 overflow-hidden rounded-md border-2 transition-all ${i === index ? "border-brand-400" : "border-transparent opacity-50 hover:opacity-90"}`}
            >
              {it.video ? (
                <div className="flex h-full w-full items-center justify-center bg-zinc-800 text-zinc-300"><Icon name="play" className="h-4 w-4" /></div>
              ) : (
                <img src={it.url} alt="" className="h-full w-full object-cover" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
