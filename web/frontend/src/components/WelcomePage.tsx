import type { Project } from "../api";
import { getFileUrl } from "../api";
import { useLang } from "../hooks";
import { timeAgo } from "../lib/format";
import type { IconName } from "./Icon";
import Icon from "./Icon";

interface Props {
  projects: Project[];
  loading: boolean;
  chatConfigured: boolean;
  /** 分镜模式是否开放（休眠时文案里不提视频） */
  storyboard: boolean;
  onSelectProject: (name: string) => void;
  onCreateProject: () => void;
  onOpenSettings: () => void;
}

const STEPS: { icon: IconName; title: string; storyboardTitle?: string; desc: string }[] = [
  { icon: "scan-face", title: "welcome.step1", desc: "welcome.step1Desc" },
  { icon: "book", title: "welcome.step2", desc: "welcome.step2Desc" },
  { icon: "panels", title: "welcome.step3", storyboardTitle: "welcome.step3Storyboard", desc: "welcome.step3Desc" },
];

export default function WelcomePage({ projects, loading, chatConfigured, storyboard, onSelectProject, onCreateProject, onOpenSettings }: Props) {
  const { t, lang } = useLang();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-6 pb-16 pt-12 sm:px-10">
        {/* Hero */}
        <div className="flex flex-col items-center text-center">
          <div className="relative mb-5">
            <div className="absolute -inset-4 rounded-[2rem] bg-gradient-to-br from-brand-300/50 via-fuchsia-300/30 to-sky-300/40 blur-2xl dark:from-brand-500/30 dark:via-fuchsia-500/20 dark:to-sky-500/20" />
            <img src="/logo-256.png" alt="Animegent" className="relative h-20 w-20 rounded-[22%] shadow-soft" />
          </div>
          <h1 className="bg-gradient-to-r from-zinc-900 via-brand-600 to-zinc-900 bg-clip-text text-3xl font-bold tracking-tight text-transparent dark:from-white dark:via-brand-300 dark:to-white sm:text-4xl">
            Animegent
          </h1>
          <p className="mt-2 max-w-md text-sm text-zinc-500 dark:text-zinc-400">{t(storyboard ? "app.taglineStoryboard" : "app.tagline")}</p>
        </div>

        <div className="mx-auto mt-8 grid max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
          {STEPS.map((step, i) => (
            <div key={step.title} className="flex items-start gap-3 rounded-xl border border-zinc-200/80 bg-white/70 px-3.5 py-3 dark:border-zinc-800 dark:bg-zinc-900/50">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400">
                <Icon name={step.icon} className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-100">
                  <span className="mr-1 text-zinc-400">{i + 1}.</span>{t(storyboard && step.storyboardTitle ? step.storyboardTitle : step.title)}
                </div>
                <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{t(step.desc)}</div>
              </div>
            </div>
          ))}
        </div>

        {!chatConfigured && (
          <div className="mx-auto mt-6 flex max-w-3xl items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/20 dark:bg-amber-500/10">
            <Icon name="key" className="h-5 w-5 text-amber-500" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-amber-900 dark:text-amber-100">{t("welcome.setupTitle")}</div>
              <div className="text-xs text-amber-800/80 dark:text-amber-200/80">{t("welcome.setupDesc")}</div>
            </div>
            <button onClick={onOpenSettings} className="btn bg-amber-500 text-white shadow-sm hover:bg-amber-600">
              <Icon name="settings" className="h-3.5 w-3.5" />{t("welcome.setupAction")}
            </button>
          </div>
        )}

        {/* Projects */}
        <div className="mt-12 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{t("welcome.projects")}</h2>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{t("welcome.newProjectHint")}</p>
          </div>
          <button onClick={onCreateProject} className="btn-primary">
            <Icon name="plus" className="h-3.5 w-3.5" strokeWidth={2.5} />{t("welcome.newProject")}
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {loading && projects.length === 0 ? (
            [0, 1, 2, 3].map((i) => (
              <div key={i}>
                <div className="skeleton aspect-[4/3] rounded-xl" />
                <div className="skeleton mt-2 h-3 w-2/3" />
              </div>
            ))
          ) : (
            <>
              <button
                onClick={onCreateProject}
                className="group flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-zinc-200 text-zinc-400 transition-colors hover:border-brand-300 hover:bg-brand-50/50 hover:text-brand-500 dark:border-zinc-800 dark:hover:border-brand-500/40 dark:hover:bg-brand-500/5"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 transition-colors group-hover:bg-brand-100 dark:bg-zinc-800 dark:group-hover:bg-brand-500/15">
                  <Icon name="plus" className="h-5 w-5" />
                </span>
                <span className="text-sm font-medium">{t("welcome.newProject")}</span>
              </button>
              {projects.map((project) => (
                <button key={project.name} onClick={() => onSelectProject(project.name)} className="group min-w-0 text-left">
                  <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-zinc-200 bg-zinc-100 shadow-sm transition-all group-hover:-translate-y-0.5 group-hover:border-brand-300 group-hover:shadow-soft dark:border-zinc-800 dark:bg-zinc-900 dark:group-hover:border-brand-500/40">
                    {project.cover ? (
                      <img src={getFileUrl(project.cover)} alt="" loading="lazy" className="h-full w-full object-cover object-top transition-transform duration-300 group-hover:scale-[1.03]" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-brand-50 via-white to-sky-50 text-brand-300 dark:from-brand-500/10 dark:via-zinc-900 dark:to-sky-500/10 dark:text-brand-500/40">
                        <Icon name="folder" className="h-10 w-10" strokeWidth={1.5} />
                      </div>
                    )}
                  </div>
                  <div className="mt-2 px-0.5">
                    <div className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">{project.name}</div>
                    <div className="mt-0.5 truncate text-[11px] text-zinc-400">
                      {project.image_count ? t("welcome.images", { count: project.image_count }) : t("welcome.noImages")}
                      {project.updated_at && ` · ${timeAgo(project.updated_at, t, lang)}`}
                    </div>
                  </div>
                </button>
              ))}
            </>
          )}
        </div>

        {!loading && projects.length === 0 && (
          <p className="mt-6 text-center text-sm text-zinc-400">{t("welcome.noProjects")}</p>
        )}
      </div>
    </div>
  );
}
