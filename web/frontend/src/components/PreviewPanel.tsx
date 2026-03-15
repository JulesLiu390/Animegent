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
  videos: "cat.videos",
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

  useEffect(() => {
    setEditContent(asset.content || "");
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
    <div className="w-80 bg-white border-l border-gray-200 flex flex-col h-full">
      <div className="p-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 truncate">{t("preview.title")}</h3>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
        >
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {isImage && (
          <div className="flex justify-center bg-gray-50 rounded-lg border border-gray-100 p-2 mb-3">
            <img
              src={getFileUrl(asset.url)}
              alt={asset.name}
              className="max-w-full max-h-[50vh] object-contain rounded"
            />
          </div>
        )}

        {isVideo && (
          <div className="bg-black rounded-lg border border-gray-100 mb-3 overflow-hidden">
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
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className={`w-full h-[40vh] bg-gray-50 rounded-lg border p-3 text-xs text-gray-700 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                dirty ? "border-blue-300" : "border-gray-100"
              }`}
            />
          </div>
        )}

        {isJson && asset.content && (
          <div className="mb-3">
            <pre className="w-full h-[40vh] bg-gray-50 rounded-lg border border-gray-100 p-3 text-xs text-gray-700 font-mono overflow-auto whitespace-pre-wrap">
              {(() => { try { return JSON.stringify(JSON.parse(asset.content), null, 2); } catch { return asset.content; } })()}
            </pre>
          </div>
        )}

        <div className="space-y-2">
          <div>
            <div className="text-[10px] text-gray-400 mb-0.5">{t("preview.filename")}</div>
            <div className="text-xs text-gray-700 break-all">{asset.name}</div>
          </div>

          {category && (
            <div>
              <div className="text-[10px] text-gray-400 mb-0.5">{t("preview.category")}</div>
              <div className="text-xs text-gray-700">{t(CAT_KEYS[category] || category)}</div>
            </div>
          )}

          {asset.description && (
            <div>
              <div className="text-[10px] text-gray-400 mb-0.5">{t("preview.description")}</div>
              <div className="text-xs text-gray-700">{asset.description}</div>
            </div>
          )}

          {asset.source_face && (
            <div>
              <div className="text-[10px] text-gray-400 mb-0.5">{t("preview.sourceFace")}</div>
              <div className="text-xs text-gray-700">{asset.source_face}</div>
            </div>
          )}
        </div>
      </div>

      <div className="p-3 border-t border-gray-200 space-y-2">
        {dirty && (
          <div className="flex gap-2">
            <button
              onClick={handleRevert}
              className="flex-1 py-2 bg-gray-100 text-gray-700 text-xs font-medium rounded-lg hover:bg-gray-200 transition-colors"
            >
              {t("common.revert")}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 py-2 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors"
            >
              {saving ? t("common.saving") : t("common.save")}
            </button>
          </div>
        )}
        <button
          onClick={onSendToChat}
          className="w-full py-2 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 transition-colors"
        >
          {t("preview.sendToChat")}
        </button>
      </div>
    </div>
  );
}
