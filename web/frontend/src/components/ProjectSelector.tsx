import { useEffect, useMemo, useRef, useState } from "react";
import type { Project } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../hooks";
import { readJson, RECENT_PROJECTS_KEY } from "../lib/storage";
import ConfirmDialog from "./ConfirmDialog";
import Icon from "./Icon";
import PromptDialog from "./PromptDialog";

interface Props {
  projects: Project[];
  current: string | null;
  onSelect: (name: string) => void;
  onCreate: (name: string) => Promise<void>;
  onRename: (oldName: string, newName: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
  /** 打开菜单时刷新项目列表（其他窗口里可能新建过项目） */
  onOpen?: () => void;
}

type Dialog = "create" | "rename" | "delete" | null;

export default function ProjectSelector({ projects, current, onSelect, onCreate, onRename, onDelete, onOpen }: Props) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const recent = useMemo(() => {
    if (!open) return [];
    const names = new Set(projects.map((p) => p.name));
    return readJson<string[]>(RECENT_PROJECTS_KEY, []).filter((n) => names.has(n) && n !== current).slice(0, 4);
  }, [open, projects, current]);

  const q = search.trim().toLowerCase();
  const matches = projects.filter((p) => !q || p.name.toLowerCase().includes(q));
  const byName = new Map(projects.map((p) => [p.name, p]));

  const close = () => {
    setOpen(false);
    setSearch("");
  };
  const choose = (name: string) => {
    close();
    if (name !== current) onSelect(name);
  };

  const row = (project: Project) => (
    <button key={project.name} onClick={() => choose(project.name)} className={`menu-item ${project.name === current ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}>
      <span className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md bg-zinc-100 text-zinc-400 dark:bg-zinc-800">
        {project.cover ? <img src={getFileUrl(project.cover)} alt="" className="h-full w-full object-cover object-top" /> : <Icon name="folder" className="h-3.5 w-3.5" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate">{project.name}</span>
        <span className="block text-[11px] text-zinc-400">
          {project.image_count ? t("welcome.images", { count: project.image_count }) : t("welcome.noImages")}
        </span>
      </span>
      {project.name === current && <Icon name="check" className="h-4 w-4 text-brand-500" />}
    </button>
  );

  return (
    <div className="relative min-w-0" ref={rootRef}>
      <button
        onClick={() => {
          if (open) close();
          else {
            setOpen(true);
            onOpen?.();
          }
        }}
        className={`flex min-w-0 max-w-[260px] items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium transition-colors ${
          open ? "bg-zinc-100 dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
        } ${current ? "text-zinc-800 dark:text-zinc-100" : "text-zinc-500"}`}
      >
        <Icon name="folder" className="h-4 w-4 text-zinc-400" />
        <span className="truncate">{current || t("project.select")}</span>
        <Icon name="chevron-down" className={`h-3.5 w-3.5 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="popover absolute left-0 top-full z-50 mt-1.5 w-72 overflow-hidden">
          {projects.length > 5 && (
            <div className="p-2 pb-0">
              <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 focus-within:border-brand-400 dark:border-zinc-700 dark:bg-zinc-950">
                <Icon name="search" className="h-3.5 w-3.5 text-zinc-400" />
                <input
                  autoFocus
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("project.search")}
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-zinc-400"
                />
              </div>
            </div>
          )}
          <div className="max-h-[min(380px,60vh)] overflow-y-auto p-1.5">
            {!q && recent.length > 0 && (
              <>
                <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-zinc-400">{t("project.recent")}</div>
                {recent.map((name) => byName.get(name)).filter((p): p is Project => Boolean(p)).map(row)}
                <div className="px-2.5 pb-1 pt-2.5 text-[11px] font-medium text-zinc-400">{t("project.all")}</div>
              </>
            )}
            {matches.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-zinc-400">{t("project.none")}</div>
            ) : (
              matches.map(row)
            )}
          </div>
          <div className="border-t border-zinc-100 p-1.5 dark:border-zinc-800">
            <button onClick={() => { close(); setDialog("create"); }} className="menu-item font-medium text-brand-600 dark:text-brand-400">
              <Icon name="folder-plus" className="h-4 w-4" />
              {t("project.createNew")}
            </button>
            {current && (
              <>
                <button onClick={() => { close(); setDialog("rename"); }} className="menu-item">
                  <Icon name="pencil" className="h-4 w-4 text-zinc-400" />
                  {t("project.renameCurrent")}
                </button>
                <button onClick={() => { close(); setDialog("delete"); }} className="menu-item text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10">
                  <Icon name="trash" className="h-4 w-4" />
                  {t("project.deleteCurrent")}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {dialog === "create" && (
        <PromptDialog
          title={t("project.createNew")}
          placeholder={t("project.namePlaceholder")}
          confirmLabel={t("project.create")}
          onConfirm={async (name) => { await onCreate(name); setDialog(null); }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === "rename" && current && (
        <PromptDialog
          title={t("project.renameTitle")}
          initialValue={current}
          confirmLabel={t("common.rename")}
          onConfirm={async (name) => {
            if (name !== current) await onRename(current, name);
            setDialog(null);
          }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === "delete" && current && (
        <ConfirmDialog
          title={t("project.deleteTitle")}
          message={t("project.deleteConfirm", { name: current })}
          confirmLabel={t("common.delete")}
          onConfirm={async () => { setDialog(null); await onDelete(current); }}
          onCancel={() => setDialog(null)}
        />
      )}
    </div>
  );
}
