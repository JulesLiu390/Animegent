import { useState, useRef } from "react";
import type { ImageVerdict, ToolCallInfo } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../LanguageContext";

const GENERATION_TOOLS = new Set([
  "stylize_character",
  "generate_asset",
  "generate_comic_strip",
  "edit_asset",
]);

interface Props {
  toolCall: ToolCallInfo;
  onAccept?: () => void;
  onReject?: () => void;
  onRevise?: (prompt: string) => void;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function ToolCallCard({ toolCall, onAccept, onReject, onRevise }: Props) {
  const { t } = useLang();
  const [expanded, setExpanded] = useState(false);
  const [revising, setRevising] = useState(false);
  const [reviseText, setReviseText] = useState("");
  const composingRef = useRef(false);
  const isPending = toolCall.pending;
  const hasError = toolCall.result && "error" in toolCall.result;
  const verdict: ImageVerdict = toolCall.verdict || "pending";

  const VIDEO_EXTS = [".mp4", ".webm", ".mov"];
  const imageOnly = toolCall.images?.filter((img) => !VIDEO_EXTS.some((ext) => img.path.toLowerCase().endsWith(ext)));
  const hasImages = imageOnly && imageOnly.length > 0;
  const isGenTool = GENERATION_TOOLS.has(toolCall.tool);
  const showActions = isGenTool && hasImages && !isPending && !hasError;

  const handleReviseSubmit = () => {
    const text = reviseText.trim();
    if (!text) return;
    onRevise?.(text);
    setRevising(false);
    setReviseText("");
  };

  return (
    <div
      className={`rounded-lg border transition-colors ${
        isPending
          ? "border-blue-200 bg-blue-50"
          : hasError
            ? "border-red-200 bg-red-50"
            : "border-green-200 bg-green-50"
      }`}
    >
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer"
        onClick={() => !isPending && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          {isPending ? (
            <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <span className={`text-sm ${hasError ? "text-red-500" : "text-green-500"}`}>
              {hasError ? "✗" : "✓"}
            </span>
          )}
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {toolCall.tool}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {toolCall.duration_ms != null && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {formatDuration(toolCall.duration_ms)}
            </span>
          )}
          {!isPending && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {expanded ? "▲" : "▶"}
            </span>
          )}
        </div>
      </div>

      {expanded && !isPending && (
        <div className="px-3 pb-2 space-y-1 border-t border-green-100">
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
            <div className="font-medium mb-0.5">Args:</div>
            <pre className="whitespace-pre-wrap bg-white/60 rounded p-1.5 overflow-x-auto">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>
          {toolCall.result && (
            <div className="text-xs text-gray-500 dark:text-gray-400">
              <div className="font-medium mb-0.5">Result:</div>
              <pre className="whitespace-pre-wrap bg-white/60 rounded p-1.5 overflow-x-auto max-h-40 overflow-y-auto">
                {JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {hasImages && (
        <div className="px-3 pb-2">
          <div className="grid grid-cols-2 gap-2">
            {imageOnly!.map((img, j) => (
              <a
                key={j}
                href={getFileUrl(img.url)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
              >
                <img
                  src={getFileUrl(img.url)}
                  alt={img.tool}
                  className={`rounded-lg border max-h-64 object-contain ${
                    verdict === "rejected"
                      ? "border-red-200 opacity-40"
                      : verdict === "accepted"
                        ? "border-green-300"
                        : "border-gray-200 dark:border-gray-700"
                  }`}
                />
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Video preview for generated clips */}
      {toolCall.tool === "generate_video_clip" && typeof toolCall.result?.output_path === "string" && (
        <div className="px-3 pb-2">
          <video
            src={getFileUrl(`/files/${toolCall.result.output_path.replace(/^.*?projects\//, 'projects/')}`)}
            controls
            className="max-w-full rounded-lg"
            style={{ maxHeight: 300 }}
          />
        </div>
      )}

      {showActions && (
        <div className="px-3 pb-2">
          {verdict === "pending" && (
            <>
              <div className="flex gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); onAccept?.(); }}
                  className="flex-1 py-1.5 bg-green-500 text-white text-xs font-medium rounded-lg hover:bg-green-600 transition-colors"
                >
                  {t("tool.accept")}
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onReject?.(); }}
                  className="flex-1 py-1.5 bg-red-100 text-red-600 text-xs font-medium rounded-lg hover:bg-red-200 transition-colors"
                >
                  {t("tool.reject")}
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); setRevising(!revising); }}
                  className={`flex-1 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                    revising
                      ? "bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-400"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  {t("tool.revise")}
                </button>
              </div>
              {revising && (
                <div className="mt-2 flex gap-2">
                  <input
                    type="text"
                    value={reviseText}
                    onChange={(e) => setReviseText(e.target.value)}
                    onCompositionStart={() => { composingRef.current = true; }}
                    onCompositionEnd={() => { composingRef.current = false; }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !composingRef.current) {
                        e.preventDefault();
                        handleReviseSubmit();
                      }
                    }}
                    placeholder={t("tool.revisePlaceholder")}
                    className="flex-1 px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 dark:bg-gray-700 dark:text-gray-200"
                    autoFocus
                    onClick={(e) => e.stopPropagation()}
                  />
                  <button
                    onClick={(e) => { e.stopPropagation(); handleReviseSubmit(); }}
                    disabled={!reviseText.trim()}
                    className="px-3 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg hover:bg-blue-600 disabled:opacity-30 transition-colors"
                  >
                    {t("common.send")}
                  </button>
                </div>
              )}
            </>
          )}
          {verdict === "accepted" && (
            <div className="text-xs text-green-600 font-medium text-center py-1">{t("tool.accepted")}</div>
          )}
          {verdict === "rejected" && (
            <div className="text-xs text-red-400 font-medium text-center py-1">{t("tool.rejected")}</div>
          )}
        </div>
      )}
    </div>
  );
}
