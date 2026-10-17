import { useState } from "react";
import { useLang } from "../hooks";
import Modal from "./Modal";

interface Props {
  title: string;
  initialValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  onConfirm: (value: string) => void | Promise<void>;
  onCancel: () => void;
}

/** 输入一行文字的弹窗（新建 / 重命名）。 */
export default function PromptDialog({ title, initialValue = "", placeholder, confirmLabel, onConfirm, onCancel }: Props) {
  const { t } = useLang();
  const [value, setValue] = useState(initialValue);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    const trimmed = value.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onConfirm(trimmed);
    } catch {
      // 出错时调用方已经提示过，弹窗保持打开方便修改
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal onClose={onCancel} labelledBy="prompt-title">
      <form className="p-5" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h3 id="prompt-title" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onFocus={(e) => e.target.select()}
          placeholder={placeholder}
          maxLength={80}
          className="field mt-3 w-full py-2 text-sm"
        />
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary px-4">{t("common.cancel")}</button>
          <button type="submit" disabled={!value.trim() || busy} className="btn-primary px-4">{confirmLabel || t("common.confirm")}</button>
        </div>
      </form>
    </Modal>
  );
}
