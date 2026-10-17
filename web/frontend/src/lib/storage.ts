/** localStorage 读写：隐私模式等情况下可能不可用，失败时忽略。 */
export function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore
  }
}

export function readJson<T>(key: string, fallback: T): T {
  const raw = readStorage(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown) {
  writeStorage(key, JSON.stringify(value));
}

export const RECENT_PROJECTS_KEY = "anidaily-recent-projects";

/** 记录最近打开的项目（项目切换菜单里显示）。 */
export function pushRecentProject(name: string) {
  const list = readJson<string[]>(RECENT_PROJECTS_KEY, []).filter((n) => n !== name);
  writeJson(RECENT_PROJECTS_KEY, [name, ...list].slice(0, 8));
}
