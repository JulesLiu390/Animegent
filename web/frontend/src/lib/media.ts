import type { Asset, Assets } from "../api";
import { getFileUrl } from "../api";

const VIDEO_EXTS = [".mp4", ".webm", ".mov"];
const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"];

function extOf(path: string): string {
  const clean = path.split(/[?#]/)[0].toLowerCase();
  const dot = clean.lastIndexOf(".");
  return dot >= 0 ? clean.slice(dot) : "";
}

export const isVideoPath = (path: string) => VIDEO_EXTS.includes(extOf(path));
export const isImagePath = (path: string) => IMAGE_EXTS.includes(extOf(path));

export function fileName(path: string): string {
  const clean = path.split(/[?#]/)[0].replace(/\\/g, "/");
  return clean.slice(clean.lastIndexOf("/") + 1);
}

function safeDecode(value: string): string {
  try {
    return decodeURI(value);
  } catch {
    return value;
  }
}

const encodePath = (path: string) => path.split("/").map((seg) => encodeURIComponent(seg)).join("/");

/**
 * 把模型回复或工具结果里出现的路径换成可以访问的 URL：
 * - http(s)、data:、blob: 原样返回
 * - /files/… 加上 API 前缀
 * - 本机绝对路径（…/projects/<项目>/…）换成 /files/projects/<项目>/…
 * - 相对路径（output/panels/strip_1.png、./style.md）按当前项目解析
 * 无法解析（项目外的路径）时返回 null。
 */
export function resolveMediaUrl(src: string | undefined | null, project?: string | null): string | null {
  const raw = (src || "").trim();
  if (!raw || raw.startsWith("#")) return null;
  if (/^(https?:|data:|blob:|mailto:)/i.test(raw)) return raw;
  if (raw.startsWith("/files/")) return getFileUrl(raw);

  const path = safeDecode(raw).replace(/\\/g, "/");
  if (path.startsWith("/") || /^[a-zA-Z]:\//.test(path)) {
    const marker = project ? `/projects/${project}/` : null;
    let idx = marker ? path.lastIndexOf(marker) : -1;
    if (idx < 0) idx = path.lastIndexOf("/projects/");
    if (idx < 0) return null;
    return getFileUrl(encodePath(`/files${path.slice(idx)}`));
  }
  if (!project) return null;
  let rel = path.replace(/^\.\//, "");
  if (rel.startsWith("../")) return null;
  if (rel.startsWith("projects/")) return getFileUrl(encodePath(`/files/${rel}`));
  rel = rel.replace(/^\/+/, "");
  return getFileUrl(encodePath(`/files/projects/${project}/${rel}`));
}

/** 去掉 ?v= 等参数、统一编码，用来比较两个文件 URL 是否指向同一文件。 */
export function normalizeFileUrl(url: string): string {
  const noQuery = url.split(/[?#]/)[0];
  const idx = noQuery.indexOf("/files/");
  return safeDecode(idx >= 0 ? noQuery.slice(idx) : noQuery);
}

/** 根据 URL 在素材库里找到对应素材（模型回复里的链接点开时直接打开预览）。 */
export function findAssetByUrl(assets: Assets, url: string): { asset: Asset; category: string } | null {
  const target = normalizeFileUrl(url);
  for (const [category, items] of Object.entries(assets)) {
    for (const asset of items) {
      if (normalizeFileUrl(asset.url) === target) return { asset, category };
    }
  }
  return null;
}

export function findAssetByPath(assets: Assets, path: string): { asset: Asset; category: string } | null {
  for (const [category, items] of Object.entries(assets)) {
    const asset = items.find((a) => a.path === path);
    if (asset) return { asset, category };
  }
  return null;
}
