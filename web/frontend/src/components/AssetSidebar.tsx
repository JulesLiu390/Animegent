import { useState, type DragEvent } from "react";
import type { Asset, Assets } from "../api";
import { deleteAsset, getFileUrl } from "../api";
import { useLang, useToast } from "../hooks";
import { CATEGORIES, DRAG_ASSET_TYPE, type Layout } from "../lib/assets";
import { naturalCompare } from "../lib/format";
import { readJson, writeJson } from "../lib/storage";
import ConfirmDialog from "./ConfirmDialog";
import Icon, { Spinner } from "./Icon";

const GRID: Record<Exclude<Layout, "list">, string> = {
  grid2: "grid-cols-2",
  grid3: "grid-cols-3",
  grid4: "grid-cols-4",
};

const COLLAPSE_KEY = "animegent-sidebar-collapsed";

interface Props {
  assets: Assets;
  loading: boolean;
  refreshing: boolean;
  selectedPath: string | null;
  onRefresh: () => void;
  onAssetClick: (asset: Asset, category: string) => void;
  onAddToChat: (asset: Asset) => void;
  onDeleted: (path: string) => void;
  onCollapse: () => void;
}

const firstLine = (text?: string) => (text || "").split("\n").map((l) => l.replace(/^#+\s*/, "").trim()).find(Boolean) || "";

export default function AssetSidebar({ assets, loading, refreshing, selectedPath, onRefresh, onAssetClick, onAddToChat, onDeleted, onCollapse }: Props) {
  const { t } = useLang();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => readJson(COLLAPSE_KEY, {}));
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);

  const toggle = (category: string) => setCollapsed((prev) => {
    const next = { ...prev, [category]: !prev[category] };
    writeJson(COLLAPSE_KEY, next);
    return next;
  });

  const sections = Object.keys(CATEGORIES)
    .filter((key) => (assets[key]?.length ?? 0) > 0)
    .map((key) => ({ key, info: CATEGORIES[key], items: [...assets[key]].sort((a, b) => naturalCompare(a.name, b.name)) }));
  const total = sections.reduce((sum, s) => sum + s.items.length, 0);

  const confirmDelete = async () => {
    const target = deleteTarget;
    setDeleteTarget(null);
    if (!target) return;
    try {
      const res = await deleteAsset(target.path);
      if (res.deleted === false) throw new Error(res.error || "delete failed");
      onDeleted(target.path);
      toast(t("sidebar.deleted"), "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const dragStart = (e: DragEvent, asset: Asset) => {
    e.dataTransfer.setData(DRAG_ASSET_TYPE, JSON.stringify(asset));
    e.dataTransfer.effectAllowed = "copy";
  };

  const tileActions = (asset: Asset, deletable: boolean) => (
    <div className="absolute right-1 top-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
      <button
        onClick={(e) => { e.stopPropagation(); onAddToChat(asset); }}
        title={t("sidebar.addToChat")}
        className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900/60 text-white backdrop-blur transition-colors hover:bg-brand-500"
      >
        <Icon name="plus" className="h-3.5 w-3.5" strokeWidth={2.5} />
      </button>
      {deletable && (
        <button
          onClick={(e) => { e.stopPropagation(); setDeleteTarget(asset); }}
          title={t("common.delete")}
          className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900/60 text-white backdrop-blur transition-colors hover:bg-red-500"
        >
          <Icon name="trash" className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-zinc-200/80 bg-white dark:border-zinc-800/80 dark:bg-zinc-925">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200/80 px-3 dark:border-zinc-800/80">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{t("sidebar.title")}</h2>
        {total > 0 && <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{total}</span>}
        <span className="flex-1" />
        <button onClick={onRefresh} className="icon-btn-sm" title={t("common.refresh")}>
          {refreshing ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="refresh" className="h-3.5 w-3.5" />}
        </button>
        <button onClick={onCollapse} className="icon-btn-sm" title={t("sidebar.collapse")}>
          <Icon name="chevron-left" className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        {loading && total === 0 ? (
          <div className="space-y-4 p-3">
            {[0, 1].map((i) => (
              <div key={i}>
                <div className="skeleton mb-2 h-3 w-20" />
                <div className="grid grid-cols-3 gap-2">
                  {[0, 1, 2, 3, 4, 5].map((j) => <div key={j} className="skeleton aspect-[3/4]" />)}
                </div>
              </div>
            ))}
          </div>
        ) : total === 0 ? (
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-100 text-zinc-400 dark:bg-zinc-800">
              <Icon name="layers" className="h-6 w-6" />
            </div>
            <div className="text-sm font-medium text-zinc-600 dark:text-zinc-300">{t("sidebar.empty")}</div>
            <p className="mt-1 text-xs leading-relaxed text-zinc-400">{t("sidebar.emptyHint")}</p>
          </div>
        ) : (
          sections.map(({ key, info, items }) => (
            <section key={key}>
              <button
                onClick={() => toggle(key)}
                className="sticky top-0 z-10 flex w-full items-center gap-2 bg-white/95 px-3 py-2 text-left backdrop-blur dark:bg-zinc-925/95"
              >
                <Icon name="chevron-right" className={`h-3 w-3 text-zinc-400 transition-transform ${collapsed[key] ? "" : "rotate-90"}`} />
                <Icon name={info.icon} className="h-3.5 w-3.5 text-zinc-400" />
                <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">{t(info.label)}</span>
                <span className="text-[11px] tabular-nums text-zinc-400">{items.length}</span>
              </button>
              {!collapsed[key] && (info.layout === "list" ? (
                <div className="space-y-0.5 px-2 pb-2">
                  {items.map((asset) => (
                    <div
                      key={asset.path}
                      draggable
                      onDragStart={(e) => dragStart(e, asset)}
                      onClick={() => onAssetClick(asset, key)}
                      className={`group relative flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors ${
                        selectedPath === asset.path ? "bg-brand-50 dark:bg-brand-500/10" : "hover:bg-zinc-100 dark:hover:bg-zinc-800/70"
                      }`}
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                        <Icon name={asset.type === "json" ? "braces" : info.icon} className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-xs font-medium text-zinc-700 dark:text-zinc-200">
                            {key === "skills" ? asset.title || asset.name : asset.name}
                          </span>
                          {key === "skills" && asset.source === "project" && (
                            <span className="chip shrink-0 bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300">{t("sidebar.projectSkill")}</span>
                          )}
                        </div>
                        {(key === "skills" ? asset.description : firstLine(asset.content)) && (
                          <div className="truncate text-[11px] text-zinc-400">{key === "skills" ? asset.description : firstLine(asset.content)}</div>
                        )}
                      </div>
                      {tileActions(asset, key !== "style" && !asset.readonly)}
                    </div>
                  ))}
                </div>
              ) : (
                <div className={`grid gap-2 px-3 pb-3 ${GRID[info.layout]}`}>
                  {items.map((asset) => {
                    const video = asset.type === "video";
                    const thumb = video ? asset.thumbnail : asset.url;
                    const label = asset.title || asset.name;
                    return (
                      <div
                        key={asset.path}
                        draggable
                        onDragStart={(e) => dragStart(e, asset)}
                        className="group relative min-w-0"
                        title={asset.description ? `${label}\n${asset.description}` : label}
                      >
                        <button
                          onClick={() => onAssetClick(asset, key)}
                          className={`relative block w-full overflow-hidden rounded-lg bg-zinc-100 transition-all dark:bg-zinc-800 ${info.aspect} ${
                            selectedPath === asset.path
                              ? "ring-2 ring-brand-500 ring-offset-1 ring-offset-white dark:ring-offset-zinc-925"
                              : "ring-1 ring-zinc-200 hover:ring-brand-300 dark:ring-zinc-700/80 dark:hover:ring-brand-500/50"
                          }`}
                        >
                          {thumb ? (
                            <img src={getFileUrl(thumb)} alt="" loading="lazy" draggable={false} className={`h-full w-full object-cover ${info.fit || ""}`} />
                          ) : (
                            <span className="flex h-full w-full items-center justify-center bg-zinc-900 text-zinc-500"><Icon name="video" className="h-5 w-5" /></span>
                          )}
                          {video && (
                            <span className="absolute inset-0 flex items-center justify-center">
                              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur">
                                <Icon name="play" className="ml-0.5 h-3 w-3" />
                              </span>
                            </span>
                          )}
                        </button>
                        {info.layout !== "grid4" && (
                          <div className="mt-1 truncate px-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">{label}</div>
                        )}
                        {tileActions(asset, true)}
                      </div>
                    );
                  })}
                </div>
              ))}
            </section>
          ))
        )}
      </div>

      {deleteTarget && (
        <ConfirmDialog
          title={t("sidebar.deleteTitle")}
          message={t("sidebar.deleteConfirm", { name: deleteTarget.title || deleteTarget.name })}
          confirmLabel={t("common.delete")}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </aside>
  );
}
