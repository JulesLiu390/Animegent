import { useCallback, useEffect, useRef, useState } from "react";
import type { AppSettings, Asset, Assets, Project } from "./api";
import {
  createProject, deleteAsset, deleteProject, fetchAssets, fetchProjects, fetchSettings, isRoleConfigured, isStoryboardEnabled, renameProject,
} from "./api";
import AssetSidebar from "./components/AssetSidebar";
import ChatPanel, { type ChatPanelHandle } from "./components/ChatPanel";
import ConfirmDialog from "./components/ConfirmDialog";
import Icon from "./components/Icon";
import { LightboxProvider } from "./components/Lightbox";
import PreviewPanel from "./components/PreviewPanel";
import ProjectSelector from "./components/ProjectSelector";
import PromptDialog from "./components/PromptDialog";
import SettingsModal from "./components/SettingsModal";
import type { SettingsTab } from "./components/SettingsModal";
import { ToastProvider } from "./components/Toast";
import WelcomePage from "./components/WelcomePage";
import { useLang, useToast } from "./hooks";
import { LanguageProvider } from "./LanguageContext";
import { assetToAttachment } from "./lib/turns";
import { errorText } from "./lib/errors";
import { findAssetByPath, findAssetByUrl } from "./lib/media";
import { pushRecentProject, readStorage, writeStorage } from "./lib/storage";

const LAST_PROJECT_KEY = "animegent-last-project";
const SIDEBAR_KEY = "animegent-sidebar";
const conversationKey = (project: string) => `animegent-last-conversation:${project}`;

