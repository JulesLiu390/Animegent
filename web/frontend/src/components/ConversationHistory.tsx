import { useEffect, useMemo, useRef, useState } from "react";
import type { Conversation } from "../api";
import { useLang } from "../hooks";
import { timeAgo } from "../lib/format";
import ConfirmDialog from "./ConfirmDialog";
import Icon from "./Icon";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  currentTitle: string;
  onSelect: (conv: Conversation) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onRefresh: () => void;
}

type T = (key: string, params?: Record<string, string | number>) => string;

/** Group conversations by date bucket. */
function groupByDate(conversations: Conversation[], t: T) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  const buckets = [
    { label: t("history.today"), from: today, items: [] as Conversation[] },
    { label: t("history.yesterday"), from: today - day, items: [] as Conversation[] },
    { label: t("history.thisWeek"), from: today - 7 * day, items: [] as Conversation[] },
    { label: t("history.thisMonth"), from: today - 30 * day, items: [] as Conversation[] },
    { label: t("history.older"), from: -Infinity, items: [] as Conversation[] },
  ];
  for (const conv of conversations) {
    const time = new Date(conv.updated_at).getTime();
    buckets.find((b) => time >= b.from)!.items.push(conv);
  }
  return buckets.filter((b) => b.items.length > 0);
}

export default function ConversationHistory({ conversations, currentId, currentTitle, onSelect, onNew, onDelete, onRename, onRefresh }: Props) {
  const { t, lang } = useLang();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    onRefresh();
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
  }, [open, onRefresh]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? conversations.filter((c) => (c.title || "").toLowerCase().includes(q)) : conversations;
  }, [conversations, search]);
  const groups = useMemo(() => groupByDate(filtered, t), [filtered, t]);

  const close = () => {
    setOpen(false);
    setSearch("");
    setRenaming(null);
  };

  const submitRename = () => {
    if (renaming && renaming.title.trim()) onRename(renaming.id, renaming.title.trim());
    setRenaming(null);
  };

  return (
    <div className="relative min-w-0" ref={rootRef}>
      <button
        onClick={() => (open ? close() : setOpen(true))}
        className={`flex min-w-0 max-w-[min(440px,55vw)] items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors ${
          open ? "bg-zinc-100 dark:bg-zinc-800" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
        } text-zinc-800 dark:text-zinc-100`}
      >
        <Icon name="history" className="h-4 w-4 text-zinc-400" />
        <span className="truncate">{currentTitle || t("history.newChat")}</span>
        <Icon name="chevron-down" className={`h-3.5 w-3.5 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="popover absolute left-1/2 top-full z-40 mt-1.5 w-[340px] -translate-x-1/2 overflow-hidden">
          <div className="space-y-1 p-2">
            <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 focus-within:border-brand-400 dark:border-zinc-700 dark:bg-zinc-950">
              <Icon name="search" className="h-3.5 w-3.5 text-zinc-400" />
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("history.search")}
                className="min-w-0 flex-1 bg-transparent text-sm text-zinc-800 placeholder-zinc-400 outline-none dark:text-zinc-100"
              />
            </div>
            <button onClick={() => { onNew(); close(); }} className="menu-item font-medium text-brand-600 dark:text-brand-400">
              <Icon name="new-chat" className="h-4 w-4" />
              {t("history.newChat")}
            </button>
          </div>

          <div className="max-h-[min(420px,60vh)] overflow-y-auto border-t border-zinc-100 p-1.5 dark:border-zinc-800">
            {groups.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-zinc-400">
                {search ? t("history.noMatch") : t("history.noHistory")}
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.label} className="mb-1">
                  <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium text-zinc-400">{group.label}</div>
                  {group.items.map((conv) => {
                    const current = conv.id === currentId;
                    if (renaming?.id === conv.id) {
                      return (
                        <div key={conv.id} className="px-1 py-0.5">
                          <input
                            autoFocus
                            value={renaming.title}
                            onChange={(e) => setRenaming({ ...renaming, title: e.target.value })}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.nativeEvent.isComposing) submitRename();
                              if (e.key === "Escape") { e.stopPropagation(); setRenaming(null); }
                            }}
                            onBlur={submitRename}
                            maxLength={60}
                            className="field w-full text-sm"
                          />
                        </div>
                      );
                    }
                    return (
                      <div
                        key={conv.id}
                        onClick={() => { onSelect(conv); close(); }}
                        className={`group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 transition-colors ${
                          current ? "bg-brand-50 dark:bg-brand-500/10" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className={`truncate text-sm ${current ? "font-medium text-brand-700 dark:text-brand-300" : "text-zinc-700 dark:text-zinc-200"}`}>
                            {conv.title || t("history.untitled")}
                          </div>
                          <div className="mt-0.5 text-[11px] text-zinc-400">
                            {t("history.messages", { count: conv.message_count })} · {timeAgo(conv.updated_at, t, lang)}
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100">
                          <button
                            onClick={(e) => { e.stopPropagation(); setRenaming({ id: conv.id, title: conv.title || "" }); }}
                            className="icon-btn-sm h-6 w-6"
                            title={t("history.rename")}
                          >
                            <Icon name="pencil" className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setDeleteId(conv.id); }}
                            className="icon-btn-sm h-6 w-6 hover:text-red-500"
                            title={t("history.delete")}
                          >
                            <Icon name="trash" className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {deleteId && (
        <ConfirmDialog
          title={t("history.delete")}
          message={t("history.deleteConfirm")}
          confirmLabel={t("common.delete")}
          onConfirm={() => { onDelete(deleteId); setDeleteId(null); }}
          onCancel={() => setDeleteId(null)}
        />
      )}
    </div>
  );
}
