import type { AppSettings } from "../api";
import { isRoleConfigured, updateModelSettings } from "../api";
import { useLang, useToast } from "../hooks";
import Icon from "./Icon";

// 服务商的模型列表里通常混着对话模型，这里只列出看起来是视频模型的
const VIDEO_MODEL_RE = /video|veo|sora|kling|hailuo|seedance|vidu|runway|pika|luma|wan2|cogvideo/i;

interface Props {
  settings: AppSettings | null;
  onChange: (settings: AppSettings) => void;
  onOpenSettings: () => void;
  disabled?: boolean;
}

export default function VideoModelSelector({ settings, onChange, onOpenSettings, disabled }: Props) {
  const { t } = useLang();
  const toast = useToast();

  if (!settings || !isRoleConfigured(settings, "video")) {
    return (
      <button
        onClick={onOpenSettings}
        title={t("toolbar.videoModel")}
        className="flex items-center gap-1 rounded-lg bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700 transition-colors hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/20"
      >
        <Icon name="video" className="h-3.5 w-3.5" />
        {t("settings.videoNotSet")}
      </button>
    );
  }

  const current = settings.models.video;
  const provider = settings.providers.find((p) => p.id === current.provider_id);
  const options = Array.from(new Set([current.model, ...(provider?.models || []).filter((m) => VIDEO_MODEL_RE.test(m))]));

  const select = async (model: string) => {
    try {
      onChange(await updateModelSettings({ video: { ...current, model } }));
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  return (
    <label className="relative flex items-center gap-1 rounded-lg bg-zinc-100 py-1 pl-2 pr-1 text-[11px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200" title={`${t("toolbar.videoModel")} · ${provider?.name || ""}`}>
      <Icon name="video" className="h-3.5 w-3.5 text-zinc-400" />
      <select
        value={current.model}
        onChange={(e) => select(e.target.value)}
        disabled={disabled}
        className="max-w-[140px] cursor-pointer appearance-none truncate bg-transparent pr-4 font-medium focus:outline-none disabled:opacity-50"
      >
        {options.map((model) => (
          <option key={model} value={model}>{model}</option>
        ))}
      </select>
      <Icon name="chevron-down" className="pointer-events-none absolute right-1 h-3 w-3 text-zinc-400" />
    </label>
  );
}
