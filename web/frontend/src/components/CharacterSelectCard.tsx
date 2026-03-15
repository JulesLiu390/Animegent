import { useMemo, useState } from "react";
import type { CharacterOption } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../LanguageContext";

interface Props {
  options: CharacterOption[];
  onConfirm: (selected: CharacterOption[]) => void;
  disabled?: boolean;
}

function groupByFace(items: CharacterOption[]) {
  const groups: Record<string, CharacterOption[]> = {};
  for (const opt of items) {
    const key = opt.source_face || "__none__";
    (groups[key] ??= []).push(opt);
  }
  return groups;
}

export default function CharacterSelectCard({ options, onConfirm, disabled }: Props) {
  const { t } = useLang();
  const [slots, setSlots] = useState<CharacterOption[]>(() =>
    options.filter((o) => o.selected)
  );
  const [pickingSlot, setPickingSlot] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const selectedPaths = new Set(slots.map((s) => s.path));

  const replaceSlot = (index: number, opt: CharacterOption) => {
    setSlots((prev) => {
      const next = [...prev];
      next[index] = opt;
      return next;
    });
    setPickingSlot(null);
  };

  const removeSlot = (index: number) => {
    setSlots((prev) => prev.filter((_, i) => i !== index));
    if (pickingSlot === index) setPickingSlot(null);
  };

  const addSlot = (opt: CharacterOption) => {
    setSlots((prev) => [...prev, opt]);
    setPickingSlot(null);
  };

  const handleConfirm = () => {
    setConfirmed(true);
    onConfirm(slots);
  };

  const available = options.filter((o) => !selectedPaths.has(o.path));

  const faceByFilename = useMemo(() => {
    const map: Record<string, CharacterOption> = {};
    for (const o of options) {
      if (o.category === "faces") {
        map[o.filename] = o;
      }
    }
    return map;
  }, [options]);

  const availableChars = available.filter((o) => o.category === "characters");
  const availableFaces = available.filter((o) => o.category === "faces");
  const charGroups = useMemo(() => groupByFace(availableChars), [availableChars]);

  if (confirmed) {
    return (
      <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 rounded-xl p-3 my-2">
        <div className="text-xs text-green-600 dark:text-green-400 font-medium mb-2">
          {t("char.confirmed", { count: slots.length })}
        </div>
        <div className="flex flex-wrap gap-2">
          {slots.map((opt) => (
            <div key={opt.path} className="flex items-center gap-1.5 bg-white dark:bg-gray-800 rounded-lg px-2 py-1 border border-green-200 dark:border-green-700">
              <img src={getFileUrl(opt.url)} alt={opt.name} className="w-8 h-8 rounded object-cover" />
              <div className="text-xs font-medium text-gray-700 dark:text-gray-200">{opt.label || opt.name}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const handlePickerClick = (opt: CharacterOption) => {
    if (pickingSlot !== null && pickingSlot < slots.length) {
      replaceSlot(pickingSlot, opt);
    } else {
      addSlot(opt);
    }
  };

  const renderOptionButton = (opt: CharacterOption, showDesc = true) => (
    <button
      key={opt.path}
      onClick={() => handlePickerClick(opt)}
      className="flex items-center gap-1.5 bg-gray-50 dark:bg-gray-900 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg px-2 py-1.5 border border-gray-200 dark:border-gray-700 hover:border-blue-300 transition-colors"
    >
      <img src={getFileUrl(opt.url)} alt={opt.name} className="w-10 h-10 rounded object-cover" />
      <div className="text-xs text-left min-w-0">
        <div className="text-gray-700 dark:text-gray-200 truncate max-w-[90px]">{opt.name}</div>
        {showDesc && opt.description && (
          <div className="text-gray-400 dark:text-gray-500 truncate max-w-[90px] text-[10px]">{opt.description}</div>
        )}
      </div>
    </button>
  );

  const renderPicker = () => {
    const groupKeys = Object.keys(charGroups).filter((k) => k !== "__none__");
    const ungrouped = charGroups["__none__"] || [];

    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-2 mt-2 max-h-56 overflow-y-auto">
        {groupKeys.map((faceFile) => {
          const faceOpt = faceByFilename[faceFile];
          const chars = charGroups[faceFile];
          return (
            <div key={faceFile} className="mb-2">
              <div className="flex items-center gap-1.5 mb-1">
                {faceOpt && (
                  <img src={getFileUrl(faceOpt.url)} alt={faceOpt.name} className="w-5 h-5 rounded-full object-cover" />
                )}
                <div className="text-[10px] text-gray-500 dark:text-gray-400 font-medium">
                  {faceOpt?.name || faceFile}
                  <span className="text-gray-400 dark:text-gray-500 ml-1">({t("char.variants", { count: chars.length })})</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 ml-6">
                {chars.map((opt) => renderOptionButton(opt))}
              </div>
            </div>
          );
        })}

        {ungrouped.length > 0 && (
          <div className="mb-2">
            <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-1">{t("char.characters")}</div>
            <div className="flex flex-wrap gap-1.5">
              {ungrouped.map((opt) => renderOptionButton(opt))}
            </div>
          </div>
        )}

        {availableFaces.length > 0 && (
          <div>
            <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-1">{t("char.faces")}</div>
            <div className="flex flex-wrap gap-1.5">
              {availableFaces.map((opt) => renderOptionButton(opt, false))}
            </div>
          </div>
        )}

        {available.length === 0 && (
          <div className="text-xs text-gray-400 dark:text-gray-500 text-center py-2">{t("char.noMore")}</div>
        )}
      </div>
    );
  };

  return (
    <div className="bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-xl p-3 my-2">
      <div className="text-xs text-blue-600 dark:text-blue-400 font-medium mb-2">
        {t("char.instruction")}
      </div>

      <div className="flex flex-wrap gap-2 mb-2">
        {slots.map((opt, i) => (
          <div key={`${opt.path}-${i}`} className="relative group">
            <button
              onClick={() => setPickingSlot(pickingSlot === i ? null : i)}
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 border shadow-sm transition-colors ${
                pickingSlot === i
                  ? "bg-blue-100 dark:bg-blue-900/40 border-blue-400 ring-1 ring-blue-400"
                  : "bg-white dark:bg-gray-800 border-blue-300 dark:border-blue-600 hover:border-blue-400"
              }`}
            >
              <img src={getFileUrl(opt.url)} alt={opt.name} className="w-10 h-10 rounded object-cover" />
              <div className="text-xs min-w-0 text-left">
                <div className="font-medium text-gray-700 dark:text-gray-200 truncate max-w-[100px]">
                  {opt.label || opt.name}
                </div>
                <div className="text-gray-400 dark:text-gray-500 truncate max-w-[100px]">
                  {opt.category === "characters" ? t("char.categoryChar") : t("char.categoryFace")}
                </div>
              </div>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); removeSlot(i); }}
              className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-gray-400 text-white rounded-full text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500"
            >
              ×
            </button>
          </div>
        ))}

        {available.length > 0 && (
          <button
            onClick={() => setPickingSlot(pickingSlot === slots.length ? null : slots.length)}
            className={`flex items-center gap-1 rounded-lg px-3 py-1.5 border border-dashed transition-colors ${
              pickingSlot === slots.length
                ? "border-blue-400 bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400"
                : "border-gray-300 dark:border-gray-600 hover:border-blue-400 text-gray-400 dark:text-gray-500 hover:text-blue-500"
            }`}
          >
            <span className="text-lg leading-none">+</span>
            <span className="text-xs">{t("common.add")}</span>
          </button>
        )}
      </div>

      {pickingSlot !== null && renderPicker()}

      <button
        onClick={handleConfirm}
        disabled={slots.length === 0 || disabled}
        className="w-full mt-2 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        {t("char.confirmSelection")} ({slots.length})
      </button>
    </div>
  );
}
