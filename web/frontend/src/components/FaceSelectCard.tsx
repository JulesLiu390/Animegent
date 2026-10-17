import { useState } from "react";
import type { FaceInfo, SelectionState } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../hooks";
import Icon from "./Icon";

interface Props {
  faces: FaceInfo[];
  selection?: SelectionState;
  interactive: boolean;
  busy: boolean;
  onConfirm: (selected: FaceInfo[]) => void;
  onSkip: () => void;
}

export default function FaceSelectCard({ faces, selection, interactive, busy, onConfirm, onSkip }: Props) {
  const { t } = useLang();
  const [selected, setSelected] = useState<Set<number>>(() => new Set(faces.map((f) => f.index)));

  const toggle = (index: number) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    return next;
  });

  const header = (title: string, done?: boolean) => (
    <div className="mb-2.5 flex items-center gap-2">
      <span className={`flex h-6 w-6 items-center justify-center rounded-md ${done ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" : "bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400"}`}>
        <Icon name={done ? "check" : "smile"} className="h-3.5 w-3.5" />
      </span>
      <span className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-100">{title}</span>
    </div>
  );

  const shell = "rounded-xl border border-zinc-200 bg-white p-3.5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/70";

  if (selection?.confirmed) {
    return (
      <div className={shell}>
        {header(selection.skipped ? t("face.skipped") : t("face.confirmedCount", { count: selection.items.length }), true)}
        {!selection.skipped && (
          <div className="flex flex-wrap gap-1.5">
            {selection.items.map((item) => (
              <img key={item.path} src={getFileUrl(item.url)} alt={item.name} title={item.name} className="h-10 w-10 rounded-lg object-cover" />
            ))}
          </div>
        )}
      </div>
    );
  }

  if (faces.length === 0) {
    return <div className={shell}>{header(t("face.detected", { count: 0 }))}<div className="text-xs text-zinc-500 dark:text-zinc-400">{t("face.none")}</div></div>;
  }

  const disabled = !interactive || busy;
  const genderText = (face: FaceInfo) =>
    [face.gender === "M" ? t("face.male") : face.gender === "F" ? t("face.female") : "", face.age ? t("face.age", { age: face.age }) : ""]
      .filter(Boolean).join(" · ");

  return (
    <div className={shell}>
      {header(t("face.detected", { count: faces.length }))}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-2">
        {faces.map((face) => {
          const isSelected = selected.has(face.index);
          return (
            <button
              key={face.index}
              onClick={() => toggle(face.index)}
              disabled={disabled}
              title={face.description || face.name}
              className="group text-left disabled:cursor-default"
            >
              <div className={`relative aspect-square overflow-hidden rounded-lg border-2 transition-colors ${isSelected ? "border-brand-500" : "border-transparent ring-1 ring-zinc-200 dark:ring-zinc-700"}`}>
                <img src={getFileUrl(face.crop_url)} alt="" loading="lazy" className={`h-full w-full object-cover transition-opacity ${isSelected ? "" : "opacity-60"}`} />
                <span className={`absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full border shadow-sm transition-colors ${
                  isSelected ? "border-brand-500 bg-brand-500 text-white" : "border-white/80 bg-black/20"
                }`}>
                  {isSelected && <Icon name="check" className="h-2.5 w-2.5" strokeWidth={3.5} />}
                </span>
              </div>
              <div className="mt-1 truncate text-[11px] font-medium text-zinc-700 dark:text-zinc-200">{face.name}</div>
              {genderText(face) && <div className="truncate text-[10px] text-zinc-400">{genderText(face)}</div>}
            </button>
          );
        })}
      </div>

      {interactive && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button onClick={() => onConfirm(faces.filter((f) => selected.has(f.index)))} disabled={selected.size === 0 || busy} className="btn-primary">
            <Icon name="wand" className="h-3.5 w-3.5" />
            {t("face.stylizeSelected", { count: selected.size })}
          </button>
          <button onClick={onSkip} disabled={busy} className="btn-secondary">{t("common.skip")}</button>
          {faces.length > 1 && (
            <>
              <span className="flex-1" />
              <button onClick={() => setSelected(new Set(faces.map((f) => f.index)))} disabled={busy} className="text-xs text-brand-600 hover:underline dark:text-brand-400">{t("face.selectAll")}</button>
              <button onClick={() => setSelected(new Set())} disabled={busy} className="text-xs text-zinc-400 hover:underline">{t("face.deselectAll")}</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
