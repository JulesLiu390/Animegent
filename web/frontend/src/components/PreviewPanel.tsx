import { useEffect, useState } from "react";
import type { Asset } from "../api";
import { getFileUrl, updateAsset } from "../api";
import { useLang } from "../LanguageContext";

interface Props {
  asset: Asset;
  category?: string;
  onClose: () => void;
  onSendToChat: () => void;
  onAssetUpdated?: () => void;
}

const CAT_KEYS: Record<string, string> = {
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

export default function PreviewPanel({ asset, category, onClose, onSendToChat, onAssetUpdated }: Props) {
  const { t } = useLang();
  const isImage = asset.type === "image";
  const isVideo = asset.type === "video";
  const isMarkdown = asset.type === "markdown";
  const isJson = asset.type === "json";

  const [editContent, setEditContent] = useState(asset.content || "");
  const [saving, setSaving] = useState(false);
  const [mdPreview, setMdPreview] = useState(false);

  useEffect(() => {
    setEditContent(asset.content || "");
    setMdPreview(false);
  }, [asset.path, asset.content]);

  const dirty = isMarkdown && editContent !== (asset.content || "");

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await updateAsset(asset.path, editContent);
      if (res.updated) {
        onAssetUpdated?.();
      }
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = () => {
    setEditContent(asset.content || "");
  };

  return (
    <div className="w-80 bg-pink-50 dark:bg-gray-800 border-l border-pink-200/60 dark:border-gray-700 flex flex-col h-full">
      <div className="p-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 truncate">{t("preview.title")}</h3>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
        >
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {isImage && (
          <div className="flex justify-center bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-700 p-2 mb-3">
            <img
              src={getFileUrl(asset.url)}
              alt={asset.name}
              className="max-w-full max-h-[50vh] object-contain rounded"
            />
          </div>
        )}

        {isVideo && (
          <div className="bg-black rounded-lg border border-gray-100 dark:border-gray-700 mb-3 overflow-hidden">
            <video
              key={asset.url}
              src={getFileUrl(asset.url)}
              controls
              className="w-full max-h-[50vh]"
            />
          </div>
        )}

        {isMarkdown && (
          <div className="mb-3">
            <div className="flex gap-1 mb-1.5">
              <button
                onClick={() => setMdPreview(false)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded transition-colors ${!mdPreview ? "bg-pink-500 text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"}`}
              >
                {t("preview.edit")}
              </button>
              <button
                onClick={() => setMdPreview(true)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded transition-colors ${mdPreview ? "bg-pink-500 text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"}`}
              >
                {t("preview.preview")}
              </button>
            </div>
            {mdPreview ? (
              <div className="w-full h-[40vh] bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-700 p-3 text-xs text-gray-700 dark:text-gray-200 overflow-auto whitespace-pre-wrap">
                {editContent.split("\n").map((line, i) => {
                  if (line.startsWith("### ")) return <h3 key={i} className="text-sm font-semibold mt-2 mb-1">{line.slice(4)}</h3>;
                  if (line.startsWith("## ")) return <h2 key={i} className="text-base font-semibold mt-3 mb-1">{line.slice(3)}</h2>;
                  if (line.startsWith("# ")) return <h1 key={i} className="text-lg font-bold mt-3 mb-1">{line.slice(2)}</h1>;
                  if (line.startsWith("- ")) return <div key={i} className="pl-3">• {line.slice(2)}</div>;
                  if (line.trim() === "") return <div key={i} className="h-2" />;
                  return <div key={i}>{line}</div>;
                })}
              </div>
            ) : (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className={`w-full h-[40vh] bg-gray-50 dark:bg-gray-900 rounded-lg border p-3 text-xs text-gray-700 dark:text-gray-200 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                  dirty ? "border-blue-300" : "border-gray-100 dark:border-gray-700"
                }`}
              />
            )}
          </div>
        )}

        {isJson && asset.content && (
          <div className="mb-3">
            <pre className="w-full h-[40vh] bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-700 p-3 text-xs text-gray-700 dark:text-gray-200 font-mono overflow-auto whitespace-pre-wrap">
              {(() => { try { return JSON.stringify(JSON.parse(asset.content), null, 2); } catch { return asset.content; } })()}
            </pre>
          </div>
        )}

        <div className="space-y-2">
          <div>
            <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-0.5">{t("preview.filename")}</div>
            <div className="text-xs text-gray-700 dark:text-gray-200 break-all">{asset.name}</div>
          </div>

          {category && (
            <div>
              <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-0.5">{t("preview.category")}</div>
              <div className="text-xs text-gray-700 dark:text-gray-200">{t(CAT_KEYS[category] || category)}</div>
            </div>
          )}

          {asset.description && (
            <div>
              <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-0.5">{t("preview.description")}</div>
              <div className="text-xs text-gray-700 dark:text-gray-200">{asset.description}</div>
            </div>
          )}

          {asset.source_face && (
            <div>
              <div className="text-[10px] text-gray-400 dark:text-gray-500 mb-0.5">{t("preview.sourceFace")}</div>
              <div className="text-xs text-gray-700 dark:text-gray-200">{asset.source_face}</div>
            </div>
          )}
        </div>
      </div>

      <div className="p-3 border-t border-gray-200 dark:border-gray-700 space-y-2">
        {dirty && (
          <div className="flex gap-2">
            <button
              onClick={handleRevert}
              className="flex-1 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-xs font-medium rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            >
              {t("common.revert")}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 py-2 bg-pink-500 text-white text-xs font-medium rounded-lg hover:bg-pink-600 disabled:opacity-50 transition-colors"
            >
              {saving ? t("common.saving") : t("common.save")}
            </button>
          </div>
        )}
        <button
          onClick={onSendToChat}
          className="w-full py-2 bg-pink-500 text-white text-xs font-medium rounded-lg hover:bg-pink-600 transition-colors"
        >
          {t("preview.sendToChat")}
        </button>
      </div>
    </div>
  );
}
