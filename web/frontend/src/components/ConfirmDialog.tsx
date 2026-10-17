import { useLang } from "../hooks";
import Icon from "./Icon";
import Modal from "./Modal";

interface Props {
  title?: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({ title, message, confirmLabel, danger = true, onConfirm, onCancel }: Props) {
  const { t } = useLang();
  return (
    <Modal onClose={onCancel} labelledBy="confirm-title">
      <div className="p-5">
        <div className="flex gap-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${danger ? "bg-red-50 text-red-500 dark:bg-red-500/10" : "bg-brand-50 text-brand-500 dark:bg-brand-500/10"}`}>
            <Icon name={danger ? "alert-triangle" : "info"} className="h-[18px] w-[18px]" />
          </div>
          <div className="min-w-0 pt-0.5">
            {title && <h3 id="confirm-title" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>}
            <p className={`text-sm leading-relaxed text-zinc-600 dark:text-zinc-300 ${title ? "mt-1" : ""}`}>{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="btn-secondary px-4">{t("common.cancel")}</button>
          <button data-autofocus onClick={onConfirm} className={`${danger ? "btn-danger" : "btn-primary"} px-4`}>
            {confirmLabel || t("common.confirm")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
