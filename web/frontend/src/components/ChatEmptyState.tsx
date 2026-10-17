import type { CreationMode } from "../api";
import { useLang } from "../hooks";
import type { IconName } from "./Icon";
import Icon from "./Icon";

interface Props {
  mode: CreationMode;
  onSuggestion: (text: string) => void;
}

const SUGGESTIONS: Record<CreationMode, { key: string; icon: IconName }[]> = {
  comic: [
    { key: "chat.suggest.photo", icon: "scan-face" },
    { key: "chat.suggest.comic", icon: "panels" },
    { key: "chat.suggest.character", icon: "sparkles" },
    { key: "chat.suggest.scene", icon: "image" },
  ],
  storyboard: [
    { key: "chat.suggest.storyboard", icon: "film" },
    { key: "chat.suggest.photo", icon: "scan-face" },
    { key: "chat.suggest.character", icon: "sparkles" },
    { key: "chat.suggest.scene", icon: "image" },
  ],
};

export default function ChatEmptyState({ mode, onSuggestion }: Props) {
  const { t } = useLang();
  return (
    <div className="flex flex-col items-center text-center">
      <div className="relative mb-5 h-36 w-36">
        <div className="absolute inset-0 rounded-full bg-gradient-to-br from-brand-200 via-fuchsia-100 to-sky-100 opacity-80 blur-2xl dark:from-brand-500/30 dark:via-fuchsia-500/10 dark:to-sky-500/20" />
        <div className="relative h-full w-full overflow-hidden rounded-full border border-white/60 bg-gradient-to-br from-brand-50 to-sky-50 shadow-soft dark:border-white/10">
          <img src="/hero-512.png" alt="" className="h-full w-full scale-110 object-cover mix-blend-multiply" />
        </div>
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{t("chat.emptyTitle")}</h2>
      <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">{t("chat.emptySubtitle")}</p>
      <div className="mt-6 grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS[mode].map((s) => (
          <button
            key={s.key}
            onClick={() => onSuggestion(t(s.key))}
            className="group flex items-center gap-2.5 rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-left text-[13px] text-zinc-600 transition-all hover:-translate-y-px hover:border-brand-300 hover:text-zinc-900 hover:shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-brand-500/40 dark:hover:text-zinc-50"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 transition-colors group-hover:bg-brand-50 group-hover:text-brand-500 dark:bg-zinc-800 dark:group-hover:bg-brand-500/10">
              <Icon name={s.icon} className="h-4 w-4" />
            </span>
            <span className="min-w-0">{t(s.key)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
