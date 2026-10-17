import { useState } from "react";
import { useLang } from "../hooks";
import Icon from "./Icon";

interface Props {
  align?: "start" | "end";
  onCopy?: () => void;
  onEdit?: () => void;
  onRetry?: () => void;
  onDelete?: () => void;
  disabled?: boolean;
}

/** 消息下方的操作按钮（悬停时出现）。 */
export default function MessageActions({ align = "start", onCopy, onEdit, onRetry, onDelete, disabled }: Props) {
  const { t } = useLang();
  const [copied, setCopied] = useState(false);

  const copy = () => {
    onCopy?.();
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={`mt-1 flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 ${align === "end" ? "justify-end" : ""}`}>
      {onCopy && (
        <button onClick={copy} className="icon-btn-sm" title={copied ? t("common.copied") : t("common.copy")}>
          <Icon name={copied ? "check" : "copy"} className={`h-3.5 w-3.5 ${copied ? "text-emerald-500" : ""}`} />
        </button>
      )}
      {onEdit && (
        <button onClick={onEdit} disabled={disabled} className="icon-btn-sm" title={t("common.edit")}>
          <Icon name="pencil" className="h-3.5 w-3.5" />
        </button>
      )}
      {onRetry && (
        <button onClick={onRetry} disabled={disabled} className="icon-btn-sm" title={t("common.retry")}>
          <Icon name="retry" className="h-3.5 w-3.5" />
        </button>
      )}
      {onDelete && (
        <button onClick={onDelete} disabled={disabled} className="icon-btn-sm hover:text-red-500 dark:hover:text-red-400" title={t("common.delete")}>
          <Icon name="trash" className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
