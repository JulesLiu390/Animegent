type T = (key: string, params?: Record<string, string | number>) => string;

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function timeAgo(date: string | number | Date, t: T, lang: string): string {
  const d = new Date(date);
  const diff = Date.now() - d.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t("time.now");
  if (minutes < 60) return t("time.minutes", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("time.hours", { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t("time.days", { n: days });
  return d.toLocaleDateString(lang === "en" ? "en-US" : "zh-CN", { month: "short", day: "numeric" });
}

/** 文件名里带数字时按数字大小排序（strip_2 在 strip_10 前面）。 */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}
