import { useRef, useState } from "react";
import type { MediaItem, Step } from "../api";
import { getFileUrl } from "../api";
import { useLang, useLightbox, useNow } from "../hooks";
import { formatDuration } from "../lib/format";
import { fileName, isVideoPath, resolveMediaUrl } from "../lib/media";
import { GENERATION_TOOLS, TOOL_ICONS, isVerdict, toolError, toolLabel, toolSummary } from "../lib/tools";
import { isJobActive, stepMedia } from "../lib/turns";
import Icon, { Spinner } from "./Icon";

interface Props {
  step: Step;
  busy: boolean;
  /** 当前项目：参数里相对项目目录的路径（版式草图）按它解析 */
  project?: string | null;
  /** 在预览面板里打开项目文件（分镜草稿）；找不到对应素材时返回 false */
  onOpenLink?: (url: string) => boolean;
  /** 「生成前确认」：批准 / 拒绝这次生成 */
  onApprove?: () => void;
  onReject?: () => void;
  /** 生成结果：满意 / 删除 / 修改 */
  onAccept?: () => void;
  onDiscard?: () => void;
  onRevise?: (prompt: string) => void;
  /** 取消还在排队的后台任务 */
  onCancelJob?: () => void;
}

const STOPPED_ERRORS = new Set(["stopped", "用户已停止", "Stopped by the user"]);

/** 旧版保存的视频片段结果里没有带 URL，按 output_path 推出来。 */
function legacyVideo(step: Step): MediaItem | null {
  const output = step.result?.output_path;
  if ((step.tool !== "generate_video_clip" && step.tool !== "merge_video_clips") || typeof output !== "string") return null;
  const idx = output.lastIndexOf("/projects/");
  return idx >= 0 ? { path: output, url: `/files${output.slice(idx)}`, tool: step.tool } : null;
}

const since = (iso?: string | null) => (iso ? Date.parse(iso) : NaN);

type Translate = (key: string, params?: Record<string, string | number>) => string;

interface FixRequest {
  panel?: number;
  area?: string;
  text?: string;
  instruction?: string;
}

/** 批准前给用户看的内容：这次要生成什么（修图时逐条列出要修的地方）。 */
function requestText(step: Step, t: Translate): string {
  const args = step.args || {};
  if (step.tool === "fix_comic_strip") {
    const fixes = (Array.isArray(args.fixes) ? args.fixes : []) as FixRequest[];
    const lines = fixes.map((f, i) => {
      const where = [f.panel ? t("review.panel", { index: f.panel }) : "", f.area ? String(f.area).toUpperCase() : ""].filter(Boolean).join(" · ");
      return `${i + 1}. ${where ? `${where}：` : ""}${f.instruction || ""}${f.text ? ` 「${f.text}」` : ""}`;
    });
    if (args.layout_path) lines.unshift(t("tool.fixLayout"));
    return lines.join("\n");
  }
  const value = args.prompt ?? args.script ?? args.panel_descriptions;
  if (Array.isArray(value)) return value.join(" / ");
  return typeof value === "string" ? value : "";
}

