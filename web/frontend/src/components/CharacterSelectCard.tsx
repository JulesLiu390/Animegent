import { useState } from "react";
import type { CharacterOption } from "../api";
import { getFileUrl } from "../api";

interface Props {
  options: CharacterOption[];
  onConfirm: (selected: CharacterOption[]) => void;
  disabled?: boolean;
}

export default function CharacterSelectCard({ options, onConfirm, disabled }: Props) {
  // Selected slots: array to preserve order
  const [slots, setSlots] = useState<CharacterOption[]>(() =>
    options.filter((o) => o.selected)
  );
  // Which slot index is currently open for picking (null = none)
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

  // All options not currently in a slot
  const available = options.filter((o) => !selectedPaths.has(o.path));
  const availableChars = available.filter((o) => o.category === "characters");
  const availableFaces = available.filter((o) => o.category === "faces");

  if (confirmed) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-xl p-3 my-2">
        <div className="text-xs text-green-600 font-medium mb-2">
          已确认 {slots.length} 个角色
        </div>
        <div className="flex flex-wrap gap-2">
          {slots.map((opt) => (
            <div key={opt.path} className="flex items-center gap-1.5 bg-white rounded-lg px-2 py-1 border border-green-200">
              <img src={getFileUrl(opt.url)} alt={opt.name} className="w-8 h-8 rounded object-cover" />
              <div className="text-xs font-medium text-gray-700">{opt.label || opt.name}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const renderPicker = () => (
    <div className="bg-white rounded-lg border border-gray-200 p-2 mt-2 max-h-48 overflow-y-auto">
      {availableChars.length > 0 && (
        <div className="mb-2">
          <div className="text-[10px] text-gray-400 mb-1">角色素材</div>
          <div className="flex flex-wrap gap-1.5">
            {availableChars.map((opt) => (
              <button
                key={opt.path}
                onClick={() =>
                  pickingSlot !== null && pickingSlot < slots.length
                    ? replaceSlot(pickingSlot, opt)
                    : addSlot(opt)
                }
                className="flex items-center gap-1.5 bg-gray-50 hover:bg-blue-50 rounded-lg px-2 py-1.5 border border-gray-200 hover:border-blue-300 transition-colors"
              >
                <img src={getFileUrl(opt.url)} alt={opt.name} className="w-10 h-10 rounded object-cover" />
                <div className="text-xs text-left min-w-0">
                  <div className="text-gray-700 truncate max-w-[90px]">{opt.name}</div>
                  <div className="text-gray-400 truncate max-w-[90px] text-[10px]">{opt.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
      {availableFaces.length > 0 && (
        <div>
          <div className="text-[10px] text-gray-400 mb-1">人脸素材</div>
          <div className="flex flex-wrap gap-1.5">
            {availableFaces.map((opt) => (
              <button
                key={opt.path}
                onClick={() =>
                  pickingSlot !== null && pickingSlot < slots.length
                    ? replaceSlot(pickingSlot, opt)
                    : addSlot(opt)
                }
                className="flex items-center gap-1.5 bg-gray-50 hover:bg-blue-50 rounded-lg px-2 py-1.5 border border-gray-200 hover:border-blue-300 transition-colors"
              >
                <img src={getFileUrl(opt.url)} alt={opt.name} className="w-10 h-10 rounded object-cover" />
                <div className="text-xs text-left min-w-0">
                  <div className="text-gray-700 truncate max-w-[90px]">{opt.name}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
      {available.length === 0 && (
        <div className="text-xs text-gray-400 text-center py-2">没有更多素材</div>
      )}
    </div>
  );

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 my-2">
      <div className="text-xs text-blue-600 font-medium mb-2">
        请确认要使用的角色（点击角色可替换）：
      </div>

      {/* Character slots */}
      <div className="flex flex-wrap gap-2 mb-2">
        {slots.map((opt, i) => (
          <div key={`${opt.path}-${i}`} className="relative group">
            <button
              onClick={() => setPickingSlot(pickingSlot === i ? null : i)}
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 border shadow-sm transition-colors ${
                pickingSlot === i
                  ? "bg-blue-100 border-blue-400 ring-1 ring-blue-400"
                  : "bg-white border-blue-300 hover:border-blue-400"
              }`}
            >
              <img src={getFileUrl(opt.url)} alt={opt.name} className="w-10 h-10 rounded object-cover" />
              <div className="text-xs min-w-0 text-left">
                <div className="font-medium text-gray-700 truncate max-w-[100px]">
                  {opt.label || opt.name}
                </div>
                <div className="text-gray-400 truncate max-w-[100px]">
                  {opt.category === "characters" ? "角色" : "人脸"}
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

        {/* Add new slot button */}
        {available.length > 0 && (
          <button
            onClick={() => setPickingSlot(pickingSlot === slots.length ? null : slots.length)}
            className={`flex items-center gap-1 rounded-lg px-3 py-1.5 border border-dashed transition-colors ${
              pickingSlot === slots.length
                ? "border-blue-400 bg-blue-100 text-blue-600"
                : "border-gray-300 hover:border-blue-400 text-gray-400 hover:text-blue-500"
            }`}
          >
            <span className="text-lg leading-none">+</span>
            <span className="text-xs">添加</span>
          </button>
        )}
      </div>

      {/* Picker panel (shown when a slot is clicked or "add" is clicked) */}
      {pickingSlot !== null && renderPicker()}

      {/* Confirm button */}
      <button
        onClick={handleConfirm}
        disabled={slots.length === 0 || disabled}
        className="w-full mt-2 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        确认选择 ({slots.length})
      </button>
    </div>
  );
}
