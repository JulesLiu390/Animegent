import { useState } from "react";
import type { Assets } from "../api";
import { getFileUrl, deleteAsset } from "../api";
import { useLang } from "../LanguageContext";
import ConfirmDialog from "./ConfirmDialog";

const CAT_KEYS: Record<string, string> = {
  style: "cat.style",
  originals: "cat.input",
  characters: "cat.stylized",
  faces: "cat.faces",
  scenes: "cat.scenes_stylized",
  scenes_raw: "cat.scenes_no_people",
  panels: "cat.panels",
  clips: "cat.clips",
  final_videos: "cat.final_videos",
  storyboard_strips: "cat.storyboard_strips",
  storyboard_frames: "cat.storyboard_frames",
  storyboards: "cat.storyboards",
  clip_scripts: "cat.clip_scripts",
  scripts: "cat.scripts",
};

interface Props {
  assets: Assets;
  loading?: boolean;
  onAssetClick?: (path: string) => void;
  onRefresh?: () => void;
  onDeleteAsset?: (path: string) => void;
}

export default function AssetSidebar({ assets, loading, onAssetClick, onRefresh, onDeleteAsset }: Props) {
  const { t } = useLang();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggleCategory = (category: string) => {
    setCollapsed((prev) => ({ ...prev, [category]: !prev[category] }));
  };

  // Categories that show one item per row at original aspect ratio, sorted numerically
  const SINGLE_COL_CATS = new Set(["storyboard_strips", "storyboard_frames"]);
  const THREE_COL_CATS = new Set(["characters", "faces"]);
  const NUM_SORT_CATS = new Set(["storyboard_strips", "storyboard_frames", "clip_scripts", "clips"]);

  const numSort = (a: { name: string }, b: { name: string }) => {
    const na = parseInt(a.name.match(/\d+/)?.[0] || "0", 10);
    const nb = parseInt(b.name.match(/\d+/)?.[0] || "0", 10);
    return na - nb;
  };

  const [deleteTarget, setDeleteTarget] = useState<{ name: string; path: string } | null>(null);

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAsset(deleteTarget.path);
      onDeleteAsset?.(deleteTarget.path);
    } catch (err) {
      console.error("Delete failed:", err);
    }
    setDeleteTarget(null);
  };

  return (
    <div className="w-96 bg-pink-50 dark:bg-gray-800 border-r border-pink-200/60 dark:border-gray-700 flex flex-col h-full p-5">
      <div className="px-2 py-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">{t("sidebar.title")}</h2>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="px-2 py-0.5 text-[11px] font-medium text-pink-500 dark:text-gray-400 bg-pink-100 dark:bg-gray-700 hover:bg-pink-200 dark:hover:bg-gray-600 rounded-md transition-colors"
          >
            {t("common.refresh")}
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {!loading && Object.entries(assets).map(([category, items]) => (
          <div key={category} className="border-b border-gray-100 dark:border-gray-700">
            <button
              onClick={() => toggleCategory(category)}
              className="w-full px-3 py-2 text-xs font-medium text-pink-400 dark:text-gray-400 uppercase tracking-wide bg-pink-100/50 dark:bg-gray-700/80 flex items-center justify-between hover:bg-pink-100 dark:hover:bg-gray-700 transition-colors"
            >
              <span>{t(CAT_KEYS[category] || category)} ({items.length})</span>
              <span className={`text-[10px] transition-transform ${collapsed[category] ? "" : "rotate-90"}`}>▶</span>
            </button>
            {!collapsed[category] && (items.length === 0 ? (
              <div className="px-3 py-2 text-xs text-gray-400 dark:text-gray-500">{t("sidebar.empty")}</div>
            ) : SINGLE_COL_CATS.has(category) ? (
              <div className="p-2 flex flex-col gap-1.5">
                {[...items].sort(numSort).map((item) => (
                  <div
                    key={item.name}
                    className="cursor-pointer group relative"
                    onClick={() => onAssetClick?.(item.path)}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget({ name: item.name, path: item.path });
                      }}
                      className="absolute -top-1 -right-1 z-10 w-4 h-4 bg-gray-500 text-white rounded-full text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm hover:bg-red-500"
                    >
                      ×
                    </button>
                    <img
                      src={getFileUrl(item.url)}
                      alt={item.name}
                      className="w-full rounded-xl border border-gray-200 dark:border-gray-700 group-hover:border-blue-400 transition-colors"
                    />
                    <div className="text-[10px] text-gray-500 dark:text-gray-400 truncate mt-0.5 text-center">
                      {item.name}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className={`p-2 grid gap-1.5 ${THREE_COL_CATS.has(category) ? "grid-cols-3" : "grid-cols-2"}`}>
                {(NUM_SORT_CATS.has(category) ? [...items].sort(numSort) : items).map((item) =>
                  item.type === "image" ? (
                    <div
                      key={item.name}
                      className="cursor-pointer group relative"
                      onClick={() => onAssetClick?.(item.path)}
                    >
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteTarget({ name: item.name, path: item.path });
                        }}
                        className="absolute -top-1 -right-1 z-10 w-4 h-4 bg-gray-500 text-white rounded-full text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm hover:bg-red-500"
                      >
                        ×
                      </button>
                      <img
                        src={getFileUrl(item.url)}
                        alt={item.name}
                        className={`w-full rounded-xl border border-gray-200 dark:border-gray-700 group-hover:border-blue-400 transition-colors ${
                          THREE_COL_CATS.has(category) ? "object-cover" : "aspect-square object-cover"
                        }`}
                      />
                      <div className="text-[10px] text-gray-500 dark:text-gray-400 truncate mt-0.5 text-center">
                        {item.name}
                      </div>
                    </div>
                  ) : item.type === "video" ? (
                    <div
                      key={item.name}
                      className="cursor-pointer group relative"
                      onClick={() => onAssetClick?.(item.path)}
                    >
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteTarget({ name: item.name, path: item.path });
                        }}
                        className="absolute -top-1 -right-1 z-10 w-4 h-4 bg-gray-500 text-white rounded-full text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm hover:bg-red-500"
                      >
                        ×
                      </button>
                      <div className="relative w-full aspect-video rounded-xl border border-gray-200 dark:border-gray-700 group-hover:border-blue-400 transition-colors overflow-hidden bg-gray-900">
                        {item.thumbnail ? (
                          <img
                            src={getFileUrl(item.thumbnail)}
                            alt={item.name}
                            className="w-full h-full object-cover"
                          />
                        ) : null}
                        <div className="absolute inset-0 flex items-center justify-center">
                          <div className="w-6 h-6 bg-black/50 rounded-full flex items-center justify-center">
                            <svg className="w-3 h-3 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                              <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
                            </svg>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div
                      key={item.name}
                      className="col-span-2 px-2 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer truncate group relative"
                      onClick={() => onAssetClick?.(item.path)}
                    >
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteTarget({ name: item.name, path: item.path });
                        }}
                        className="absolute top-1 right-1 w-4 h-4 bg-gray-500 text-white rounded-full text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm hover:bg-red-500"
                      >
                        ×
                      </button>
                      {item.name}
                    </div>
                  )
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
      {deleteTarget && (
        <ConfirmDialog
          message={t("sidebar.deleteConfirm", { name: deleteTarget.name })}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