function AppInner() {
  const { lang, setLang, dark, setDark, t } = useLang();
  const toast = useToast();
  // 切换语言不应该让下面依赖它的加载逻辑重新执行，所以用 ref 拿最新的 t
  const tRef = useRef(t);
  useEffect(() => { tRef.current = t; }, [t]);
  const errorMessage = useCallback((err: unknown) => errorText(err, tRef.current), []);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [currentProject, setCurrentProject] = useState<string | null>(null);
  const currentProjectRef = useRef<string | null>(null);
  const [assets, setAssets] = useState<Assets>({});
  const assetsRef = useRef<Assets>({});
  useEffect(() => { assetsRef.current = assets; }, [assets]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsRefreshing, setAssetsRefreshing] = useState(false);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
  // 窄屏下素材库盖在对话上面，默认收起
  const [sidebarOpen, setSidebarOpen] = useState(() => readStorage(SIDEBAR_KEY) !== "closed" && window.innerWidth >= 768);
  const [chatBusy, setChatBusy] = useState(false);
  // undefined：没有待确认的切换；null：回到首页
  const [pendingProject, setPendingProject] = useState<string | null | undefined>(undefined);
  const [creating, setCreating] = useState(false);
  const [deletePreview, setDeletePreview] = useState<Asset | null>(null);
  const chatRef = useRef<ChatPanelHandle>(null);

  // ---------- 数据 ----------

  const assetsSeq = useRef(0);
  const loadAssets = useCallback(async (project: string | null, initial = false) => {
    const seq = ++assetsSeq.current;
    if (!project) return;
    if (initial) setAssetsLoading(true);
    else setAssetsRefreshing(true);
    try {
      const data = await fetchAssets(project);
      if (seq === assetsSeq.current) setAssets(data);
    } catch (err) {
      if (seq === assetsSeq.current && initial) toast(errorMessage(err), "error");
    } finally {
      if (seq === assetsSeq.current) {
        setAssetsLoading(false);
        setAssetsRefreshing(false);
      }
    }
  }, [errorMessage, toast]);

  const refreshTimer = useRef<number | undefined>(undefined);
  /** 工具执行完会频繁触发：合并成一次刷新。 */
  const scheduleAssetsRefresh = useCallback(() => {
    window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => loadAssets(currentProjectRef.current), 400);
  }, [loadAssets]);

  const loadProjects = useCallback(async () => {
    try {
      const list = await fetchProjects();
      setProjects(list);
      return list;
    } catch (err) {
      toast(errorMessage(err), "error");
      return null;
    } finally {
      setProjectsLoading(false);
    }
  }, [errorMessage, toast]);

  const switchProject = useCallback((name: string | null) => {
    currentProjectRef.current = name;
    setCurrentProject(name);
    setAssets({});
    setPreviewPath(null);
    if (name) {
      writeStorage(LAST_PROJECT_KEY, name);
      pushRecentProject(name);
      loadAssets(name, true);
    } else {
      writeStorage(LAST_PROJECT_KEY, "");
    }
  }, [loadAssets]);

  useEffect(() => {
    fetchSettings().then(setSettings).catch((err) => toast(errorMessage(err), "error"));
    let cancelled = false;
    fetchProjects()
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
        // 刷新页面后回到上次打开的项目
        const last = readStorage(LAST_PROJECT_KEY);
        if (last && list.some((p) => p.name === last)) switchProject(last);
      })
      .catch((err) => toast(errorMessage(err), "error"))
      .finally(() => { if (!cancelled) setProjectsLoading(false); });
    return () => { cancelled = true; };
  }, [errorMessage, switchProject, toast]);

  // ---------- 项目 ----------

  const requestProject = (name: string | null) => {
    if (name === currentProject) return;
    if (chatBusy) setPendingProject(name);
    else if (name === null) goHome();
    else switchProject(name);
  };

  const goHome = () => {
    switchProject(null);
    loadProjects();
  };

  const handleCreateProject = async (name: string) => {
    try {
      const res = await createProject(name);
      await loadProjects();
      switchProject(res.name);
      if (res.created) toast(t("project.created", { name: res.name }), "success");
      setCreating(false);
    } catch (err) {
      toast(errorMessage(err), "error");
      throw err;
    }
  };

  const handleRenameProject = async (oldName: string, newName: string) => {
    try {
      const res = await renameProject(oldName, newName);
      if (!res.renamed || !res.new_name) throw new Error(res.error || "rename failed");
      // 改名后对话还在，接着打开同一个对话
      writeStorage(conversationKey(res.new_name), readStorage(conversationKey(oldName)) || "");
      await loadProjects();
      switchProject(res.new_name);
      toast(t("project.renamed", { name: res.new_name }), "success");
    } catch (err) {
      toast(errorMessage(err), "error");
      throw err;
    }
  };

  const handleDeleteProject = async (name: string) => {
    try {
      const res = await deleteProject(name);
      if (res.deleted === false) throw new Error(res.error || "delete failed");
      if (name === currentProject) switchProject(null);
      await loadProjects();
      toast(t("project.deleted", { name }), "success");
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  // ---------- 素材 ----------

  const preview = previewPath ? findAssetByPath(assets, previewPath) : null;

  const openAsset = (asset: Asset) => setPreviewPath((prev) => (prev === asset.path ? null : asset.path));

  const previewByPath = useCallback((path: string) => {
    if (!findAssetByPath(assetsRef.current, path)) return false;
    setPreviewPath(path);
    return true;
  }, []);

  const openLink = useCallback((url: string) => {
    const found = findAssetByUrl(assetsRef.current, url);
    if (!found) return false;
    setPreviewPath(found.asset.path);
    return true;
  }, []);

  const addToChat = (asset: Asset) => chatRef.current?.addAttachments([assetToAttachment(asset)]);

  const removeAssetLocally = (path: string) => {
    setAssets((prev) => {
      const next: Assets = {};
      for (const [cat, items] of Object.entries(prev)) next[cat] = items.filter((a) => a.path !== path);
      return next;
    });
    if (previewPath === path) setPreviewPath(null);
    scheduleAssetsRefresh();
  };

  const confirmDeletePreview = async () => {
    const target = deletePreview;
    setDeletePreview(null);
    if (!target) return;
    try {
      const res = await deleteAsset(target.path);
      if (res.deleted === false) throw new Error(res.error || "delete failed");
      removeAssetLocally(target.path);
      toast(t("sidebar.deleted"), "success");
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  const toggleSidebar = () => {
    setSidebarOpen((open) => {
      writeStorage(SIDEBAR_KEY, open ? "closed" : "open");
      return !open;
    });
  };

  const openSettings = useCallback((tab?: SettingsTab) => setSettingsTab(tab ?? "models"), []);
  const chatConfigured = settings ? isRoleConfigured(settings, "chat") : true;
  const rememberConversation = useCallback((id: string | null) => {
    if (currentProjectRef.current) writeStorage(conversationKey(currentProjectRef.current), id || "");
  }, []);

  return (
    <div className="flex h-full flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      {/* Top bar */}
      <header className="relative z-30 flex h-12 shrink-0 items-center gap-1.5 border-b border-zinc-200/80 bg-white/80 px-3 backdrop-blur dark:border-zinc-800/80 dark:bg-zinc-900/70">
        <button onClick={() => requestProject(null)} className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800" title={t("app.home")}>
          <img src="/logo-64.png" alt="" className="h-7 w-7 rounded-[22%]" />
          <span className="hidden text-sm font-semibold tracking-tight sm:inline">Animegent</span>
        </button>
        <span className="select-none text-zinc-300 dark:text-zinc-700">/</span>
        <ProjectSelector
          projects={projects}
          current={currentProject}
          onSelect={(name) => requestProject(name)}
          onCreate={handleCreateProject}
          onRename={handleRenameProject}
          onDelete={handleDeleteProject}
          onOpen={loadProjects}
        />
        <div className="flex-1" />
        <button
          onClick={() => openSettings(settings?.providers.length === 0 ? "providers" : "models")}
          className="relative flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
          title={t("settings.title")}
        >
          <Icon name="settings" className="h-4 w-4" />
          <span className="hidden sm:inline">{t("settings.title")}</span>
          {!chatConfigured && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-white dark:ring-zinc-900" />}
        </button>
        <button onClick={() => setDark(!dark)} className="icon-btn" title={dark ? t("app.themeLight") : t("app.themeDark")}>
          <Icon name={dark ? "sun" : "moon"} className="h-4 w-4" />
        </button>
        <button
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          className="flex h-8 min-w-8 items-center justify-center rounded-lg px-1.5 text-xs font-semibold text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          title={t("app.language")}
        >
          {lang === "zh" ? "EN" : "中"}
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {currentProject && sidebarOpen && (
          <div className="absolute inset-0 z-10 animate-fade-in bg-zinc-950/30 md:hidden" onClick={toggleSidebar} />
        )}
        {currentProject && sidebarOpen && (
          <div className="absolute inset-y-0 left-0 z-20 shadow-pop md:static md:shadow-none">
            <AssetSidebar
              assets={assets}
              loading={assetsLoading}
              refreshing={assetsRefreshing}
              selectedPath={previewPath}
              onRefresh={() => loadAssets(currentProject)}
              onAssetClick={openAsset}
              onAddToChat={addToChat}
              onDeleted={removeAssetLocally}
              onCollapse={toggleSidebar}
            />
          </div>
        )}
        <main className="min-w-0 flex-1">
          {currentProject ? (
            <ChatPanel
              key={currentProject}
              ref={chatRef}
              project={currentProject}
              initialConversationId={readStorage(conversationKey(currentProject)) || null}
              onConversationChange={rememberConversation}
              onAssetsChanged={scheduleAssetsRefresh}
              onPreviewPath={previewByPath}
              onOpenLink={openLink}
              settings={settings}
              onSettingsChange={setSettings}
              onOpenSettings={openSettings}
              onBusyChange={setChatBusy}
              sidebarOpen={sidebarOpen}
              onToggleSidebar={toggleSidebar}
            />
          ) : (
            <WelcomePage
              projects={projects}
              loading={projectsLoading}
              chatConfigured={chatConfigured}
              storyboard={isStoryboardEnabled(settings)}
              onSelectProject={(name) => requestProject(name)}
              onCreateProject={() => setCreating(true)}
              onOpenSettings={() => openSettings(settings?.providers.length === 0 ? "providers" : "models")}
            />
          )}
        </main>
        {currentProject && preview && (
          <div className="absolute inset-0 z-10 animate-fade-in bg-zinc-950/30 lg:hidden" onClick={() => setPreviewPath(null)} />
        )}
        {currentProject && preview && (
          <div className="absolute inset-y-0 right-0 z-20 shadow-pop lg:static lg:shadow-none">
            <PreviewPanel
              key={preview.asset.path}
              asset={preview.asset}
              category={preview.category}
              project={currentProject}
              onClose={() => setPreviewPath(null)}
              onSendToChat={() => addToChat(preview.asset)}
              onSaved={() => loadAssets(currentProject)}
              onDelete={preview.category === "style" || preview.asset.readonly ? undefined : () => setDeletePreview(preview.asset)}
              onOpenLink={openLink}
            />
          </div>
        )}
      </div>

      {settingsTab && (
        <SettingsModal
          settings={settings}
          onChange={setSettings}
          onClose={() => setSettingsTab(null)}
          initialTab={settingsTab}
        />
      )}
      {pendingProject !== undefined && (
        <ConfirmDialog
          title={t("app.busyTitle")}
          message={t("app.busySwitch")}
          confirmLabel={t("app.stopAndSwitch")}
          onConfirm={() => {
            const target = pendingProject;
            setPendingProject(undefined);
            if (target === null) goHome();
            else switchProject(target);
          }}
          onCancel={() => setPendingProject(undefined)}
        />
      )}
      {creating && (
        <PromptDialog
          title={t("project.createNew")}
          placeholder={t("project.namePlaceholder")}
          confirmLabel={t("project.create")}
          onConfirm={handleCreateProject}
          onCancel={() => setCreating(false)}
        />
      )}
      {deletePreview && (
        <ConfirmDialog
          title={t("sidebar.deleteTitle")}
          message={t("sidebar.deleteConfirm", { name: deletePreview.title || deletePreview.name })}
          confirmLabel={t("common.delete")}
          onConfirm={confirmDeletePreview}
          onCancel={() => setDeletePreview(null)}
        />
      )}
    </div>
  );
}

function App() {
  return (
    <LanguageProvider>
      <ToastProvider>
        <LightboxProvider>
          <AppInner />
        </LightboxProvider>
      </ToastProvider>
    </LanguageProvider>
  );
}

export default App;
