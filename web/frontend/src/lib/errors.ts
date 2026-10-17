type T = (key: string, params?: Record<string, string | number>) => string;

/** fetch 本身失败（后端没启动、断网）时浏览器只给 "Failed to fetch"，换成能看懂的提示。 */
export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError && /fetch|network|load failed/i.test(err.message);
}

export function errorText(err: unknown, t: T): string {
  if (isNetworkError(err)) return t("app.backendDown");
  return err instanceof Error ? err.message : String(err);
}
