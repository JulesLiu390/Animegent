import { useState, useCallback, useEffect, type ReactNode } from "react";
import { t as translate, type Lang } from "./i18n";
import { LanguageContext } from "./hooks";
import { readStorage, writeStorage } from "./lib/storage";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = readStorage("anidaily-lang");
    return (saved === "en" || saved === "zh") ? saved : "zh";
  });

  const [dark, setDarkState] = useState(() => {
    const saved = readStorage("anidaily-dark");
    if (saved !== null) return saved === "true";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    writeStorage("anidaily-lang", l);
  }, []);

  const setDark = useCallback((d: boolean) => {
    setDarkState(d);
    writeStorage("anidaily-dark", String(d));
  }, []);

  // Sync dark class / lang on <html>
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  }, [lang]);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translate(key, lang, params),
    [lang]
  );

  return (
    <LanguageContext.Provider value={{ lang, setLang, dark, setDark, t }}>
      {children}
    </LanguageContext.Provider>
  );
}
