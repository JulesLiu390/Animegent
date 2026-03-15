import { useLang } from "../LanguageContext";

interface Props {
  mode: "comic" | "storyboard";
  onChange: (mode: "comic" | "storyboard") => void;
  disabled?: boolean;
}

export default function ModeSelector({ mode, onChange, disabled }: Props) {
  const { t } = useLang();
  return (
    <div className="flex items-center bg-gray-100 dark:bg-gray-700 rounded-md p-0.5 text-[11px]">
      <button
        onClick={() => onChange("comic")}
        disabled={disabled}
        className={`px-2 py-0.5 rounded transition-colors ${
          mode === "comic"
            ? "bg-white dark:bg-gray-600 text-gray-800 dark:text-gray-100 shadow-sm font-medium"
            : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        } disabled:opacity-50`}
      >
        {t("mode.comic")}
      </button>
      <button
        onClick={() => onChange("storyboard")}
        disabled={disabled}
        className={`px-2 py-0.5 rounded transition-colors ${
          mode === "storyboard"
            ? "bg-white dark:bg-gray-600 text-gray-800 dark:text-gray-100 shadow-sm font-medium"
            : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        } disabled:opacity-50`}
      >
        {t("mode.storyboard")}
      </button>
    </div>
  );
}
