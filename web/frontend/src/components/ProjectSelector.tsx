import { useState, useEffect, useCallback } from "react";
import type { Project } from "../api";
import { useLang } from "../LanguageContext";
import ConfirmDialog from "./ConfirmDialog";

const RECENT_KEY = "anidaily-recent-projects";
const MAX_RECENT = 5;

function getRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
  } catch {
    return [];
  }
}

function pushRecent(name: string) {
  const list = getRecent().filter((n) => n !== name);
  list.unshift(name);
  localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
}

interface Props {
  projects: Project[];
  current: string | null;
  onSelect: (name: string) => void;
  onRename?: (oldName: string, newName: string) => void;
  onCreate: (name: string) => void;
  onDelete: (name: string) => void;
}

export default function ProjectSelector({ projects, current, onSelect, onRename, onCreate, onDelete }: Props) {
  const { t } = useLang();
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const [recent, setRecent] = useState<string[]>(getRecent);

  // Track recent projects
  const selectProject = useCallback((name: string) => {
    onSelect(name);
    pushRecent(name);
    setRecent(getRecent());
  }, [onSelect]);

  // Update recent when current changes externally
  useEffect(() => {
    if (current) {
      pushRecent(current);
      setRecent(getRecent());
    }
  }, [current]);

  const handleCreate = () => {
    const name = newName.trim();
    if (!name) return;
    onCreate(name);
    pushRecent(name);
    setRecent(getRecent());
    setNewName("");
    setShowNew(false);
  };

  const handleRename = () => {
    const name = renameName.trim();
    if (!name || !current || name === current) {
      setRenaming(false);
      return;
    }
    onRename?.(current, name);
    setRenaming(false);
    setRenameName("");
  };

  const startRename = () => {
    setRenameName(current || "");
    setRenaming(true);
  };

  // Filter recent to only existing projects
  const projectNames = new Set(projects.map((p) => p.name));
  const recentProjects = recent.filter((n) => projectNames.has(n) && n !== current);

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
      <span className="text-sm text-gray-500 dark:text-gray-400 shrink-0">{t("project.label")}</span>

      <select
        value={current || ""}
        onChange={(e) => selectProject(e.target.value)}
        className="text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 bg-white dark:bg-gray-700 dark:text-gray-200 focus:outline-none focus:border-blue-400 min-w-[120px]"
      >
        <option value="" disabled>{t("project.select")}</option>
        {recentProjects.length > 0 && (
          <optgroup label={t("project.recent")}>
            {recentProjects.map((name) => (
              <option key={`recent-${name}`} value={name}>{name}</option>
            ))}
          </optgroup>
        )}
        <optgroup label={t("project.all")}>
          {projects.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </optgroup>
      </select>

      {current && !renaming && (
        <>
          <button
            onClick={startRename}
            className="px-2.5 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors"
            title={t("project.rename")}
          >
            {t("project.rename")}
          </button>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="px-2.5 py-1 text-xs font-medium text-red-500 bg-red-50 dark:bg-red-900/30 hover:bg-red-100 dark:hover:bg-red-900/50 rounded-lg transition-colors"
            title={t("project.deleteTitle")}
          >
            {t("common.delete")}
          </button>
        </>
      )}

      {renaming && (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRename();
              if (e.key === "Escape") setRenaming(false);
            }}
            className="text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 w-40 bg-white dark:bg-gray-700 dark:text-gray-200 focus:outline-none focus:border-blue-400"
          />
          <button onClick={handleRename} className="px-2.5 py-1 text-xs font-medium text-white bg-pink-500 hover:bg-pink-600 rounded-lg transition-colors">
            {t("common.confirm")}
          </button>
          <button onClick={() => setRenaming(false)} className="px-2.5 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors">
            {t("common.cancel")}
          </button>
        </div>
      )}

      {showDeleteConfirm && current && (
        <ConfirmDialog
          message={t("project.deleteConfirm", { name: current })}
          onConfirm={() => { onDelete(current); setShowDeleteConfirm(false); }}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}

      {!renaming && (showNew ? (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") { setShowNew(false); setNewName(""); }
            }}
            placeholder={t("project.namePlaceholder")}
            className="text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1 w-32 bg-white dark:bg-gray-700 dark:text-gray-200 focus:outline-none focus:border-blue-400"
          />
          <button onClick={handleCreate} className="px-2.5 py-1 text-xs font-medium text-white bg-pink-500 hover:bg-pink-600 rounded-lg transition-colors">
            {t("common.confirm")}
          </button>
          <button onClick={() => { setShowNew(false); setNewName(""); }} className="px-2.5 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors">
            {t("common.cancel")}
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowNew(true)}
          className="px-2.5 py-1 text-xs font-medium text-white bg-pink-500 hover:bg-pink-600 rounded-lg transition-colors"
        >
          {t("project.createNew")}
        </button>
      ))}
    </div>
  );
}
