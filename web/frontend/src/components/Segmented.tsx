import type { IconName } from "./Icon";
import Icon from "./Icon";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
  title?: string;
}

interface Props<T extends string> {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  label?: string;
}

/** 分段选择器（创作模式、执行方式等）。 */
export default function Segmented<T extends string>({ value, options, onChange, disabled, label }: Props<T>) {
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center rounded-lg bg-zinc-100 p-0.5 dark:bg-zinc-800">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={opt.title}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
              active
                ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-700 dark:text-zinc-50"
                : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
            }`}
          >
            {opt.icon && <Icon name={opt.icon} className="h-3.5 w-3.5" />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
