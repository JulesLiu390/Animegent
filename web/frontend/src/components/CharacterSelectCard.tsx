import { useMemo, useState, type ReactNode } from "react";
import type { CharacterOption, SelectionState } from "../api";
import { getFileUrl } from "../api";
import { useLang, useLightbox } from "../hooks";
import Icon from "./Icon";

interface Props {
  options: CharacterOption[];
  selection?: SelectionState;
  /** 只读：旧版本保存的、已经过时的选择卡片 */
  interactive: boolean;
  busy: boolean;
  onConfirm: (selected: CharacterOption[]) => void;
}

function groupByFace(items: CharacterOption[]) {
  const groups: Record<string, CharacterOption[]> = {};
  for (const opt of items) {
    (groups[opt.source_face || "__none__"] ??= []).push(opt);
  }
  return groups;
}

const displayName = (opt: { label?: string; name: string }) => opt.label || opt.name;

export default function CharacterSelectCard({ options, selection, interactive, busy, onConfirm }: Props) {
  const { t } = useLang();
  const openLightbox = useLightbox();
  const [slots, setSlots] = useState<CharacterOption[]>(() => options.filter((o) => o.selected));
  const [pickingSlot, setPickingSlot] = useState<number | null>(null);

  const selectedPaths = new Set(slots.map((s) => s.path));
  const available = options.filter((o) => !selectedPaths.has(o.path));
  const availableChars = available.filter((o) => o.category === "characters");
  const availableFaces = available.filter((o) => o.category === "faces");
  const charGroups = groupByFace(availableChars);
  const faceByFilename = useMemo(() => {
    const map: Record<string, CharacterOption> = {};
    for (const o of options) if (o.category === "faces") map[o.filename] = o;
    return map;
  }, [options]);

  const header = (title: string, hint?: string, done?: boolean) => (
    <div className="mb-2.5 flex items-center gap-2">
      <span className={`flex h-6 w-6 items-center justify-center rounded-md ${done ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400" : "bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400"}`}>
        <Icon name={done ? "check" : "users"} className="h-3.5 w-3.5" />
      </span>
      <span className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-100">{title}</span>
      {hint && <span className="truncate text-[11px] text-zinc-400">{hint}</span>}
    </div>
  );

  const avatarRow = (items: { path: string; url: string; name: string; label?: string }[]) => (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <div key={item.path} className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 py-1 pl-1 pr-2.5 dark:border-zinc-700 dark:bg-zinc-800/60">
          <img src={getFileUrl(item.url)} alt="" className="h-8 w-8 rounded-md object-cover object-top" />
          <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200">{displayName(item)}</span>
        </div>
      ))}
    </div>
  );

  const card = (children: ReactNode) => (
    <div className="rounded-xl border border-zinc-200 bg-white p-3.5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/70">{children}</div>
  );

  if (selection?.confirmed) {
    return card(<>{header(t("char.confirmed", { count: selection.items.length }), undefined, true)}{avatarRow(selection.items)}</>);
  }

  if (!interactive) {
    const pre = options.filter((o) => o.selected);
    return card(<>{header(t("char.expired"))}{pre.length > 0 ? avatarRow(pre) : <div className="text-xs text-zinc-400">—</div>}</>);
  }

  if (options.length === 0) {
    return card(<>{header(t("char.instruction"))}<div className="text-xs text-zinc-500 dark:text-zinc-400">{t("char.none")}</div></>);
  }

  const pick = (opt: CharacterOption) => {
    if (pickingSlot !== null && pickingSlot < slots.length) {
      setSlots((prev) => prev.map((s, i) => (i === pickingSlot ? opt : s)));
    } else {
      setSlots((prev) => [...prev, opt]);
    }
    setPickingSlot(null);
  };

  const removeSlot = (index: number) => {
    setSlots((prev) => prev.filter((_, i) => i !== index));
    if (pickingSlot === index) setPickingSlot(null);
  };

  const optionButton = (opt: CharacterOption) => (
    <button
      key={opt.path}
      onClick={() => pick(opt)}
      title={opt.description || opt.name}
      className="group w-[72px] text-left"
    >
      <div className="aspect-[3/4] overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50 transition-colors group-hover:border-brand-400 dark:border-zinc-700 dark:bg-zinc-800">
        <img src={getFileUrl(opt.url)} alt="" loading="lazy" className="h-full w-full object-cover object-top" />
      </div>
      <div className="mt-1 truncate text-[11px] text-zinc-600 dark:text-zinc-300">{opt.name}</div>
    </button>
  );

  const groupKeys = Object.keys(charGroups).filter((k) => k !== "__none__");
  const ungrouped = charGroups["__none__"] || [];

  return card(
    <>
      {header(t("char.instruction"), t("char.instructionHint"))}

      <div className="flex flex-wrap gap-2.5">
        {slots.map((opt, i) => (
          <div key={`${opt.path}-${i}`} className="group relative w-[84px]">
            <button
              onClick={() => setPickingSlot(pickingSlot === i ? null : i)}
              onDoubleClick={() => openLightbox([{ url: getFileUrl(opt.url), name: displayName(opt) }])}
              className={`block w-full overflow-hidden rounded-lg border-2 bg-zinc-50 transition-colors dark:bg-zinc-800 ${
                pickingSlot === i ? "border-brand-500" : "border-transparent ring-1 ring-zinc-200 hover:ring-brand-300 dark:ring-zinc-700"
              }`}
            >
              <img src={getFileUrl(opt.url)} alt="" className="aspect-[3/4] w-full object-cover object-top" />
            </button>
            <div className="mt-1 truncate text-center text-[11px] font-medium text-zinc-700 dark:text-zinc-200" title={displayName(opt)}>
              {displayName(opt)}
            </div>
            <div className="truncate text-center text-[10px] text-zinc-400">
              {opt.category === "characters" ? t("char.categoryChar") : t("char.categoryFace")}
            </div>
            <button
              onClick={() => removeSlot(i)}
              className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-700 text-white opacity-0 shadow transition-opacity hover:bg-red-500 group-hover:opacity-100"
            >
              <Icon name="x" className="h-3 w-3" strokeWidth={3} />
            </button>
          </div>
        ))}

        {available.length > 0 && (
          <button
            onClick={() => setPickingSlot(pickingSlot === slots.length ? null : slots.length)}
            className={`flex aspect-[3/4] w-[84px] flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed text-xs transition-colors ${
              pickingSlot === slots.length
                ? "border-brand-400 bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300"
                : "border-zinc-200 text-zinc-400 hover:border-brand-300 hover:text-brand-500 dark:border-zinc-700"
            }`}
          >
            <Icon name="plus" className="h-4 w-4" />
            {t("common.add")}
          </button>
        )}
      </div>

      {pickingSlot !== null && (
        <div className="mt-3 max-h-72 space-y-3 overflow-y-auto rounded-lg border border-zinc-200 bg-zinc-50/70 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40">
          {groupKeys.map((faceFile) => {
            const faceOpt = faceByFilename[faceFile];
            const chars = charGroups[faceFile];
            return (
              <div key={faceFile}>
                <div className="mb-1.5 flex items-center gap-1.5">
                  {faceOpt && <img src={getFileUrl(faceOpt.url)} alt="" className="h-5 w-5 rounded-full object-cover" />}
                  <span className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400">
                    {faceOpt?.name || faceFile}
                    <span className="ml-1 text-zinc-400">· {t("char.variants", { count: chars.length })}</span>
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">{chars.map(optionButton)}</div>
              </div>
            );
          })}
          {ungrouped.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-zinc-500 dark:text-zinc-400">{t("char.characters")}</div>
              <div className="flex flex-wrap gap-2">{ungrouped.map(optionButton)}</div>
            </div>
          )}
          {availableFaces.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-zinc-500 dark:text-zinc-400">{t("char.faces")}</div>
              <div className="flex flex-wrap gap-2">{availableFaces.map(optionButton)}</div>
            </div>
          )}
          {available.length === 0 && <div className="py-2 text-center text-xs text-zinc-400">{t("char.noMore")}</div>}
        </div>
      )}

      <div className="mt-3 flex justify-end">
        <button onClick={() => onConfirm(slots)} disabled={slots.length === 0 || busy} className="btn-primary">
          <Icon name="check" className="h-3.5 w-3.5" />
          {t("char.confirmSelection", { count: slots.length })}
        </button>
      </div>
    </>,
  );
}
