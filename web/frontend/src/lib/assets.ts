import type { IconName } from "../components/Icon";

/** 从素材库拖进对话框时 dataTransfer 里的类型。 */
export const DRAG_ASSET_TYPE = "application/x-animegent-asset";

export type Layout = "list" | "grid2" | "grid3" | "grid4";

export interface CategoryInfo {
  label: string;
  icon: IconName;
  layout: Layout;
  aspect?: string;
  fit?: string;
}

// 显示顺序 = 一般的创作流程
export const CATEGORIES: Record<string, CategoryInfo> = {
  style: { label: "cat.style", icon: "palette", layout: "list" },
  skills: { label: "cat.skills", icon: "lightbulb", layout: "list" },
  originals: { label: "cat.input", icon: "image", layout: "grid3", aspect: "aspect-square" },
  faces: { label: "cat.faces", icon: "smile", layout: "grid4", aspect: "aspect-square" },
  characters: { label: "cat.stylized", icon: "user", layout: "grid3", aspect: "aspect-[3/4]", fit: "object-top" },
  scenes: { label: "cat.scenes_stylized", icon: "image", layout: "grid2", aspect: "aspect-video" },
  scenes_raw: { label: "cat.scenes_no_people", icon: "image", layout: "grid2", aspect: "aspect-video" },
  scripts: { label: "cat.scripts", icon: "book", layout: "list" },
  drafts: { label: "cat.drafts", icon: "clapperboard", layout: "list" },
  layouts: { label: "cat.layouts", icon: "pen-tool", layout: "grid3", aspect: "aspect-[9/16]", fit: "object-top" },
  panels: { label: "cat.panels", icon: "panels", layout: "grid2", aspect: "aspect-[9/16]", fit: "object-top" },
  storyboards: { label: "cat.storyboards", icon: "braces", layout: "list" },
  storyboard_strips: { label: "cat.storyboard_strips", icon: "film", layout: "grid2", aspect: "aspect-[9/16]", fit: "object-top" },
  storyboard_frames: { label: "cat.storyboard_frames", icon: "image", layout: "grid2", aspect: "aspect-video" },
  clip_scripts: { label: "cat.clip_scripts", icon: "file-text", layout: "list" },
  clips: { label: "cat.clips", icon: "video", layout: "grid2", aspect: "aspect-video" },
  final_videos: { label: "cat.final_videos", icon: "clapperboard", layout: "grid2", aspect: "aspect-video" },
};
