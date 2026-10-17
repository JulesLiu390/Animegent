import { useState } from "react";
import type { Asset } from "../api";
import { getFileUrl, updateAsset } from "../api";
import { useLang, useLightbox, useToast } from "../hooks";
import { CATEGORIES } from "../lib/assets";
import Icon from "./Icon";
import MarkdownText from "./MarkdownText";
import Segmented from "./Segmented";

interface Props {
  asset: Asset;
  category?: string;
  project: string;
  onClose: () => void;
  onSendToChat: () => void;
  onSaved: () => void;
  onDelete?: () => void;
  onOpenLink: (url: string) => boolean;
}

/** 右侧预览面板。按素材 path 作为 key 挂载，切换素材时编辑状态自动重置。 */
export default function PreviewPanel({ asset, category, project, onClose, onSendToChat, onSaved, onDelete, onOpenLink }: Props) {
  const { t } = useLang();
  const toast = useToast();
  const openLightbox = useLightbox();
  const isImage = asset.type === "image";
  const isVideo = asset.type === "video";
  const isMarkdown = asset.type === "markdown";
  const isJson = asset.type === "json";
  const readonly = !!asset.readonly;

  const [editContent, setEditContent] = useState(asset.content || "");
  const [tab, setTab] = useState<"edit" | "preview">("preview");
  const [saving, setSaving] = useState(false);
  const dirty = isMarkdown && editContent !== (asset.content || "");
  const info = category ? CATEGORIES[category] : undefined;
  const url = getFileUrl(asset.url);
  const title = asset.title || asset.name;

  const save = async () => {
    setSaving(true);
    try {
      const res = await updateAsset(asset.path, editContent);
      if (!res.updated) throw new Error(res.error || "save failed");
      toast(t("preview.saved"), "success");
      onSaved();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSaving(false);
    }
  };

  const json = isJson ? (() => {
    try {
      return JSON.stringify(JSON.parse(asset.content || ""), null, 2);
    } catch {
      return asset.content || "";
    }
  })() : "";

  return (
    <aside className="flex h-full w-[360px] shrink-0 animate-fade-in flex-col border-l border-zinc-200/80 bg-white dark:border-zinc-800/80 dark:bg-zinc-925">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200/80 px-3 dark:border-zinc-800/80">
        {info && (
          <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            <Icon name={info.icon} className="h-3 w-3" />
            {t(info.label)}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100" title={title}>{title}</span>
        <button onClick={onClose} className="icon-btn-sm" title={t("common.close")}>
          <Icon name="x" className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {isImage && (
          <button
            onClick={() => openLightbox([{ url, name: asset.name }])}
            className="group relative flex w-full cursor-zoom-in justify-center overflow-hidden rounded-xl border border-zinc-200 bg-[repeating-conic-gradient(#f4f4f5_0%_25%,#fafafa_0%_50%)] bg-[length:16px_16px] p-2 dark:border-zinc-800 dark:bg-[repeating-conic-gradient(#18181b_0%_25%,#27272a_0%_50%)]"
          >
            <img src={url} alt={asset.name} className="max-h-[52vh] max-w-full rounded-md object-contain" />
            <span className="absolute right-2 top-2 rounded-md bg-black/50 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100">
              <Icon name="maximize" className="h-3.5 w-3.5" />
            </span>
          </button>
        )}

        {isVideo && (
          <video key={asset.url} src={url} controls className="max-h-[52vh] w-full rounded-xl bg-black" />
        )}

        {isMarkdown && (
          <div>
            {readonly ? (
              <div className="mb-2 rounded-lg bg-zinc-50 px-3 py-2 text-[11px] leading-relaxed text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                {t("preview.builtinSkill")}
              </div>
            ) : (
            <div className="mb-2 flex items-center justify-between">
              <Segmented
                value={tab}
                onChange={setTab}
                options={[
                  { value: "preview", label: t("preview.preview"), icon: "eye" },
                  { value: "edit", label: t("preview.edit"), icon: "pencil" },
                ]}
              />
              {dirty && <span className="text-[11px] text-amber-600 dark:text-amber-400">{t("preview.unsaved")}</span>}
            </div>
            )}
            {tab === "edit" && !readonly ? (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                spellCheck={false}
                className="field h-[58vh] w-full resize-none py-2.5 font-mono text-[12px] leading-relaxed"
              />
            ) : (
              <div className="min-h-[20vh] rounded-xl border border-zinc-200 bg-zinc-50/60 p-3.5 dark:border-zinc-800 dark:bg-zinc-950/40">
                <MarkdownText
                  text={(category === "skills" ? withoutFrontmatter(editContent) : editContent) || "—"}
                  project={project}
                  onOpenLink={onOpenLink}
                  className="md-sm"
                />
              </div>
            )}
          </div>
        )}

        {isJson && (
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-all rounded-xl border border-zinc-200 bg-zinc-50 p-3 font-mono text-[11px] leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
            {json}
          </pre>
        )}

        <dl className="mt-4 space-y-3">
          <Meta label={t("preview.filename")} value={asset.name} mono />
          {asset.title && asset.title !== asset.name && <Meta label={t("preview.name")} value={asset.title} />}
          {asset.description && <Meta label={t("preview.description")} value={asset.description} />}
          {asset.source_face && <Meta label={t("preview.sourceFace")} value={asset.source_face} mono />}
        </dl>
      </div>

      <div className="shrink-0 space-y-2 border-t border-zinc-200/80 p-3 dark:border-zinc-800/80">
        {dirty && (
          <div className="flex gap-2">
            <button onClick={() => setEditContent(asset.content || "")} className="btn-secondary flex-1">{t("common.revert")}</button>
            <button onClick={save} disabled={saving} className="btn-primary flex-1">{saving ? t("common.saving") : t("common.save")}</button>
          </div>
        )}
        <div className="flex gap-2">
          <button onClick={onSendToChat} className="btn-primary flex-1 py-2">
            <Icon name="plus" className="h-3.5 w-3.5" strokeWidth={2.5} />
            {t("preview.sendToChat")}
          </button>
          {(isImage || isVideo) && (
            <>
              <a href={url} target="_blank" rel="noopener noreferrer" className="icon-btn border border-zinc-200 dark:border-zinc-700" title={t("common.openNewTab")}>
                <Icon name="external-link" />
              </a>
              <a href={url} download={asset.name} className="icon-btn border border-zinc-200 dark:border-zinc-700" title={t("common.download")}>
                <Icon name="download" />
              </a>
            </>
          )}
          {onDelete && (
            <button onClick={onDelete} className="icon-btn border border-zinc-200 hover:border-red-200 hover:bg-red-50 hover:text-red-500 dark:border-zinc-700 dark:hover:border-red-500/30 dark:hover:bg-red-500/10" title={t("common.delete")}>
              <Icon name="trash" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

/** 技能的 SKILL.md 开头是 YAML frontmatter：预览时不显示（名称和描述在下面单独列出）。 */
function withoutFrontmatter(text: string): string {
  const match = /^---\r?\n[\s\S]*?\r?\n---[ \t]*(\r?\n|$)/.exec(text);
  return match ? text.slice(match[0].length) : text;
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] font-medium text-zinc-400">{label}</dt>
      <dd className={`mt-0.5 break-all text-xs leading-relaxed text-zinc-700 dark:text-zinc-200 ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
