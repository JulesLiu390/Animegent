import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { ApiFormat, AppSettings, ModelAssignment, ModelRole, ProviderInfo, ProviderInput, ProviderProbe } from "../api";
import {
  createProvider, deleteProvider, fetchProviderModels, isStoryboardEnabled, testProvider, updateModelSettings, updateProvider,
} from "../api";
import { useLang, useToast } from "../hooks";
import ConfirmDialog from "./ConfirmDialog";
import type { IconName } from "./Icon";
import Icon, { Spinner } from "./Icon";
import Modal from "./Modal";

export type SettingsTab = "models" | "providers";

interface Props {
  settings: AppSettings | null;
  onChange: (settings: AppSettings) => void;
  onClose: () => void;
  initialTab?: SettingsTab;
}

const ROLES: ModelRole[] = ["chat", "vision", "image", "video"];

// 视频模型只在分镜模式里用：分镜休眠时不显示（已保存的配置仍留在 settings.json 里）
const visibleRoles = (settings: AppSettings) => ROLES.filter((role) => role !== "video" || isStoryboardEnabled(settings));

const ROLE_ICONS: Record<ModelRole, IconName> = {
  chat: "message",
  vision: "eye",
  image: "image",
  video: "video",
};

const FORMAT_LABEL_KEYS: Record<ApiFormat, string> = {
  openai_compatible: "settings.formatOpenai",
  gemini_official: "settings.formatGemini",
  anthropic_native: "settings.formatAnthropic",
};

// 常用服务商地址（选中后填入 Base URL，可再手动修改）
const PRESETS: Record<ApiFormat, { label: string; url: string }[]> = {
  openai_compatible: [
    { label: "OpenAI", url: "https://api.openai.com/v1" },
    { label: "DeepSeek", url: "https://api.deepseek.com/v1" },
    { label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
    { label: "云雾 yunwu.ai", url: "https://yunwu.ai/v1" },
    { label: "硅基流动 SiliconFlow", url: "https://api.siliconflow.cn/v1" },
    { label: "阿里云百炼", url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
    { label: "火山方舟", url: "https://ark.cn-beijing.volces.com/api/v3" },
    { label: "Moonshot (Kimi)", url: "https://api.moonshot.cn/v1" },
    { label: "智谱 GLM", url: "https://open.bigmodel.cn/api/paas/v4" },
    { label: "xAI (Grok)", url: "https://api.x.ai/v1" },
    { label: "Groq", url: "https://api.groq.com/openai/v1" },
    { label: "Ollama (Local)", url: "http://localhost:11434/v1" },
    { label: "LM Studio (Local)", url: "http://localhost:1234/v1" },
  ],
  gemini_official: [
    { label: "Google AI Studio", url: "https://generativelanguage.googleapis.com" },
    { label: "云雾 yunwu.ai", url: "https://yunwu.ai" },
  ],
  anthropic_native: [
    { label: "Anthropic", url: "https://api.anthropic.com/v1" },
  ],
};

const fieldClass = "field";
const inputClass = "field w-full";
const secondaryButton = "btn-secondary";
const primaryButton = "btn-primary px-4";

const parseKeys = (raw: string) => raw.split(/[\n,]/).map((k) => k.trim()).filter(Boolean);
const mergeModels = (current: string[], extra: string[]) => Array.from(new Set([...current, ...extra])).sort();
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** 按 Key 前缀猜服务商（新建时自动填 API 格式和地址）。 */
function detectFromKey(raw: string): { format: ApiFormat; name: string; url: string } | null {
  const key = parseKeys(raw)[0] || "";
  if (key.startsWith("sk-ant-")) return { format: "anthropic_native", name: "Anthropic", url: "https://api.anthropic.com/v1" };
  if (key.startsWith("AIza")) return { format: "gemini_official", name: "Google Gemini", url: "https://generativelanguage.googleapis.com" };
  if (key.startsWith("sk-or-")) return { format: "openai_compatible", name: "OpenRouter", url: "https://openrouter.ai/api/v1" };
  if (key.startsWith("gsk_")) return { format: "openai_compatible", name: "Groq", url: "https://api.groq.com/openai/v1" };
  if (key.startsWith("xai-")) return { format: "openai_compatible", name: "xAI", url: "https://api.x.ai/v1" };
  return null;
}

// 用 div 而不是 label 包裹：label 会把点击转给里面第一个按钮（例如误删模型标签）
// 和后端 settings.py 的 DEFAULT_CONCURRENCY / MAX_CONCURRENCY 一致
const DEFAULT_CONCURRENCY = 3;
const MAX_CONCURRENCY = 16;
const clampConcurrency = (value: number) =>
  Number.isFinite(value) ? Math.min(MAX_CONCURRENCY, Math.max(1, Math.round(value))) : DEFAULT_CONCURRENCY;

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="block min-w-0">
      <div className="mb-1 text-[11px] font-medium text-zinc-500 dark:text-zinc-400">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[11px] leading-snug text-zinc-400">{hint}</div>}
    </div>
  );
}

