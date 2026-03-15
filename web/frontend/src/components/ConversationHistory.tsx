import { useState, useEffect, useRef, useMemo } from "react";
import type { Conversation } from "../api";
import { useLang } from "../LanguageContext";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  currentTitle: string;
  onSelect: (conv: Conversation) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRefresh: () => void;
}

/** Group conversations by date bucket. */
function groupByDate(conversations: Conversation[], t: (key: string) => string) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);
  const monthAgo = new Date(today.getTime() - 30 * 86400000);

  const groups: { label: string; items: Conversation[] }[] = [];
  const buckets: { label: string; items: Conversation[] }[] = [
    { label: t("history.today"), items: [] },
    { label: t("history.yesterday"), items: [] },
    { label: t("history.thisWeek"), items: [] },
    { label: t("history.thisMonth"), items: [] },
    { label: t("history.older"), items: [] },
  ];

  for (const conv of conversations) {
    const d = new Date(conv.updated_at);
    if (d >= today) buckets[0].items.push(conv);
    else if (d >= yesterday) buckets[1].items.push(conv);
    else if (d >= weekAgo) buckets[2].items.push(conv);
    else if (d >= monthAgo) buckets[3].items.push(conv);
    else buckets[4].items.push(conv);
  }

  for (const b of buckets) {
    if (b.items.length > 0) groups.push(b);
  }
  return groups;
}

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const d = new Date(dateStr).getTime();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d`;
}

export default function ConversationHistory({
  conversations,
  currentId,
  currentTitle,
  onSelect,
  onNew,
  onDelete,
  onRefresh,
}: Props) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Focus search on open
  useEffect(() => {
    if (open) {
      searchRef.current?.focus();
      onRefresh();
    }
  }, [open, onRefresh]);

  const filtered = useMemo(() => {
    if (!search.trim()) return conversations;
    const q = search.toLowerCase();
    return conversations.filter(
      (c) => (c.title || "").toLowerCase().includes(q)
    );
  }, [conversations, search]);

  const groups = useMemo(() => groupByDate(filtered, t), [filtered, t]);

  const displayTitle = currentTitle || t("history.newChat");

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger: title + chevron */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors max-w-[300px]"
      >
        <span className="truncate">{displayTitle}</span>
        <svg
          className={`w-3.5 h-3.5 shrink-0 text-gray-400 dark:text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 w-80 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl z-50 overflow-hidden">
          {/* Search */}
          <div className="px-3 pt-3 pb-2">
            <div className="flex items-center gap-2 px-2.5 py-1.5 bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
              <svg className="w-4 h-4 text-gray-400 dark:text-gray-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <circle cx="11" cy="11" r="8" />
                <path strokeLinecap="round" d="M21 21l-4.35-4.35" />
              </svg>
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("history.search")}
                className="flex-1 bg-transparent text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 outline-none"
              />
            </div>
          </div>

          {/* New Chat button */}
          <div className="px-3 pb-2">
            <button
              onClick={() => { onNew(); setOpen(false); setSearch(""); }}
              className="w-full flex items-center gap-2 px-2.5 py-2 text-sm text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              {t("history.newChat")}
            </button>
          </div>

          {/* Conversation list */}
          <div className="max-h-80 overflow-y-auto border-t border-gray-100 dark:border-gray-700">
            {groups.length === 0 ? (
              <div className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
                {t("history.noHistory")}
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.label}>
                  <div className="px-4 py-1.5 text-[11px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider bg-gray-50/80 dark:bg-gray-900/80">
                    {group.label}
                  </div>
                  {group.items.map((conv) => {
                    const isCurrent = conv.id === currentId;
                    return (
                      <div
                        key={conv.id}
                        onClick={() => { onSelect(conv); setOpen(false); setSearch(""); }}
                        className={`group flex items-center gap-2 px-4 py-2 cursor-pointer transition-colors ${
                          isCurrent
                            ? "bg-blue-50 dark:bg-blue-900/30 border-l-2 border-blue-500"
                            : "hover:bg-gray-50 dark:hover:bg-gray-700 border-l-2 border-transparent"
                        }`}
                      >
                        {/* Active indicator */}
                        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isCurrent ? "bg-green-500" : "bg-transparent"}`} />

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className={`text-sm truncate ${isCurrent ? "font-medium text-gray-900 dark:text-gray-100" : "text-gray-700 dark:text-gray-200"}`}>
                            {conv.title || t("history.untitled")}
                          </div>
                          <div className="text-xs text-gray-400 dark:text-gray-500">
                            {t("history.messages", { count: conv.message_count })}
                          </div>
                        </div>

                        {/* Time + actions */}
                        <div className="flex items-center gap-1 shrink-0">
                          <span className="text-[11px] text-gray-400 dark:text-gray-500">{timeAgo(conv.updated_at)}</span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteId(conv.id);
                            }}
                            className="p-0.5 text-gray-300 dark:text-gray-600 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                            title={t("history.delete")}
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
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
          message={t("history.deleteConfirm")}
          onConfirm={() => { onDelete(deleteId); setDeleteId(null); }}
          onCancel={() => setDeleteId(null)}
        />
      )}
    </div>
  );
}
