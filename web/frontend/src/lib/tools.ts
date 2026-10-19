import type { IconName } from "../components/Icon";
import type { Step } from "../api";
import { fileName } from "./media";

type T = (key: string, params?: Record<string, string | number>) => string;

export const TOOL_ICONS: Record<string, IconName> = {
  detect_faces_in_image: "scan-face",
  stylize_character: "wand",
  edit_asset: "pencil",
  generate_asset: "image-plus",
  generate_comic_strip: "panels",
  generate_storyboard_strip: "film",
  generate_video_clip: "video",
  merge_video_clips: "clapperboard",
  write_storyboard: "braces",
  read_storyboard: "braces",
  describe_image: "eye",
  draw_with_pil: "pen-tool",
  draft_strip: "clapperboard",
  skill_load: "lightbulb",
  skill_read_resource: "lightbulb",
  review_comic_strip: "list-checks",
  fix_comic_strip: "sparkles",
  fix_comic_text: "pencil",
  read_through: "book",
  write_script: "file-pen",
  update_script: "file-pen",
  read_script: "file-text",
  list_files: "folder-open",
  select_characters: "users",
  select_faces: "smile",
  propose_plan: "list-checks",
  rename_asset: "tag",
  check_jobs: "clock",
};

/** 生成类工具：在后台执行；「生成前确认」模式下要批准；结果图片下面显示 满意 / 删除 / 修改。 */
export const GENERATION_TOOLS = new Set([
  "stylize_character", "generate_asset", "generate_comic_strip", "fix_comic_strip", "edit_asset", "generate_storyboard_strip", "generate_video_clip",
]);

export function toolLabel(tool: string, t: T): string {
  const key = `tool.name.${tool}`;
  const label = t(key);
  return label === key ? tool : label;
}

export function toolStatus(tool: string, t: T): string {
  const key = `tool.status.${tool}`;
  const label = t(key);
  return label === key ? t("tool.status.default") : label;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** review_comic_strip 的结论：pass 可以用 / minor 有小问题 / redo 建议重画 */
export type Verdict = "pass" | "minor" | "redo";
export const isVerdict = (v: unknown): v is Verdict => v === "pass" || v === "minor" || v === "redo";

/** 工具卡片标题后面的简短说明（文件名、第几条…）。 */
export function toolSummary(step: Step, t: T): string {
  const args = step.args || {};
  const result = { ...(step.job?.result || {}), ...(step.result || {}) };
  const output = str(result.output_path) || str(args.output_path);
  switch (step.tool) {
    case "generate_comic_strip":
      return [args.strip_index != null ? t("tool.stripIndex", { index: String(args.strip_index) }) : "", output && fileName(output)]
        .filter(Boolean).join(" · ");
    case "draft_strip":
      return [
        args.strip_index != null ? t("tool.stripIndex", { index: String(args.strip_index) }) : "",
        typeof result.panels === "number" && result.panels > 0 ? t("tool.panelCount", { count: result.panels }) : "",
      ].filter(Boolean).join(" · ");
    case "fix_comic_text":
      return [
        fileName(str(args.image_path)),
        Array.isArray(args.fixes) && args.fixes.length > 0 ? t("tool.fixCount", { count: args.fixes.length }) : "",
      ].filter(Boolean).join(" · ");
    case "fix_comic_strip":
      return [
        fileName(str(args.image_path)),
        Array.isArray(args.fixes) && args.fixes.length > 0 ? t("tool.fixCount", { count: args.fixes.length }) : "",
        args.layout_path ? t("tool.layoutSketch") : "",
      ].filter(Boolean).join(" · ");
    case "read_through":
      return [
        Array.isArray(args.strips) && args.strips.length ? t("tool.readStrips", { count: args.strips.length }) : "",
        !(Array.isArray(args.strips) && args.strips.length) && Array.isArray(args.drafts) && args.drafts.length
          ? t("tool.readDrafts", { count: args.drafts.length }) : "",
        isVerdict(result.verdict) ? t(`review.${result.verdict}`) : "",
      ].filter(Boolean).join(" · ");
    case "review_comic_strip":
      return [
        fileName(str(args.strip_path)),
        isVerdict(result.verdict) ? t(`review.${result.verdict}`) : "",
      ].filter(Boolean).join(" · ");
    case "generate_storyboard_strip":
      return [
        args.strip_index != null ? t("tool.stripIndex", { index: String(args.strip_index) }) : "",
        typeof result.count === "number" ? t("tool.frameCount", { count: result.count }) : "",
      ].filter(Boolean).join(" · ");
    case "generate_video_clip":
      return args.clip_index != null ? t("tool.clipIndex", { index: String(args.clip_index) }) : "";
    case "detect_faces_in_image":
      return typeof result.count === "number" ? t("tool.faceCount", { count: result.count }) : fileName(str(args.image_path));
    case "stylize_character":
      return str(result.character_name) || str(args.character_name);
    case "generate_asset":
    case "edit_asset":
    case "merge_video_clips":
    case "draw_with_pil":
      return output ? fileName(output) : "";
    case "write_script":
    case "update_script":
    case "read_script":
    case "write_storyboard":
    case "read_storyboard":
      return fileName(str(args.file_path));
    case "skill_load":
      return str(args.skill_id);
    case "skill_read_resource":
      return [str(args.skill_id), str(args.path)].filter(Boolean).join("/");
    case "describe_image":
      return str(result.name) || fileName(str(args.image_path));
    case "list_files":
      return fileName(str(args.directory).replace(/\/+$/, "")) || "/";
    case "rename_asset":
      return str(args.name);
    case "check_jobs": {
      const jobs = Array.isArray(result.jobs) ? result.jobs.length : 0;
      return jobs ? t("tool.jobCount", { count: jobs }) : "";
    }
    default:
      return "";
  }
}

/** 工具调用（或它的后台任务）的错误信息。 */
export function toolError(step: Step): string | null {
  const error = step.job?.status === "failed" ? step.job.error || "failed" : step.result?.error;
  if (error == null || error === false) return null;
  return typeof error === "string" ? error : JSON.stringify(error);
}
