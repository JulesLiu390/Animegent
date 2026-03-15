import { useLang } from "../LanguageContext";

export type InteractionMode = "ask" | "edit" | "plan";

interface Props {
  mode: InteractionMode;
  onChange: (mode: InteractionMode) => void;
  disabled?: boolean;
}

export default function InteractionModeSelector({ mode, onChange, disabled }: Props) {
  const { t } = useLang();
  const options: { value: InteractionMode; label: string }[] = [
    { value: "ask", label: t("interaction.ask") },
    { value: "edit", label: t("interaction.edit") },
    { value: "plan", label: t("interaction.plan") },
  ];

  return (
    <div className="flex items-center bg-gray-100 dark:bg-gray-700 rounded-md p-0.5 text-[11px]">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          disabled={disabled}
          className={`px-2 py-0.5 rounded transition-colors ${
            mode === opt.value
              ? "bg-white dark:bg-gray-600 text-gray-800 dark:text-gray-100 shadow-sm font-medium"
              : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          } disabled:opacity-50`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