export default function ToolCallCard({ step, busy, project, onOpenLink, onApprove, onReject, onAccept, onDiscard, onRevise, onCancelJob }: Props) {
  const { t } = useLang();
  const openLightbox = useLightbox();
  const [expanded, setExpanded] = useState(false);
  const [revising, setRevising] = useState(false);
  const [reviseText, setReviseText] = useState("");
  const composingRef = useRef(false);

  const tool = step.tool || "";
  const job = step.job;
  const awaiting = step.status === "pending_approval";
  const working = step.status === "running" || isJobActive(job);
  const now = useNow(working);

  const rawError = working || awaiting ? null : toolError(step);
  const stopped = step.status === "cancelled" || (rawError != null && STOPPED_ERRORS.has(rawError));
  // 等批准 / 选择时用户直接发了新消息：这次调用没有执行
  const notRun = step.status === "cancelled" && rawError != null && !STOPPED_ERRORS.has(rawError);
  const error = stopped || step.status === "rejected" ? null : rawError;
  const media = stepMedia(step);
  const images = media.filter((m) => !isVideoPath(m.path));
  const videos = media.filter((m) => isVideoPath(m.path));
  if (videos.length === 0) {
    const legacy = legacyVideo(step);
    if (legacy) videos.push(legacy);
  }
  const verdict = step.verdict || "pending";
  const showVerdict = GENERATION_TOOLS.has(tool) && images.length > 0 && !working && !error;
  const summary = toolSummary(step, t);
  const started = job ? since(job.started_at) : since(step.started_at);
  const elapsed = working
    ? (Number.isNaN(started) ? undefined : now - started)
    : job?.finished_at && job.started_at ? since(job.finished_at) - since(job.started_at) : step.duration_ms ?? undefined;
  const faces = tool === "detect_faces_in_image";
  const request = awaiting ? requestText(step, t) : "";
  // 批准条漫前一起看这一条的版式草图
  // 批准前一起看：要修的图、这一条的版式草图
  const layoutPath = typeof step.args?.layout_path === "string" ? step.args.layout_path : "";
  const basePath = tool === "fix_comic_strip" && typeof step.args?.image_path === "string" ? step.args.image_path : "";
  const previews = awaiting
    ? [{ path: basePath, title: t("tool.fixBase") }, { path: layoutPath, title: t("tool.layoutSketch") }]
      .map((p) => ({ ...p, url: p.path ? resolveMediaUrl(p.path, project) : null }))
      .filter((p): p is { path: string; title: string; url: string } => !!p.url)
    : [];
  const { code, ...otherArgs } = step.args || {};
  // 分镜草稿：写草稿的结果、按草稿生成的条漫
  const draftPath = typeof step.result?.draft_path === "string" ? step.result.draft_path
    : typeof step.args?.draft_path === "string" ? step.args.draft_path : "";
  const draftUrl = draftPath ? resolveMediaUrl(draftPath, project) : null;
  const openDraft = draftUrl && onOpenLink ? () => { if (!onOpenLink(draftUrl)) window.open(draftUrl, "_blank", "noopener"); } : undefined;

  const submitRevise = () => {
    const text = reviseText.trim();
    if (!text) return;
    onRevise?.(text);
    setRevising(false);
    setReviseText("");
  };

  const lightboxItems = images.map((img) => ({ url: getFileUrl(img.url), name: fileName(img.path) }));

  let badge;
  if (awaiting) {
    badge = <span className="chip bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"><Icon name="pause" className="h-2.5 w-2.5" />{t("approval.pending")}</span>;
  } else if (job?.status === "queued") {
    badge = <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"><Icon name="clock" className="h-2.5 w-2.5" />{t("job.queued")}</span>;
  } else if (working) {
    badge = <Spinner className="h-3.5 w-3.5 text-brand-500" />;
  } else if (step.status === "rejected") {
    badge = <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{t("approval.rejected")}</span>;
  } else if (job?.status === "cancelled") {
    badge = <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{t("job.cancelled")}</span>;
  } else if (stopped) {
    badge = <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{t(notRun ? "tool.notRun" : "tool.stopped")}</span>;
  } else if (error) {
    badge = <Icon name="alert-circle" className="h-4 w-4 text-red-500" />;
  } else {
    badge = <Icon name="check" className="h-4 w-4 text-emerald-500" />;
  }

  return (
    <div className={`overflow-hidden rounded-xl border transition-colors ${
      error
        ? "border-red-200 bg-red-50/60 dark:border-red-500/20 dark:bg-red-500/5"
        : awaiting
          ? "border-amber-200 bg-amber-50/40 dark:border-amber-500/25 dark:bg-amber-500/5"
          : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/70"
    }`}>
      <button
        type="button"
        onClick={() => !working && setExpanded(!expanded)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
      >
        <span className={`flex h-6 w-6 items-center justify-center rounded-md ${
          working || awaiting
            ? "bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400"
            : error
              ? "bg-red-100 text-red-500 dark:bg-red-500/15 dark:text-red-400"
              : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
        }`}>
          <Icon name={TOOL_ICONS[tool] || "zap"} className="h-3.5 w-3.5" />
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px]">
          <span className="font-medium text-zinc-800 dark:text-zinc-100">{toolLabel(tool, t)}</span>
          {summary && <span className="ml-2 text-zinc-400 dark:text-zinc-500">{summary}</span>}
          {job?.status === "running" && <span className="ml-2 text-brand-500 dark:text-brand-400">{t("job.running")}</span>}
        </span>
        {elapsed != null && elapsed >= 0 && <span className="shrink-0 font-mono text-[11px] tabular-nums text-zinc-400">{formatDuration(elapsed)}</span>}
        {badge}
        {!working && <Icon name="chevron-down" className={`h-3.5 w-3.5 text-zinc-400 transition-transform ${expanded ? "rotate-180" : ""}`} />}
      </button>

      {awaiting && (
        <div className="px-3 pb-3 pl-[44px]">
          {request && (
            <div className={`mb-2 whitespace-pre-wrap text-xs leading-relaxed text-zinc-600 dark:text-zinc-300 ${tool === "fix_comic_strip" ? "line-clamp-6" : "line-clamp-3"}`}>
              {request}
            </div>
          )}
          {!request && draftPath && (
            <button onClick={openDraft} disabled={!openDraft} className="mb-2 block text-left text-xs text-zinc-600 hover:text-brand-600 hover:underline disabled:no-underline dark:text-zinc-300">
              {t("tool.fromDraft", { name: fileName(draftPath) })}
            </button>
          )}
          {previews.length > 0 && (
            <div className="mb-2 flex gap-2">
              {previews.map((p, i) => (
                <button
                  key={p.path}
                  onClick={() => openLightbox(previews.map((x) => ({ url: x.url, name: fileName(x.path) })), i)}
                  title={p.title}
                  className="block overflow-hidden rounded-md border border-zinc-200 bg-white dark:border-zinc-700"
                >
                  <img src={p.url} alt={p.title} loading="lazy" className="h-28 w-auto" />
                </button>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            <button onClick={onApprove} disabled={busy} className="btn-primary">
              <Icon name="play" className="h-3 w-3" />{t("approval.approve")}
            </button>
            <button onClick={onReject} disabled={busy} className="btn-secondary">{t("approval.reject")}</button>
          </div>
        </div>
      )}

      {job?.status === "queued" && onCancelJob && (
        <div className="px-3 pb-2.5 pl-[44px]">
          <button onClick={onCancelJob} className="text-xs text-zinc-400 hover:text-red-500 hover:underline">{t("job.cancel")}</button>
        </div>
      )}

      {error && (
        <div className="-mt-0.5 whitespace-pre-wrap break-words px-3 pb-2 pl-[44px] text-xs leading-relaxed text-red-600 dark:text-red-400">{error}</div>
      )}

      {tool === "draft_strip" && step.status === "completed" && step.result && (
        <DraftSummary result={step.result} onOpen={openDraft} />
      )}
      {tool === "review_comic_strip" && step.status === "completed" && step.result && <ReviewSummary result={step.result} />}
      {tool === "read_through" && step.status === "completed" && step.result && <ReadThroughSummary result={step.result} />}

      {images.length > 0 && (
        <div className="px-3 pb-3">
          {faces ? (
            <div className="flex flex-wrap gap-1.5">
              {images.map((img, i) => (
                <button key={img.url} onClick={() => openLightbox(lightboxItems, i)} className="h-16 w-16 overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
                  <img src={getFileUrl(img.url)} alt="" loading="lazy" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          ) : images.length === 1 ? (
            <button
              onClick={() => openLightbox(lightboxItems, 0)}
              className={`group relative block overflow-hidden rounded-lg border bg-zinc-50 dark:bg-zinc-950 ${
                verdict === "rejected" ? "border-red-200 opacity-40 dark:border-red-500/30" : verdict === "accepted" ? "border-emerald-300 dark:border-emerald-500/40" : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <img src={getFileUrl(images[0].url)} alt="" loading="lazy" className="max-h-[420px] max-w-full object-contain" />
              <span className="absolute right-2 top-2 rounded-md bg-black/50 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100">
                <Icon name="maximize" className="h-3.5 w-3.5" />
              </span>
            </button>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
              {images.map((img, i) => (
                <button
                  key={img.url}
                  onClick={() => openLightbox(lightboxItems, i)}
                  className={`aspect-square overflow-hidden rounded-lg border bg-zinc-50 transition-opacity dark:bg-zinc-950 ${
                    verdict === "rejected" ? "border-red-200 opacity-40" : "border-zinc-200 hover:opacity-90 dark:border-zinc-800"
                  }`}
                >
                  <img src={getFileUrl(img.url)} alt="" loading="lazy" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {videos.length > 0 && !error && (
        <div className="space-y-2 px-3 pb-3">
          {videos.map((v) => (
            <video key={v.url} src={getFileUrl(v.url)} controls preload="metadata" className="max-h-80 w-full rounded-lg bg-black" />
          ))}
        </div>
      )}

      {showVerdict && (
        <div className="px-3 pb-3">
          {verdict === "pending" ? (
            <>
              <div className="flex flex-wrap gap-1.5">
                <button onClick={onAccept} disabled={busy} className="btn bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:hover:bg-emerald-500/20">
                  <Icon name="check" className="h-3.5 w-3.5" />{t("tool.accept")}
                </button>
                <button onClick={onDiscard} disabled={busy} className="btn-danger-soft">
                  <Icon name="trash" className="h-3.5 w-3.5" />{t("tool.reject")}
                </button>
                <button
                  onClick={() => setRevising(!revising)}
                  disabled={busy}
                  className={revising ? "btn bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300" : "btn-secondary"}
                >
                  <Icon name="pencil" className="h-3.5 w-3.5" />{t("tool.revise")}
                </button>
              </div>
              {revising && (
                <div className="mt-2 flex gap-2">
                  <input
                    autoFocus
                    value={reviseText}
                    onChange={(e) => setReviseText(e.target.value)}
                    onCompositionStart={() => { composingRef.current = true; }}
                    onCompositionEnd={() => { composingRef.current = false; }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !composingRef.current && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        submitRevise();
                      }
                      if (e.key === "Escape") setRevising(false);
                    }}
                    placeholder={t("tool.revisePlaceholder")}
                    className="field min-w-0 flex-1"
                  />
                  <button onClick={submitRevise} disabled={!reviseText.trim() || busy} className="btn-primary">
                    {t("common.send")}
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className={`flex items-center gap-1.5 text-xs font-medium ${
              verdict === "accepted" ? "text-emerald-600 dark:text-emerald-400" : verdict === "revised" ? "text-brand-500 dark:text-brand-400" : "text-zinc-400"
            }`}>
              <Icon name={verdict === "accepted" ? "check" : verdict === "revised" ? "pencil" : "trash"} className="h-3.5 w-3.5" />
              {verdict === "accepted" ? t("tool.accepted") : verdict === "revised" ? t("tool.revised") : t("tool.rejected")}
            </div>
          )}
        </div>
      )}

      {expanded && !working && (
        <div className="space-y-2 border-t border-zinc-100 bg-zinc-50/70 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-950/40">
          {typeof code === "string" ? (
            <>
              <CodeBlock label={t("tool.code")} code={code} />
              <JsonBlock label={t("tool.args")} value={otherArgs} />
            </>
          ) : (
            <JsonBlock label={t("tool.args")} value={step.args || {}} />
          )}
          {step.result && <JsonBlock label={t("tool.result")} value={step.result} />}
          {job?.result && <JsonBlock label={t("job.result")} value={job.result} />}
        </div>
      )}
    </div>
  );
}

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x.trim() !== "") : []);

/** 分镜草稿的摘要：一句话、版式、检查后改了什么、警告。 */
function DraftSummary({ result, onOpen }: { result: Record<string, unknown>; onOpen?: () => void }) {
  const { t } = useLang();
  const summary = typeof result.summary === "string" ? result.summary : "";
  const layout = typeof result.layout === "string" ? result.layout : "";
  const changes = strings(result.changes).filter((c) => c !== "无" && c.toLowerCase() !== "nothing");
  const warnings = strings(result.warnings);
  return (
    <div className="space-y-1 px-3 pb-2.5 pl-[44px] text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">
      {summary && <div>{summary}</div>}
      {layout && <div><span className="text-zinc-400">{t("tool.draftLayout")}</span>{layout}</div>}
      {changes.length > 0 && (
        <div>
          <span className="text-zinc-400">{t("tool.draftChanges")}</span>
          <ul className="ml-4 list-disc">{changes.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}
      {warnings.map((w) => <div key={w} className="text-amber-600 dark:text-amber-400">{w}</div>)}
      {onOpen && (
        <button onClick={onOpen} className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline dark:text-brand-400">
          <Icon name="file-text" className="h-3 w-3" />{t("tool.openDraft")}
        </button>
      )}
    </div>
  );
}

const VERDICT_STYLES = {
  pass: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  minor: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  redo: "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300",
};

interface Problem {
  panel?: number;
  area?: string;
  kind?: string;
  problem?: string;
  action?: string;
  fix?: string;
}

const ACTION_STYLES: Record<string, string> = {
  修图: "bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300",
  重画这一格: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  整条重画: "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300",
};

/** 对照分镜草稿检查成图的结论和问题清单。 */
function ReviewSummary({ result }: { result: Record<string, unknown> }) {
  const { t, lang } = useLang();
  const verdict = isVerdict(result.verdict) ? result.verdict : null;
  const summary = typeof result.summary === "string" ? result.summary : "";
  const problems = (Array.isArray(result.problems) ? result.problems : []).filter(
    (p): p is Problem => typeof p === "object" && p !== null && typeof (p as Problem).problem === "string",
  );
  const colon = lang === "en" ? ": " : "：";
  return (
    <div className="space-y-1.5 px-3 pb-2.5 pl-[44px] text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">
      {(verdict || summary) && (
        <div className="flex items-start gap-2">
          {verdict && <span className={`chip shrink-0 ${VERDICT_STYLES[verdict]}`}>{t(`review.${verdict}`)}</span>}
          {summary && <span>{summary}</span>}
        </div>
      )}
      {problems.length > 0 && (
        <ul className="space-y-1">
          {problems.map((p, i) => (
            <li key={i}>
              <span className="font-medium text-zinc-700 dark:text-zinc-200">
                {p.panel ? t("review.panel", { index: p.panel }) : t("review.wholeStrip")}{p.area ? ` · ${p.area}` : ""}{p.kind ? ` · ${p.kind}` : ""}
              </span>
              {colon}{p.problem}
              {p.fix && <span className="text-zinc-400"> → {p.fix}</span>}
              {p.action && (
                <span className={`chip ml-1.5 ${ACTION_STYLES[p.action] || "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"}`}>{p.action}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface ReadIssue {
  strip?: number;
  panel?: number;
  kind?: string;
  problem?: string;
  target?: string;
  fix?: string;
}

/** 连读的结论：读者复述的故事、跨条的问题和问题的根（总剧本 / 草稿 / 成图）。 */
function ReadThroughSummary({ result }: { result: Record<string, unknown> }) {
  const { t, lang } = useLang();
  const verdict = isVerdict(result.verdict) ? result.verdict : null;
  const story = typeof result.story === "string" ? result.story : "";
  const issues = (Array.isArray(result.issues) ? result.issues : []).filter(
    (i): i is ReadIssue => typeof i === "object" && i !== null && typeof (i as ReadIssue).problem === "string",
  );
  const colon = lang === "en" ? ": " : "：";
  return (
    <div className="space-y-1.5 px-3 pb-2.5 pl-[44px] text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">
      {verdict && <span className={`chip ${VERDICT_STYLES[verdict]}`}>{t(`review.${verdict}`)}</span>}
      {story && (
        <div className="rounded-lg bg-zinc-50 px-2.5 py-2 dark:bg-zinc-900">
          <div className="mb-0.5 text-[11px] text-zinc-400">{t("review.story")}</div>
          <div>{story}</div>
        </div>
      )}
      {issues.length > 0 && (
        <ul className="space-y-1">
          {issues.map((p, i) => (
            <li key={i}>
              <span className="font-medium text-zinc-700 dark:text-zinc-200">
                {p.strip ? t("review.strip", { index: p.strip }) : t("review.wholeStrip")}
                {p.panel ? ` · ${t("review.panel", { index: p.panel })}` : ""}{p.kind ? ` · ${p.kind}` : ""}
              </span>
              {colon}{p.problem}
              {p.fix && <span className="text-zinc-400"> → {p.fix}</span>}
              {p.target && <span className="chip ml-1.5 bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{p.target}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">{label}</div>
      <pre className="max-h-80 overflow-auto rounded-lg border border-zinc-200 bg-white p-2 font-mono text-[11px] leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
        {code}
      </pre>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">{label}</div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-zinc-200 bg-white p-2 font-mono text-[11px] leading-relaxed text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
