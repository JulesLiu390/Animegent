import { createContext, useContext, useEffect, useState } from "react";
import type { Lang } from "./i18n";

// ---- 语言 / 深色模式 ----

export interface LanguageContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  dark: boolean;
  setDark: (dark: boolean) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

export const LanguageContext = createContext<LanguageContextValue>({
  lang: "zh",
  setLang: () => {},
  dark: false,
  setDark: () => {},
  t: (key) => key,
});

export function useLang() {
  return useContext(LanguageContext);
}

// ---- 轻提示 ----

export type ToastKind = "success" | "error" | "info";

export interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void;
}

export const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext).toast;
}

// ---- 大图查看 ----

export interface LightboxItem {
  url: string;   // 可以直接使用的 URL
  name?: string;
  video?: boolean;
}

export interface LightboxContextValue {
  open: (items: LightboxItem[], index?: number) => void;
}

export const LightboxContext = createContext<LightboxContextValue>({ open: () => {} });

export function useLightbox() {
  return useContext(LightboxContext).open;
}

// ---- 计时 ----

/** 每隔 interval 毫秒刷新一次的当前时间（只在 active 时计时）。 */
export function useNow(active: boolean, interval = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), interval);
    return () => window.clearInterval(id);
  }, [active, interval]);
  return now;
}
