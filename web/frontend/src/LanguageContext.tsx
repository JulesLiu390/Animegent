import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { t as translate, type Lang } from "./i18n";

interface LanguageContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  dark: boolean;
  setDark: (dark: boolean) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue>({
  lang: "zh",
  setLang: () => {},
  dark: false,
  setDark: () => {},
  t: (key) => key,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = localStorage.getItem("anidaily-lang");
    return (saved === "en" || saved === "zh") ? saved : "zh";
  });

  const [dark, setDarkState] = useState(() => {
    const saved = localStorage.getItem("anidaily-dark");
    if (saved !== null) return saved === "true";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem("anidaily-lang", l);
  }, []);

  const setDark = useCallback((d: boolean) => {
    setDarkState(d);
    localStorage.setItem("anidaily-dark", String(d));
  }, []);

  // Sync dark class on <html>
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

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

export function useLang() {
  return useContext(LanguageContext);
}