function StatusText({ status }: { status: { ok: boolean; text: string } | null }) {
  if (!status) return null;
  return (
    <div
      className={`flex min-w-0 items-start gap-1.5 whitespace-pre-line break-words rounded-lg px-2.5 py-1.5 text-[11px] leading-relaxed ${
        status.ok
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
          : "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300"
      }`}
    >
      <Icon name={status.ok ? "check" : "alert-circle"} className="mt-px h-3.5 w-3.5" />
      <span className="min-w-0">{status.text}</span>
    </div>
  );
}

export default function SettingsModal({ settings, onChange, onClose, initialTab }: Props) {
  const { t } = useLang();
  const [tab, setTab] = useState<SettingsTab>(
    initialTab || (settings && settings.providers.length === 0 ? "providers" : "models"),
  );
  const [creating, setCreating] = useState(false);
  const [modelsDirty, setModelsDirty] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);

  const requestClose = () => {
    if (modelsDirty) setConfirmClose(true);
    else onClose();
  };

  const tabs: { value: SettingsTab; label: string; icon: IconName }[] = [
    { value: "models", label: t("settings.tabModels"), icon: "bot" },
    { value: "providers", label: t("settings.tabProviders"), icon: "server" },
  ];

  return (
    <Modal onClose={requestClose} closeOnBackdrop={false} className="flex h-[min(760px,88vh)] max-w-3xl flex-col overflow-hidden" labelledBy="settings-title">
      <div className="flex shrink-0 items-center gap-4 border-b border-zinc-200 px-5 py-3.5 dark:border-zinc-800">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400">
            <Icon name="settings" className="h-[18px] w-[18px]" />
          </span>
          <div>
            <h2 id="settings-title" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{t("settings.title")}</h2>
            <div className="text-[11px] text-zinc-400">{t("settings.subtitle")}</div>
          </div>
        </div>
        <div className="flex items-center rounded-lg bg-zinc-100 p-0.5 dark:bg-zinc-800">
          {tabs.map((item) => (
            <button
              key={item.value}
              onClick={() => { setTab(item.value); setCreating(false); }}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-all ${
                tab === item.value
                  ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-700 dark:text-zinc-50"
                  : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              <Icon name={item.icon} className="h-3.5 w-3.5" />
              {item.label}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        <button onClick={requestClose} className="icon-btn" title={t("common.close")}>
          <Icon name="x" className="h-[18px] w-[18px]" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {!settings ? (
          <div className="flex justify-center py-12 text-brand-500"><Spinner className="h-5 w-5" /></div>
        ) : tab === "models" ? (
          <ModelsTab
            settings={settings}
            onChange={onChange}
            onDirtyChange={setModelsDirty}
            onAddProvider={() => { setTab("providers"); setCreating(true); }}
          />
        ) : (
          <ProvidersTab
            key={creating ? "creating" : "list"}
            settings={settings}
            onChange={onChange}
            startCreating={creating}
          />
        )}
      </div>

      {confirmClose && (
        <ConfirmDialog
          message={t("settings.unsavedClose")}
          confirmLabel={t("common.close")}
          onConfirm={() => { setConfirmClose(false); onClose(); }}
          onCancel={() => setConfirmClose(false)}
        />
      )}
    </Modal>
  );
}

// ==================== 模型分配 ====================

function ModelsTab({ settings, onChange, onAddProvider, onDirtyChange }: {
  settings: AppSettings;
  onChange: (settings: AppSettings) => void;
  onAddProvider: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useLang();
  const toast = useToast();
  // 外部改了设置（例如在输入框旁边切换了视频模型）时重置草稿
  const [base, setBase] = useState(settings.models);
  const [draft, setDraft] = useState(settings.models);
  if (base !== settings.models) {
    setBase(settings.models);
    setDraft(settings.models);
  }
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.models);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);

  const update = (role: ModelRole, patch: Partial<ModelAssignment>) => {
    setDraft((prev) => ({ ...prev, [role]: { ...prev[role], ...patch } }));
    setError(null);
  };

  const save = async () => {
    setSaving(true);
    try {
      onChange(await updateModelSettings(draft));
      toast(t("settings.saved"), "success");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  if (settings.providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-500 dark:bg-brand-500/10">
          <Icon name="server" className="h-6 w-6" />
        </div>
        <div className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">{t("settings.noProviders")}</div>
        <button onClick={onAddProvider} className={primaryButton}>
          <Icon name="plus" className="h-3.5 w-3.5" strokeWidth={2.5} />{t("settings.addProvider")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {visibleRoles(settings).map((role) => (
        <RoleCard
          key={role}
          role={role}
          value={draft[role]}
          providers={settings.providers}
          onChange={(patch) => update(role, patch)}
        />
      ))}
      <div className="sticky bottom-0 -mx-5 -mb-4 flex items-center justify-end gap-3 border-t border-zinc-100 bg-white/95 px-5 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
        {error && <StatusText status={{ ok: false, text: error }} />}
        {dirty && !error && <span className="text-[11px] text-amber-600 dark:text-amber-400">{t("preview.unsaved")}</span>}
        <button onClick={() => setDraft(settings.models)} disabled={!dirty || saving} className={secondaryButton}>{t("common.revert")}</button>
        <button onClick={save} disabled={!dirty || saving} className={primaryButton}>
          {saving ? t("common.saving") : t("settings.save")}
        </button>
      </div>
    </div>
  );
}

function RoleCard({ role, value, providers, onChange }: {
  role: ModelRole;
  value: ModelAssignment;
  providers: ProviderInfo[];
  onChange: (patch: Partial<ModelAssignment>) => void;
}) {
  const { t } = useLang();
  const provider = providers.find((p) => p.id === value.provider_id);
  const imageFormat = value.format || (provider?.api_format === "gemini_official" ? "gemini" : "openai");
  const listId = `settings-models-${role}`;
  const configured = Boolean(value.provider_id && value.model && provider);

  return (
    <div className="rounded-xl border border-zinc-200 p-3.5 dark:border-zinc-800">
      <div className="mb-3 flex items-start gap-2.5">
        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${configured ? "bg-brand-50 text-brand-500 dark:bg-brand-500/10 dark:text-brand-400" : "bg-zinc-100 text-zinc-400 dark:bg-zinc-800"}`}>
          <Icon name={ROLE_ICONS[role]} className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-zinc-800 dark:text-zinc-100">
            {t(`settings.role.${role}`)}
            {!configured && role !== "vision" && <span className="chip bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">{t("settings.notSet")}</span>}
          </div>
          <div className="mt-0.5 text-[11px] text-zinc-400">{t(`settings.role.${role}Desc`)}</div>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <Field label={t("settings.provider")}>
          <select
            value={value.provider_id}
            onChange={(e) => onChange(e.target.value ? { provider_id: e.target.value } : { provider_id: "", model: "" })}
            className={inputClass}
          >
            <option value="">{role === "vision" ? t("settings.followChat") : t("settings.notSet")}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </Field>
        <Field label={t("settings.model")}>
          <input
            list={listId}
            value={value.model}
            onChange={(e) => onChange({ model: e.target.value })}
            placeholder={t("settings.modelPlaceholder")}
            disabled={!value.provider_id}
            className={`${inputClass} font-mono`}
          />
          <datalist id={listId}>
            {(provider?.models || []).map((m) => <option key={m} value={m} />)}
          </datalist>
        </Field>

        {role === "image" && (
          <>
            <Field label={t("settings.interface")}>
              <select value={value.format} onChange={(e) => onChange({ format: e.target.value })} className={inputClass}>
                <option value="">{t("settings.auto")}</option>
                <option value="gemini">{t("settings.imageGemini")}</option>
                <option value="openai">{t("settings.imageOpenai")}</option>
              </select>
            </Field>
            {imageFormat === "openai" && (
              <Field label={t("settings.size")}>
                <input
                  value={value.size}
                  onChange={(e) => onChange({ size: e.target.value })}
                  placeholder={t("settings.sizePlaceholder")}
                  className={`${inputClass} font-mono`}
                />
              </Field>
            )}
          </>
        )}

        {role === "video" && (
          <Field label={t("settings.interface")}>
            <select value={value.format} onChange={(e) => onChange({ format: e.target.value })} className={inputClass}>
              <option value="">{t("settings.auto")}</option>
              <option value="unified">{t("settings.videoUnified")}</option>
              <option value="openai">{t("settings.videoOpenai")}</option>
              <option value="gemini">{t("settings.videoGemini")}</option>
            </select>
          </Field>
        )}
      </div>
    </div>
  );
}

// ==================== 服务商 ====================

function ProvidersTab({ settings, onChange, startCreating }: {
  settings: AppSettings;
  onChange: (settings: AppSettings) => void;
  startCreating: boolean;
}) {
  const { t } = useLang();
  const toast = useToast();
  const [editing, setEditing] = useState<ProviderInfo | "new" | null>(startCreating ? "new" : null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderInfo | null>(null);

  if (editing) {
    return (
      <ProviderForm
        provider={editing === "new" ? null : editing}
        onSaved={(next) => { onChange(next); setEditing(null); toast(t("settings.saved"), "success"); }}
        onCancel={() => setEditing(null)}
      />
    );
  }

  const rolesUsing = (id: string) => visibleRoles(settings).filter((role) => settings.models[role].provider_id === id);

  const handleDelete = async () => {
    const target = deleteTarget;
    setDeleteTarget(null);
    if (!target) return;
    try {
      onChange(await deleteProvider(target.id));
    } catch (e) {
      toast(errorText(e), "error");
    }
  };

  return (
    <div className="space-y-2.5">
      <div className="mb-1 flex items-center justify-between">
        <div className="text-xs text-zinc-500 dark:text-zinc-400">
          {t("settings.providerCount", { count: settings.providers.length })}
        </div>
        <button onClick={() => setEditing("new")} className={primaryButton}>
          <Icon name="plus" className="h-3.5 w-3.5" strokeWidth={2.5} />{t("settings.addProvider")}
        </button>
      </div>

      {settings.providers.length === 0 && (
        <div className="flex flex-col items-center py-16 text-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-100 text-zinc-400 dark:bg-zinc-800">
            <Icon name="server" className="h-6 w-6" />
          </div>
          <div className="text-sm text-zinc-500 dark:text-zinc-400">{t("settings.noProviders")}</div>
        </div>
      )}

      {settings.providers.map((provider) => {
        const used = rolesUsing(provider.id);
        return (
          <div key={provider.id} className="rounded-xl border border-zinc-200 p-3.5 transition-colors hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  <Icon name="server" className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100">{provider.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="chip bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300">
                      {t(FORMAT_LABEL_KEYS[provider.api_format])}
                    </span>
                    <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                      <Icon name="key" className="h-2.5 w-2.5" />
                      {provider.key_count > 0 ? t("settings.keys", { count: provider.key_count }) : t("settings.noKey")}
                    </span>
                    <span className="chip bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                      {t("settings.modelCount", { count: provider.models.length })}
                    </span>
                    {used.length > 0 && (
                      <span className="chip bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300">
                        {t("settings.usedFor")}: {used.map((role) => t(`settings.role.${role}`)).join(" / ")}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button onClick={() => setEditing(provider)} className="icon-btn-sm" title={t("common.edit")}>
                  <Icon name="pencil" className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => setDeleteTarget(provider)} className="icon-btn-sm hover:text-red-500" title={t("common.delete")}>
                  <Icon name="trash" className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <div className="mt-2.5 truncate pl-[42px] font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{provider.base_url || "—"}</div>
            {provider.key_previews.length > 0 && (
              <div className="mt-0.5 truncate pl-[42px] font-mono text-[11px] text-zinc-400">{provider.key_previews.join("  ")}</div>
            )}
          </div>
        );
      })}

      {deleteTarget && (
        <ConfirmDialog
          title={t("settings.deleteProviderTitle")}
          message={t("settings.deleteProviderConfirm", { name: deleteTarget.name })}
          confirmLabel={t("common.delete")}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

function ProviderForm({ provider, onSaved, onCancel }: {
  provider: ProviderInfo | null;
  onSaved: (settings: AppSettings) => void;
  onCancel: () => void;
}) {
  const { t } = useLang();
  const [name, setName] = useState(provider?.name || "");
  const [format, setFormat] = useState<ApiFormat>(provider?.api_format || "openai_compatible");
  const [baseUrl, setBaseUrl] = useState(provider?.base_url || "");
  const [concurrency, setConcurrency] = useState(provider?.max_concurrency ?? DEFAULT_CONCURRENCY);
  const [keysText, setKeysText] = useState("");
  const [showKeys, setShowKeys] = useState(false);
  const [models, setModels] = useState<string[]>(provider?.models || []);
  const [manualModel, setManualModel] = useState("");
  const [busy, setBusy] = useState<"" | "fetch" | "test" | "save">("");
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const keys = parseKeys(keysText);
  const detected = provider ? null : detectFromKey(keysText);

  // 新建时按 Key 前缀自动填 API 格式；地址和名称只在还没填时补上
  const handleKeysChange = (value: string) => {
    setKeysText(value);
    setStatus(null);
    if (provider) return;
    const guess = detectFromKey(value);
    if (!guess) return;
    setFormat(guess.format);
    setBaseUrl((prev) => prev || guess.url);
    setName((prev) => prev || guess.name);
  };

  const probe = (model = ""): ProviderProbe => ({
    provider_id: provider?.id ?? null,
    api_format: format,
    base_url: baseUrl.trim(),
    api_keys: keys.length > 0 ? keys : null,
    model,
  });

  const handleFetch = async () => {
    setBusy("fetch");
    setStatus(null);
    try {
      const res = await fetchProviderModels(probe());
      if (res.error) {
        setStatus({ ok: false, text: res.error });
      } else {
        setModels((prev) => mergeModels(prev, res.models));
        setStatus({ ok: true, text: t("settings.fetched", { count: res.models.length }) });
      }
    } catch (e) {
      setStatus({ ok: false, text: errorText(e) });
    } finally {
      setBusy("");
    }
  };

  const handleTest = async (model = "") => {
    setBusy("test");
    setStatus(null);
    try {
      const res = await testProvider(probe(model));
      setStatus({
        ok: res.ok,
        text: res.results.map((r) => `${r.ok ? "✓" : "✗"} ${r.key}  ${r.message}`).join("\n"),
      });
      if (res.ok && model) {
        setModels((prev) => mergeModels(prev, [model]));
        setManualModel("");
      }
    } catch (e) {
      setStatus({ ok: false, text: errorText(e) });
    } finally {
      setBusy("");
    }
  };

  const addManualModel = () => {
    const model = manualModel.trim();
    if (!model) return;
    setModels((prev) => mergeModels(prev, [model]));
    setManualModel("");
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setStatus({ ok: false, text: t("settings.requireName") });
      return;
    }
    setBusy("save");
    const body: ProviderInput = {
      name: name.trim(),
      api_format: format,
      base_url: baseUrl.trim(),
      api_keys: keys.length > 0 ? keys : provider ? null : [],
      models,
      max_concurrency: clampConcurrency(concurrency),
    };
    try {
      onSaved(provider ? await updateProvider(provider.id, body) : await createProvider(body));
    } catch (e) {
      setStatus({ ok: false, text: errorText(e) });
      setBusy("");
    }
  };

  const keyStyle = { WebkitTextSecurity: showKeys ? "none" : "disc" } as CSSProperties;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button onClick={onCancel} className="icon-btn-sm" title={t("common.cancel")}>
          <Icon name="chevron-left" className="h-4 w-4" />
        </button>
        <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
          {provider ? t("settings.editProviderName", { name: provider.name }) : t("settings.newProvider")}
        </div>
      </div>

      <Field
        label={t("settings.apiKeys")}
        hint={provider && provider.key_count > 0 ? t("settings.apiKeysKeep", { count: provider.key_count }) : t("settings.apiKeysHint")}
      >
        <div className="relative">
          <textarea
            value={keysText}
            onChange={(e) => handleKeysChange(e.target.value)}
            rows={Math.min(Math.max(keys.length, 1) + 1, 6)}
            placeholder={provider?.key_previews.join("\n") || "sk-…"}
            className={`${inputClass} resize-none pr-16 font-mono`}
            style={keyStyle}
            spellCheck={false}
            autoComplete="off"
          />
          <button
            type="button"
            onClick={() => setShowKeys(!showKeys)}
            className="absolute right-2 top-1.5 flex items-center gap-1 rounded px-1 text-[11px] text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            <Icon name="eye" className="h-3 w-3" />
            {showKeys ? t("settings.hideKeys") : t("settings.showKeys")}
          </button>
        </div>
        {detected && (
          <div className="mt-1 flex items-center gap-1 text-[11px] text-brand-500">
            <Icon name="sparkles" className="h-3 w-3" />{t("settings.detected", { name: detected.name })}
          </div>
        )}
      </Field>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("settings.apiFormat")}>
          <select value={format} onChange={(e) => setFormat(e.target.value as ApiFormat)} className={inputClass}>
            {(Object.keys(FORMAT_LABEL_KEYS) as ApiFormat[]).map((f) => (
              <option key={f} value={f}>{t(FORMAT_LABEL_KEYS[f])}</option>
            ))}
          </select>
        </Field>
        <Field label={t("settings.name")}>
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </Field>
      </div>

      <Field label={t("settings.baseUrl")}>
        <div className="flex gap-2">
          <input
            value={baseUrl}
            onChange={(e) => { setBaseUrl(e.target.value); setStatus(null); }}
            placeholder={PRESETS[format][0].url}
            className={`${fieldClass} min-w-0 flex-1 font-mono`}
          />
          <select
            value=""
            onChange={(e) => {
              const preset = PRESETS[format].find((p) => p.url === e.target.value);
              if (!preset) return;
              setBaseUrl(preset.url);
              setName((prev) => prev || preset.label);
            }}
            className={`${fieldClass} w-40 shrink-0`}
          >
            <option value="">{t("settings.preset")}</option>
            {PRESETS[format].map((p) => (
              <option key={p.url} value={p.url}>{p.label}</option>
            ))}
          </select>
        </div>
      </Field>

      <Field label={t("settings.concurrency")} hint={t("settings.concurrencyHint")}>
        <input
          type="number"
          min={1}
          max={MAX_CONCURRENCY}
          value={concurrency}
          onChange={(e) => setConcurrency(Number(e.target.value))}
          onBlur={() => setConcurrency(clampConcurrency(concurrency))}
          className={`${inputClass} w-24`}
        />
      </Field>

      <Field label={`${t("settings.models")} (${models.length})`} hint={t("settings.modelsHint")}>
        <div className="flex max-h-36 flex-wrap gap-1 overflow-y-auto rounded-lg border border-zinc-200 bg-zinc-50 p-2 dark:border-zinc-800 dark:bg-zinc-950">
          {models.length === 0 ? (
            <span className="text-[11px] text-zinc-400">—</span>
          ) : (
            models.map((model) => (
              <span
                key={model}
                className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
              >
                {model}
                <button
                  type="button"
                  onClick={() => setModels((prev) => prev.filter((m) => m !== model))}
                  className="text-zinc-400 hover:text-red-500"
                  aria-label={`${t("common.delete")} ${model}`}
                >
                  <Icon name="x" className="h-3 w-3" />
                </button>
              </span>
            ))
          )}
        </div>
      </Field>
      <div className="flex flex-wrap gap-2">
        <input
          value={manualModel}
          onChange={(e) => setManualModel(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); addManualModel(); } }}
          placeholder={t("settings.manualModel")}
          className={`${fieldClass} min-w-[160px] flex-1 font-mono`}
        />
        <button type="button" onClick={addManualModel} disabled={!manualModel.trim()} className={secondaryButton}>
          <Icon name="plus" className="h-3.5 w-3.5" />{t("settings.addModel")}
        </button>
        <button type="button" onClick={() => handleTest(manualModel.trim())} disabled={!manualModel.trim() || busy !== ""} className={secondaryButton}>
          <Icon name="zap" className="h-3.5 w-3.5" />{t("settings.testModel")}
        </button>
        <button type="button" onClick={() => setModels([])} disabled={models.length === 0} className={secondaryButton}>
          {t("settings.clearModels")}
        </button>
      </div>

      <StatusText status={status} />

      <div className="sticky bottom-0 -mx-5 -mb-4 flex flex-wrap items-center gap-2 border-t border-zinc-100 bg-white/95 px-5 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/95">
        <button type="button" onClick={() => handleTest()} disabled={busy !== ""} className={secondaryButton}>
          {busy === "test" ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="zap" className="h-3.5 w-3.5" />}
          {t("settings.test")}
        </button>
        <button type="button" onClick={handleFetch} disabled={busy !== ""} className={secondaryButton}>
          {busy === "fetch" ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="refresh" className="h-3.5 w-3.5" />}
          {t("settings.fetchModels")}
        </button>
        <div className="flex-1" />
        <button type="button" onClick={onCancel} className={secondaryButton}>{t("common.cancel")}</button>
        <button type="button" onClick={handleSave} disabled={busy !== ""} className={primaryButton}>
          {busy === "save" ? t("common.saving") : t("settings.save")}
        </button>
      </div>
    </div>
  );
}
