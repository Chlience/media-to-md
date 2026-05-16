import { FormEvent, useEffect, useMemo, useState } from 'react';
import { WhisperXApiClient } from '../api/client';
import {
  RuntimePhaseCompact,
  runtimePhaseSummary,
  runtimePercentText,
} from '../components/RuntimeProgress';
import { AppShell, PageHeader } from '../components/Shell';
import {
  ArtifactZipDownload,
  Box,
  MetaList,
  StatusPill,
  Timeline,
  formatBytes,
  formatDate,
  formatDuration,
} from '../components/Primitives';
import { downloadTextFile } from '../services/jobs';
import { AdminSessionStore } from '../services/session';
import {
  BackendConfig,
  JobEvent,
  JobStatus,
  LlmProviderInfo,
  RuntimePhase,
  taskTypeLabel,
  taskTypePdf,
  taskTypeWhisperx,
  WhisperxBackend,
} from '../types/api';

const api = new WhisperXApiClient();
const sessionStore = new AdminSessionStore();
const filters = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'] as const;
const taskTypeViews = [
  { value: taskTypeWhisperx, label: '音视频转写任务' },
  { value: taskTypePdf, label: 'PDF 文档解析任务' },
] as const;
const pageSize = 10;
const defaultWhisperxModel = 'small';
const defaultOpenaiWhisperxModel = 'large-v2';
const defaultModelCacheOnly = false;
const defaultWhisperxBackend: WhisperxBackend = 'cli';
const defaultOpenaiTimeoutSeconds = '3600';
const defaultOpenaiMp3Bitrate = '64k';
const defaultLlmProvider = 'openai';
const defaultLlmTimeoutSeconds = '60';
const defaultMaxUploadMb = '512';
const fallbackLlmProviders: LlmProviderInfo[] = [
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
  { id: 'moonshot', label: 'Moonshot', baseUrl: 'https://api.moonshot.cn/v1' },
  {
    id: 'dashscope',
    label: '阿里云 DashScope',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'custom', label: '自定义 OpenAI 兼容接口', baseUrl: null },
];
const defaultWhisperxArgDisplay = {
  device: '',
  computeType: '',
  batchSize: '',
  chunkSize: '',
  diarizeModel: '',
  minSpeakers: '',
  maxSpeakers: '',
  speakerEmbeddings: '',
  noAlign: '',
} as const;

type Filter = (typeof filters)[number];
type TaskTypeView = (typeof taskTypeViews)[number]['value'];
type ConfigNotice = {
  kind: 'success' | 'error';
  message: string;
  title?: string;
  provider?: string;
  baseUrl?: string | null;
  model?: string | null;
  modelCount?: number;
} | null;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function trimTrailingPunctuation(value: string): string {
  return value.trim().replace(/[\s。．.!！?？:：;；,…，、]+$/u, '');
}

function shortJobId(jobId: string): string {
  return jobId.length > 14 ? jobId.slice(0, 14) : jobId;
}

function jsonPreview(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('参数必须是 JSON object。');
  }
  return parsed as Record<string, unknown>;
}

function parseJsonObjectOrEmpty(text: string): Record<string, unknown> {
  try {
    return parseJsonObject(text);
  } catch {
    return {};
  }
}

function formatJsonObject(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function runtimePhaseFromEvent(event: JobEvent): RuntimePhase | null {
  if (event.type !== 'progress') return null;
  return {
    process: stringOrNull(event.data.process),
    code: stringOrNull(event.data.code) ?? 'progress',
    label: stringOrNull(event.data.label) ?? '运行进度',
    detail: stringOrNull(event.data.detail) ?? event.message,
    stagePercent: numberOrNull(event.data.stage_percent),
    source: stringOrNull(event.data.source),
    updatedAt: stringOrNull(event.data.updated_at),
  };
}

function eventTimelineText(event: JobEvent) {
  const phase = runtimePhaseFromEvent(event);
  if (!phase) return `${event.type}: ${event.message}`;
  return (
    <span>
      progress: {phase.label} · {runtimePercentText(phase)}
    </span>
  );
}

function llmProviderDefaultBaseUrl(providers: LlmProviderInfo[], providerId: string): string {
  return providers.find((provider) => provider.id === providerId)?.baseUrl ?? '';
}

export function AdminPage() {
  const [token, setToken] = useState(() => sessionStore.read()?.token ?? '');
  const [username, setUsername] = useState(() => sessionStore.read()?.username ?? 'admin');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [taskTypeView, setTaskTypeView] = useState<TaskTypeView>(taskTypeWhisperx);
  const [page, setPage] = useState(1);
  const [config, setConfig] = useState<BackendConfig | null>(null);
  const [cliModel, setCliModel] = useState(defaultWhisperxModel);
  const [openaiModel, setOpenaiModel] = useState(defaultOpenaiWhisperxModel);
  const [modelDir, setModelDir] = useState('');
  const [whisperxBackend, setWhisperxBackend] = useState<WhisperxBackend>(defaultWhisperxBackend);
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiApiKeyConfigured, setOpenaiApiKeyConfigured] = useState(false);
  const [openaiClearApiKey, setOpenaiClearApiKey] = useState(false);
  const [openaiTimeoutSeconds, setOpenaiTimeoutSeconds] = useState(defaultOpenaiTimeoutSeconds);
  const [openaiTranscodeToMp3, setOpenaiTranscodeToMp3] = useState(true);
  const [openaiMp3Bitrate, setOpenaiMp3Bitrate] = useState(defaultOpenaiMp3Bitrate);
  const [openaiModels, setOpenaiModels] = useState<string[]>([]);
  const [openaiModelsBusy, setOpenaiModelsBusy] = useState(false);
  const [nltkDataDir, setNltkDataDir] = useState('');
  const [modelCacheOnly, setModelCacheOnly] = useState(defaultModelCacheOnly);
  const [maxWhisperxUploadMb, setMaxWhisperxUploadMb] = useState(defaultMaxUploadMb);
  const [maxPdfUploadMb, setMaxPdfUploadMb] = useState(defaultMaxUploadMb);
  const [cliWhisperxArgs, setCliWhisperxArgs] = useState('{}');
  const [openaiWhisperxArgs, setOpenaiWhisperxArgs] = useState('{}');
  const [pdfArgs, setPdfArgs] = useState('{}');
  const [whisperxLlmPolishEnabled, setWhisperxLlmPolishEnabled] = useState(false);
  const [pdfLlmPolishEnabled, setPdfLlmPolishEnabled] = useState(false);
  const [llmProvider, setLlmProvider] = useState(defaultLlmProvider);
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmApiKeyConfigured, setLlmApiKeyConfigured] = useState(false);
  const [llmClearApiKey, setLlmClearApiKey] = useState(false);
  const [llmModel, setLlmModel] = useState('');
  const [llmTimeoutSeconds, setLlmTimeoutSeconds] = useState(defaultLlmTimeoutSeconds);
  const [llmModels, setLlmModels] = useState<string[]>([]);
  const [llmNotice, setLlmNotice] = useState<ConfigNotice>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobStatus | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<JobEvent[]>([]);
  const [selectedLog, setSelectedLog] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [configNotice, setConfigNotice] = useState<ConfigNotice>(null);
  const [busy, setBusy] = useState(false);
  const [loginOpen, setLoginOpen] = useState(() => !sessionStore.read()?.token);

  const signedIn = token.trim().length > 0;

  const counts = useMemo(() => {
    const next = { all: jobs.length, queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0 };
    for (const job of jobs) {
      if (job.status in next) next[job.status as keyof typeof next] += 1;
    }
    return next;
  }, [jobs]);

  const jobsForTaskType = useMemo(
    () => jobs.filter((job) => job.taskType === taskTypeView),
    [jobs, taskTypeView],
  );

  const filteredJobs = useMemo(
    () => (filter === 'all' ? jobsForTaskType : jobsForTaskType.filter((job) => job.status === filter)),
    [filter, jobsForTaskType],
  );
  const pageCount = Math.max(1, Math.ceil(filteredJobs.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagedJobs = useMemo(
    () => filteredJobs.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [currentPage, filteredJobs],
  );
  const isWhisperxView = taskTypeView === taskTypeWhisperx;
  const emptyColSpan = isWhisperxView ? 11 : 7;
  const visibleModel = whisperxBackend === 'openai' ? openaiModel : cliModel;
  const visibleModelPlaceholder =
    whisperxBackend === 'openai' ? defaultOpenaiWhisperxModel : defaultWhisperxModel;
  const visibleWhisperxArgs =
    whisperxBackend === 'openai' ? openaiWhisperxArgs : cliWhisperxArgs;
  const setVisibleWhisperxArgs =
    whisperxBackend === 'openai' ? setOpenaiWhisperxArgs : setCliWhisperxArgs;
  const llmProviders =
    config?.llmPolishProviders && config.llmPolishProviders.length > 0
      ? config.llmPolishProviders
      : fallbackLlmProviders;
  const setVisibleModel = (value: string) => {
    if (whisperxBackend === 'openai') {
      setOpenaiModel(value);
    } else {
      setCliModel(value);
    }
  };

  const loadJobs = async (adminToken = token) => {
    if (!adminToken) return;
    const nextJobs = await api.fetchJobs({ adminToken, includeLog: false });
    setJobs(nextJobs);
    setSelectedJob((current) =>
      current ? nextJobs.find((job) => job.jobId === current.jobId) ?? current : current,
    );
  };

  const loadConfig = async (adminToken = token) => {
    if (!adminToken) return;
    const nextConfig = await api.fetchConfig(adminToken);
    setConfig(nextConfig);
    setCliModel(nextConfig.cliModel);
    setOpenaiModel(nextConfig.openaiModel);
    setModelDir(nextConfig.modelDir ?? '');
    setWhisperxBackend(nextConfig.whisperxBackend);
    setOpenaiBaseUrl(nextConfig.whisperxOpenaiBaseUrl ?? '');
    setOpenaiApiKey('');
    setOpenaiApiKeyConfigured(nextConfig.whisperxOpenaiApiKeyConfigured);
    setOpenaiClearApiKey(false);
    setOpenaiTimeoutSeconds(String(nextConfig.whisperxOpenaiTimeoutSeconds || 3600));
    setOpenaiTranscodeToMp3(nextConfig.whisperxOpenaiTranscodeToMp3);
    setOpenaiMp3Bitrate(nextConfig.whisperxOpenaiMp3Bitrate || defaultOpenaiMp3Bitrate);
    setOpenaiModels([]);
    setNltkDataDir(nextConfig.nltkDataDir ?? '');
    setModelCacheOnly(nextConfig.modelCacheOnly);
    setMaxWhisperxUploadMb(String(nextConfig.maxWhisperxUploadMb));
    setMaxPdfUploadMb(String(nextConfig.maxPdfUploadMb));
    setCliWhisperxArgs(jsonPreview(nextConfig.whisperxCliArgsConfig));
    setOpenaiWhisperxArgs(jsonPreview(nextConfig.whisperxOpenaiArgsConfig));
    setPdfArgs(jsonPreview(nextConfig.pdfArgsConfig));
    setWhisperxLlmPolishEnabled(nextConfig.whisperxLlmPolishEnabled);
    setPdfLlmPolishEnabled(nextConfig.pdfLlmPolishEnabled);
    setLlmProvider(nextConfig.llmPolishProvider || defaultLlmProvider);
    setLlmBaseUrl(nextConfig.llmPolishBaseUrl ?? '');
    setLlmApiKey('');
    setLlmApiKeyConfigured(nextConfig.llmPolishApiKeyConfigured);
    setLlmClearApiKey(false);
    setLlmModel(nextConfig.llmPolishModel ?? '');
    setLlmTimeoutSeconds(String(nextConfig.llmPolishTimeoutSeconds || 60));
    setLlmModels([]);
    setLlmNotice(null);
  };

  const refresh = async (adminToken = token) => {
    if (!adminToken) return;
    setError(null);
    try {
      await Promise.all([loadJobs(adminToken), loadConfig(adminToken)]);
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  };

  const closeDetail = () => {
    setSelectedJob(null);
    setSelectedEvents([]);
    setSelectedLog('');
  };

  const loadJobDetail = async (jobId: string, adminToken = token) => {
    if (!adminToken) return;
    const [status, events, log] = await Promise.all([
      api.fetchStatus(jobId),
      api.fetchJobEvents({ adminToken, jobId }),
      api.fetchJobLog({ adminToken, jobId }),
    ]);
    setSelectedJob(status);
    setSelectedEvents(events);
    setSelectedLog(log);
  };

  useEffect(() => {
    if (!token) return;
    void refresh(token);
    const timer = setInterval(() => void loadJobs(token).catch((nextError) => setError(errorMessage(nextError))), 3000);
    return () => clearInterval(timer);
  }, [token]);

  useEffect(() => {
    if (!selectedJob) return undefined;
    document.body.classList.add('modal-open');
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDetail();
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.classList.remove('modal-open');
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [selectedJob]);

  useEffect(() => {
    if (!token || !selectedJob || selectedJob.status !== 'running') return undefined;
    const jobId = selectedJob.jobId;
    const timer = window.setInterval(() => {
      void loadJobDetail(jobId, token).catch((nextError) => setError(errorMessage(nextError)));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [token, selectedJob?.jobId, selectedJob?.status]);

  useEffect(() => {
    if (!configNotice) return undefined;
    const timer = window.setTimeout(() => setConfigNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [configNotice]);

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api.loginAdmin({ username: username || 'admin', password });
      sessionStore.save(session);
      setToken(session.accessToken);
      setUsername(session.username);
      setPassword('');
      setNewPassword('');
      await refresh(session.accessToken);
      setLoginOpen(false);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    sessionStore.clear();
    setToken('');
    setJobs([]);
    setConfig(null);
    setSelectedJob(null);
    setPassword('');
    setNewPassword('');
    setLoginOpen(true);
  };

  const saveAccount = async () => {
    if (!token || !password) {
      setError('修改账号需要输入当前密码。');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await api.updateAdminAccount({
        adminToken: token,
        currentPassword: password,
        username,
        newPassword: null,
      });
      sessionStore.save(session);
      setToken(session.accessToken);
      setUsername(session.username);
      setPassword('');
      setNewPassword('');
      setLoginOpen(false);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const changePassword = async () => {
    if (!token || !password || !newPassword) {
      setError('修改密码需要输入当前密码和新密码。');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await api.updateAdminAccount({
        adminToken: token,
        currentPassword: password,
        newPassword,
      });
      sessionStore.save(session);
      setToken(session.accessToken);
      setUsername(session.username);
      setPassword('');
      setNewPassword('');
      setLoginOpen(false);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const saveConfig = async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    setConfigNotice(null);
    try {
      const parsedOpenaiTimeoutSeconds = Number(openaiTimeoutSeconds || defaultOpenaiTimeoutSeconds);
      if (!Number.isFinite(parsedOpenaiTimeoutSeconds) || parsedOpenaiTimeoutSeconds <= 0) {
        throw new Error('OpenAI timeout seconds 必须是大于 0 的数字。');
      }
      const normalizedOpenaiMp3Bitrate = openaiMp3Bitrate.trim().toLowerCase();
      const openaiMp3BitrateMatch = /^([1-9][0-9]{0,3})k$/.exec(normalizedOpenaiMp3Bitrate);
      const openaiMp3BitrateKbps = openaiMp3BitrateMatch ? Number(openaiMp3BitrateMatch[1]) : 0;
      if (!openaiMp3BitrateMatch || openaiMp3BitrateKbps < 8 || openaiMp3BitrateKbps > 320) {
        throw new Error('OpenAI MP3 bitrate 必须是 8k 到 320k 之间的值，例如 64k。');
      }
      const parsedLlmTimeoutSeconds = Number(llmTimeoutSeconds || defaultLlmTimeoutSeconds);
      if (!Number.isFinite(parsedLlmTimeoutSeconds) || parsedLlmTimeoutSeconds <= 0) {
        throw new Error('LLM timeout seconds 必须是大于 0 的数字。');
      }
      const parsedMaxWhisperxUploadMb = Number(maxWhisperxUploadMb || defaultMaxUploadMb);
      if (!Number.isFinite(parsedMaxWhisperxUploadMb) || parsedMaxWhisperxUploadMb <= 0) {
        throw new Error('音视频最大上传 MB 必须是大于 0 的数字。');
      }
      const parsedMaxPdfUploadMb = Number(maxPdfUploadMb || defaultMaxUploadMb);
      if (!Number.isFinite(parsedMaxPdfUploadMb) || parsedMaxPdfUploadMb <= 0) {
        throw new Error('PDF 最大上传 MB 必须是大于 0 的数字。');
      }
      const nextConfig = await api.updateConfig({
        adminToken: token,
        cliModel,
        openaiModel,
        modelDir,
        whisperxBackend,
        whisperxOpenaiBaseUrl: openaiBaseUrl,
        whisperxOpenaiApiKey: openaiApiKey,
        whisperxOpenaiClearApiKey: openaiClearApiKey,
        whisperxOpenaiTimeoutSeconds: parsedOpenaiTimeoutSeconds,
        whisperxOpenaiTranscodeToMp3: openaiTranscodeToMp3,
        whisperxOpenaiMp3Bitrate: normalizedOpenaiMp3Bitrate,
        modelCacheOnly,
        nltkDataDir,
        maxWhisperxUploadMb: parsedMaxWhisperxUploadMb,
        maxPdfUploadMb: parsedMaxPdfUploadMb,
        whisperxCliArgs: parseJsonObject(cliWhisperxArgs),
        whisperxOpenaiArgs: parseJsonObject(openaiWhisperxArgs),
        pdfArgs: parseJsonObject(pdfArgs),
        whisperxLlmPolishEnabled,
        pdfLlmPolishEnabled,
        llmPolishProvider: llmProvider,
        llmPolishBaseUrl: llmBaseUrl,
        llmPolishApiKey: llmApiKey,
        llmPolishClearApiKey: llmClearApiKey,
        llmPolishModel: llmModel,
        llmPolishTimeoutSeconds: parsedLlmTimeoutSeconds,
      });
      setConfig(nextConfig);
      setWhisperxBackend(nextConfig.whisperxBackend);
      setCliModel(nextConfig.cliModel);
      setOpenaiModel(nextConfig.openaiModel);
      setOpenaiBaseUrl(nextConfig.whisperxOpenaiBaseUrl ?? '');
      setOpenaiApiKey('');
      setOpenaiApiKeyConfigured(nextConfig.whisperxOpenaiApiKeyConfigured);
      setOpenaiClearApiKey(false);
      setOpenaiTimeoutSeconds(String(nextConfig.whisperxOpenaiTimeoutSeconds || 3600));
      setOpenaiTranscodeToMp3(nextConfig.whisperxOpenaiTranscodeToMp3);
      setOpenaiMp3Bitrate(nextConfig.whisperxOpenaiMp3Bitrate || defaultOpenaiMp3Bitrate);
      setOpenaiModels([]);
      setMaxWhisperxUploadMb(String(nextConfig.maxWhisperxUploadMb));
      setMaxPdfUploadMb(String(nextConfig.maxPdfUploadMb));
      setCliWhisperxArgs(jsonPreview(nextConfig.whisperxCliArgsConfig));
      setOpenaiWhisperxArgs(jsonPreview(nextConfig.whisperxOpenaiArgsConfig));
      setPdfArgs(jsonPreview(nextConfig.pdfArgsConfig));
      setWhisperxLlmPolishEnabled(nextConfig.whisperxLlmPolishEnabled);
      setPdfLlmPolishEnabled(nextConfig.pdfLlmPolishEnabled);
      setLlmProvider(nextConfig.llmPolishProvider || defaultLlmProvider);
      setLlmBaseUrl(nextConfig.llmPolishBaseUrl ?? '');
      setLlmApiKey('');
      setLlmApiKeyConfigured(nextConfig.llmPolishApiKeyConfigured);
      setLlmClearApiKey(false);
      setLlmModel(nextConfig.llmPolishModel ?? '');
      setLlmTimeoutSeconds(String(nextConfig.llmPolishTimeoutSeconds || 60));
      setConfigNotice({ kind: 'success', message: '配置已保存' });
    } catch (nextError) {
      const message = trimTrailingPunctuation(errorMessage(nextError));
      setError(message);
      setConfigNotice({
        kind: 'error',
        message: message ? `保存失败 ${message}` : '保存失败',
      });
    } finally {
      setBusy(false);
    }
  };

  const parsedLlmTimeoutOrDefault = () => {
    const parsed = Number(llmTimeoutSeconds || defaultLlmTimeoutSeconds);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      throw new Error('LLM timeout seconds 必须是大于 0 的数字。');
    }
    return parsed;
  };

  const changeLlmProvider = (nextProvider: string) => {
    const previousDefault = llmProviderDefaultBaseUrl(llmProviders, llmProvider);
    const nextDefault = llmProviderDefaultBaseUrl(llmProviders, nextProvider);
    const shouldReplaceBaseUrl = !llmBaseUrl.trim() || llmBaseUrl.trim() === previousDefault;
    setLlmProvider(nextProvider);
    if (shouldReplaceBaseUrl) setLlmBaseUrl(nextDefault);
    setLlmModels([]);
    setLlmNotice(null);
  };

  const loadLlmModels = async () => {
    if (!token) return;
    setLlmBusy(true);
    setLlmNotice(null);
    try {
      const response = await api.fetchLlmModels({
        adminToken: token,
        provider: llmProvider,
        baseUrl: llmBaseUrl,
        apiKey: llmApiKey,
        model: llmModel,
        timeoutSeconds: parsedLlmTimeoutOrDefault(),
      });
      setLlmBaseUrl(response.baseUrl);
      setLlmModels(response.models);
      const selectedModel = llmModel.trim() || response.models[0] || '';
      if (!llmModel.trim() && response.models[0]) setLlmModel(response.models[0]);
      setLlmNotice({
        kind: 'success',
        title: response.models.length > 0 ? '模型列表已更新' : '模型列表为空',
        message: response.message,
        provider: response.provider,
        baseUrl: response.baseUrl,
        model: selectedModel || null,
        modelCount: response.models.length > 0 ? response.models.length : undefined,
      });
    } catch (nextError) {
      const message = trimTrailingPunctuation(errorMessage(nextError));
      setLlmNotice({ kind: 'error', message: message || '模型拉取失败' });
    } finally {
      setLlmBusy(false);
    }
  };

  const parsedOpenaiTimeoutOrDefault = () => {
    const parsed = Number(openaiTimeoutSeconds || defaultOpenaiTimeoutSeconds);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      throw new Error('OpenAI timeout seconds 必须是大于 0 的数字。');
    }
    return parsed;
  };

  const loadWhisperxOpenaiModels = async () => {
    if (!token) return;
    setOpenaiModelsBusy(true);
    setConfigNotice(null);
    try {
      const response = await api.fetchWhisperxOpenaiModels({
        adminToken: token,
        baseUrl: openaiBaseUrl,
        apiKey: openaiApiKey,
        timeoutSeconds: parsedOpenaiTimeoutOrDefault(),
      });
      setOpenaiBaseUrl(response.baseUrl);
      setOpenaiModels(response.models);
      const selectedModel = response.models.includes(openaiModel.trim())
        ? openaiModel.trim()
        : response.models[0] || '';
      if (selectedModel) setOpenaiModel(selectedModel);
      setConfigNotice({
        kind: 'success',
        title: response.models.length > 0 ? 'WhisperX 模型列表已更新' : 'WhisperX 模型列表为空',
        message: response.message,
        provider: response.provider,
        baseUrl: response.baseUrl,
        model: selectedModel || null,
        modelCount: response.models.length > 0 ? response.models.length : undefined,
      });
    } catch (nextError) {
      const message = trimTrailingPunctuation(errorMessage(nextError));
      setConfigNotice({ kind: 'error', message: message || 'WhisperX 模型拉取失败' });
    } finally {
      setOpenaiModelsBusy(false);
    }
  };

  const checkLlmProviderConnection = async () => {
    if (!token) return;
    setLlmBusy(true);
    setLlmNotice(null);
    try {
      const response = await api.checkLlmConnection({
        adminToken: token,
        provider: llmProvider,
        baseUrl: llmBaseUrl,
        apiKey: llmApiKey,
        model: llmModel,
        timeoutSeconds: parsedLlmTimeoutOrDefault(),
      });
      if (response.baseUrl) setLlmBaseUrl(response.baseUrl);
      if (response.models.length > 0) setLlmModels(response.models);
      const selectedModel = response.model?.trim() || llmModel.trim();
      setLlmNotice({
        kind: response.ok ? 'success' : 'error',
        title: response.ok ? '连接检查通过' : '连接检查失败',
        message: response.message,
        provider: response.provider,
        baseUrl: response.baseUrl,
        model: selectedModel || null,
        modelCount: response.models.length > 0 ? response.models.length : undefined,
      });
    } catch (nextError) {
      const message = trimTrailingPunctuation(errorMessage(nextError));
      setLlmNotice({ kind: 'error', message: message || '连接检查失败' });
    } finally {
      setLlmBusy(false);
    }
  };

  const openDetail = async (job: JobStatus) => {
    setSelectedJob(job);
    setSelectedEvents([]);
    setSelectedLog('');
    if (!token) return;
    try {
      await loadJobDetail(job.jobId, token);
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  };

  const deleteJob = async (job: JobStatus) => {
    if (!token || job.status === 'running') return;
    if (!window.confirm(`确认删除任务 ${job.jobId} 及其相关文件？`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteJob({ adminToken: token, jobId: job.jobId });
      if (selectedJob?.jobId === job.jobId) closeDetail();
      await loadJobs(token);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const downloadLog = async () => {
    if (!token || !selectedJob) return;
    const text = await api.fetchRawJobLog({ adminToken: token, jobId: selectedJob.jobId });
    downloadTextFile({ filename: `${selectedJob.jobId}.log`, text });
  };

  const whisperxArgValue = (key: string, defaultValue: string) =>
    String(parseJsonObjectOrEmpty(visibleWhisperxArgs)[key] ?? defaultValue);
  const whisperxArgBooleanValue = (key: string) => {
    const value = parseJsonObjectOrEmpty(visibleWhisperxArgs)[key];
    if (value === undefined || value === null || value === '') return '';
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
      if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
    }
    return '';
  };
  const pdfArgValue = (key: string, defaultValue: string) =>
    String(parseJsonObjectOrEmpty(pdfArgs)[key] ?? defaultValue);
  const setArgValue = (
    text: string,
    setText: (value: string) => void,
    key: string,
    value: string,
  ) => {
    const next = parseJsonObjectOrEmpty(text);
    const trimmed = value.trim();
    if (trimmed === '') {
      delete next[key];
    } else {
      next[key] = trimmed;
    }
    setText(formatJsonObject(next));
  };
  const setWhisperxArg = (key: string, value: string) =>
    setArgValue(visibleWhisperxArgs, setVisibleWhisperxArgs, key, value);
  const setWhisperxBooleanArg = (key: string, value: string) => {
    const next = parseJsonObjectOrEmpty(visibleWhisperxArgs);
    if (value === '') {
      delete next[key];
    } else {
      next[key] = value === 'true';
    }
    setVisibleWhisperxArgs(formatJsonObject(next));
  };
  const setPdfArg = (key: string, value: string) =>
    setArgValue(pdfArgs, setPdfArgs, key, value);
  const optionValue = (job: JobStatus, ...keys: string[]) => {
    for (const key of keys) {
      const value = job.options?.[key];
      if (value !== undefined && value !== null && value !== '') return String(value);
    }
    return '—';
  };
  const changeTaskTypeView = (nextView: TaskTypeView) => {
    setTaskTypeView(nextView);
    setPage(1);
  };
  const changeFilter = (nextFilter: Filter) => {
    setFilter(nextFilter);
    setPage(1);
  };
  const renderJobActions = (job: JobStatus) => (
    <td className="nowrap">
      <button className="btn" type="button" onClick={() => void openDetail(job)}>
        详情
      </button>{' '}
      <button
        className="btn btn-danger"
        type="button"
        disabled={job.status === 'running' || busy}
        onClick={() => void deleteJob(job)}
      >
        删除
      </button>
    </td>
  );

  return (
    <AppShell activeRoute="admin">
      <section id="admin" className="screen active" aria-labelledby="admin-title">
        <PageHeader
          title="任务管理页"
          description="管理员登录后管理账号、运行配置和历史任务；任务列表每 3 秒自动刷新，支持过滤、详情查看和安全删除。"
          actions={
            <>
              <button className="btn" type="button" onClick={() => setLoginOpen(true)}>
                {signedIn ? '账号管理' : '管理员登录'}
              </button>
              <button className="btn" type="button" onClick={() => void refresh()} disabled={!signedIn || busy}>
                手动刷新
              </button>
              {signedIn ? (
                <button className="btn btn-logout" type="button" onClick={logout}>
                  登出
                </button>
              ) : null}
            </>
          }
        />

        {error ? <div className="error-banner">{error}</div> : null}
        {error ? <div style={{ height: 16 }} /> : null}
        {configNotice ? (
          <div
            className={`config-toast config-toast-${configNotice.kind}`}
            role={configNotice.kind === 'error' ? 'alert' : 'status'}
            aria-live={configNotice.kind === 'error' ? 'assertive' : 'polite'}
          >
            {configNotice.message}
          </div>
        ) : null}

        <div className="grid-12">
          <div className="span-12">
            <div className="stat-strip">
              <div className="stat">
                <div className="stat-num">{counts.all}</div>
                <div className="stat-label">全部任务</div>
              </div>
              <div className="stat">
                <div className="stat-num">{counts.queued}</div>
                <div className="stat-label">queued</div>
              </div>
              <div className="stat">
                <div className="stat-num">{counts.running}</div>
                <div className="stat-label">running</div>
              </div>
              <div className="stat">
                <div className="stat-num">{counts.succeeded}</div>
                <div className="stat-label">succeeded</div>
              </div>
              <div className="stat">
                <div className="stat-num">{counts.failed}</div>
                <div className="stat-label">failed</div>
              </div>
            </div>
          </div>

          <div className="span-12">
            <Box
              title="后端运行配置"
              actions={
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={() => void saveConfig()}
                  disabled={!signedIn || busy}
                >
                  保存 config
                </button>
              }
            >
              <div className="config-grid">
                <div className="config-card">
                  <h3>WhisperX</h3>
                  <div className="config-inner">
                    <div className="form-grid">
                      <div className="field"><label className="label" htmlFor="cfg-whisperx-backend">执行方式</label><select id="cfg-whisperx-backend" className="select" value={whisperxBackend} onChange={(event) => setWhisperxBackend(event.target.value as WhisperxBackend)}><option value="cli">本机 CLI</option><option value="openai">OpenAI 兼容接口</option></select></div>
                      <div className="field">
                        <label className="label" htmlFor="cfg-model">默认模型</label>
                        <input id="cfg-model" className="input" value={visibleModel} list={whisperxBackend === 'openai' ? 'cfg-openai-model-list' : undefined} placeholder={visibleModelPlaceholder} onChange={(event) => setVisibleModel(event.target.value)} />
                        {whisperxBackend === 'openai' ? <datalist id="cfg-openai-model-list">{openaiModels.map((model) => <option key={model} value={model} />)}</datalist> : null}
                      </div>
                      <div className="field"><label className="label" htmlFor="cfg-whisperx-upload-limit">音视频最大上传 MB</label><input id="cfg-whisperx-upload-limit" className="input mono" type="number" min="0.001" step="0.1" value={maxWhisperxUploadMb} onChange={(event) => setMaxWhisperxUploadMb(event.target.value)} /></div>
                      {whisperxBackend === 'openai' ? (
                        <>
                          <div className="field"><label className="label" htmlFor="cfg-openai-base-url">OpenAI Base URL</label><input id="cfg-openai-base-url" className="input mono" value={openaiBaseUrl} placeholder="http://localhost:9000/v1" onChange={(event) => { setOpenaiBaseUrl(event.target.value); setOpenaiModels([]); }} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-api-key">OpenAI API Key</label><input id="cfg-openai-api-key" className="input mono" type="password" value={openaiApiKey} placeholder={openaiApiKeyConfigured ? '已配置；留空保持不变' : '未配置则不发送 Authorization'} onChange={(event) => { setOpenaiApiKey(event.target.value); setOpenaiModels([]); }} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-timeout">OpenAI timeout seconds</label><input id="cfg-openai-timeout" className="input mono" value={openaiTimeoutSeconds} onChange={(event) => { setOpenaiTimeoutSeconds(event.target.value); setOpenaiModels([]); }} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-transcode-mp3">转 MP3 后上传</label><select id="cfg-openai-transcode-mp3" className="select" value={String(openaiTranscodeToMp3)} onChange={(event) => setOpenaiTranscodeToMp3(event.target.value === 'true')}><option value="true">开启</option><option value="false">关闭</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-mp3-bitrate">MP3 bitrate</label><input id="cfg-openai-mp3-bitrate" className="input mono" value={openaiMp3Bitrate} placeholder="64k" onChange={(event) => setOpenaiMp3Bitrate(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-clear-key">清除 OpenAI Key</label><select id="cfg-openai-clear-key" className="select" value={String(openaiClearApiKey)} onChange={(event) => setOpenaiClearApiKey(event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                          <div className="field field-full">
                            <div className="llm-actions-row">
                              <div className="btn-row llm-action-buttons">
                                <button className="btn" type="button" disabled={!signedIn || openaiModelsBusy} onClick={() => void loadWhisperxOpenaiModels()}>
                                  拉取 WhisperX 模型
                                </button>
                              </div>
                              {openaiModels.length > 0 ? (
                                <div className="llm-model-picker">
                                  <label className="label" htmlFor="cfg-openai-model-select">选择已拉取 WhisperX 模型</label>
                                  <select
                                    id="cfg-openai-model-select"
                                    className="select mono"
                                    value={openaiModels.includes(openaiModel) ? openaiModel : ''}
                                    onChange={(event) => setOpenaiModel(event.target.value)}
                                  >
                                    <option value="" disabled>选择模型（{openaiModels.length} 个）</option>
                                    {openaiModels.map((model) => (
                                      <option key={model} value={model}>{model}</option>
                                    ))}
                                  </select>
                                </div>
                              ) : null}
                            </div>
                          </div>
                          <div className="field"><label className="label" htmlFor="cfg-batch-size">Batch size</label><input id="cfg-batch-size" className="input mono" value={whisperxArgValue('batch_size', defaultWhisperxArgDisplay.batchSize)} placeholder="远端默认" onChange={(event) => setWhisperxArg('batch_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-chunk-size">Chunk size</label><input id="cfg-chunk-size" className="input mono" value={whisperxArgValue('chunk_size', defaultWhisperxArgDisplay.chunkSize)} placeholder="远端默认" onChange={(event) => setWhisperxArg('chunk_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-no-align">No align</label><select id="cfg-no-align" className="select" value={String(whisperxArgBooleanValue('no_align'))} onChange={(event) => setWhisperxBooleanArg('no_align', event.target.value)}><option value="">远端默认</option><option value="true">true</option><option value="false">false</option></select></div>
                        </>
                      ) : (
                        <>
                          <div className="field field-full"><div className="status-note">本机 CLI 模式显示本进程启动 whisperx 时会用到的本地运行参数；OpenAI 接口地址和 Key 不参与本机 CLI 调用。</div></div>
                          <div className="field"><label className="label" htmlFor="cfg-model-dir">模型缓存目录</label><input id="cfg-model-dir" className="input mono" value={modelDir} placeholder="默认不指定" onChange={(event) => setModelDir(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-device">Device</label><select id="cfg-device" className="select" value={whisperxArgValue('device', defaultWhisperxArgDisplay.device)} onChange={(event) => setWhisperxArg('device', event.target.value)}><option value="">后端默认（未指定）</option><option value="cuda">cuda</option><option value="cpu">cpu</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-compute-type">Compute type</label><select id="cfg-compute-type" className="select" value={whisperxArgValue('compute_type', defaultWhisperxArgDisplay.computeType)} onChange={(event) => setWhisperxArg('compute_type', event.target.value)}><option value="">后端默认</option><option value="default">default</option><option value="float16">float16</option><option value="float32">float32</option><option value="int8">int8</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-batch-size">Batch size</label><input id="cfg-batch-size" className="input mono" value={whisperxArgValue('batch_size', defaultWhisperxArgDisplay.batchSize)} placeholder="后端默认" onChange={(event) => setWhisperxArg('batch_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-chunk-size">Chunk size</label><input id="cfg-chunk-size" className="input mono" value={whisperxArgValue('chunk_size', defaultWhisperxArgDisplay.chunkSize)} placeholder="后端默认" onChange={(event) => setWhisperxArg('chunk_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-no-align">No align</label><select id="cfg-no-align" className="select" value={String(whisperxArgBooleanValue('no_align'))} onChange={(event) => setWhisperxBooleanArg('no_align', event.target.value)}><option value="">后端默认</option><option value="true">true</option><option value="false">false</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-cache-only">仅使用本地缓存</label><select id="cfg-cache-only" className="select" value={String(modelCacheOnly)} onChange={(event) => setModelCacheOnly(event.target.value === 'true')}><option value="true">true</option><option value="false">false</option></select></div>
                          <div className="field field-full"><label className="label" htmlFor="cfg-diarize-model">Diarize model</label><input id="cfg-diarize-model" className="input mono" value={whisperxArgValue('diarize_model', defaultWhisperxArgDisplay.diarizeModel)} placeholder="后端默认；例如 /models/whisperx-cache/pyannote-speaker-diarization-community-1" onChange={(event) => setWhisperxArg('diarize_model', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-min-speakers">Min speakers</label><input id="cfg-min-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('min_speakers', defaultWhisperxArgDisplay.minSpeakers)} placeholder="后端默认" onChange={(event) => setWhisperxArg('min_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-max-speakers">Max speakers</label><input id="cfg-max-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('max_speakers', defaultWhisperxArgDisplay.maxSpeakers)} placeholder="后端默认" onChange={(event) => setWhisperxArg('max_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-speaker-embeddings">Speaker embeddings</label><select id="cfg-speaker-embeddings" className="select" value={String(whisperxArgBooleanValue('speaker_embeddings'))} onChange={(event) => setWhisperxBooleanArg('speaker_embeddings', event.target.value)}><option value="">后端默认</option><option value="true">true</option><option value="false">false</option></select></div>
                          <div className="field field-full"><label className="label" htmlFor="cfg-nltk">NLTK data dir</label><input id="cfg-nltk" className="input mono" value={nltkDataDir} placeholder="未设置时跟随模型缓存目录 / nltk_data" onChange={(event) => setNltkDataDir(event.target.value)} /></div>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="config-card">
                  <h3>OpenDataLoader PDF</h3>
                  <div className="config-inner">
                    <div className="form-grid">
                      <div className="field"><label className="label" htmlFor="cfg-pdf-format">format</label><input id="cfg-pdf-format" className="input" value={pdfArgValue('format', 'markdown,text')} onChange={(event) => setPdfArg('format', event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-pages">pages</label><input id="cfg-pdf-pages" className="input" value={pdfArgValue('pages', '')} placeholder="全部" onChange={(event) => setPdfArg('pages', event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-threads">threads</label><input id="cfg-pdf-threads" className="input mono" value={pdfArgValue('threads', '1')} onChange={(event) => setPdfArg('threads', event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-image-output">image_output</label><select id="cfg-pdf-image-output" className="select" value={pdfArgValue('image_output', 'off')} onChange={(event) => setPdfArg('image_output', event.target.value)}><option value="off">off</option><option value="embedded">embedded</option><option value="external">external</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-image-format">image_format</label><select id="cfg-pdf-image-format" className="select" value={pdfArgValue('image_format', 'png')} onChange={(event) => setPdfArg('image_format', event.target.value)}><option value="png">png</option><option value="jpeg">jpeg</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-table">table_method</label><select id="cfg-pdf-table" className="select" value={pdfArgValue('table_method', 'default')} onChange={(event) => setPdfArg('table_method', event.target.value)}><option value="default">default</option><option value="cluster">cluster</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-reading">reading_order</label><select id="cfg-pdf-reading" className="select" value={pdfArgValue('reading_order', 'xycut')} onChange={(event) => setPdfArg('reading_order', event.target.value)}><option value="xycut">xycut</option><option value="off">off</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-hybrid">Hybrid backend</label><select id="cfg-pdf-hybrid" className="select" value={pdfArgValue('hybrid', 'off')} onChange={(event) => setPdfArg('hybrid', event.target.value)}><option value="off">off</option><option value="docling-fast">docling-fast</option><option value="hancom-ai">hancom-ai</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-hybrid-mode">hybrid_mode</label><select id="cfg-pdf-hybrid-mode" className="select" value={pdfArgValue('hybrid_mode', 'auto')} onChange={(event) => setPdfArg('hybrid_mode', event.target.value)}><option value="auto">auto</option><option value="full">full</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-timeout">hybrid_timeout</label><input id="cfg-pdf-timeout" className="input mono" value={pdfArgValue('hybrid_timeout', '')} placeholder="默认" onChange={(event) => setPdfArg('hybrid_timeout', event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-upload-limit">PDF 最大上传 MB</label><input id="cfg-pdf-upload-limit" className="input mono" type="number" min="0.001" step="0.1" value={maxPdfUploadMb} onChange={(event) => setMaxPdfUploadMb(event.target.value)} /></div>
                    </div>
                  </div>
                </div>

                <div className="config-card">
                  <h3>LLM 润色</h3>
                  <div className="config-inner">
                    <div className="form-grid">
                      <div className="field"><label className="label" htmlFor="cfg-whisperx-llm-enabled">音视频转写润色服务</label><select id="cfg-whisperx-llm-enabled" className="select" value={String(whisperxLlmPolishEnabled)} onChange={(event) => setWhisperxLlmPolishEnabled(event.target.value === 'true')}><option value="false">关闭</option><option value="true">开启</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-pdf-llm-enabled">PDF 润色服务</label><select id="cfg-pdf-llm-enabled" className="select" value={String(pdfLlmPolishEnabled)} onChange={(event) => setPdfLlmPolishEnabled(event.target.value === 'true')}><option value="false">关闭</option><option value="true">开启</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-llm-provider">供应商</label><select id="cfg-llm-provider" className="select" value={llmProvider} onChange={(event) => changeLlmProvider(event.target.value)}>{llmProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></div>
                      <div className="field field-full"><label className="label" htmlFor="cfg-llm-base-url">接口地址</label><input id="cfg-llm-base-url" className="input mono" value={llmBaseUrl} placeholder={llmProviderDefaultBaseUrl(llmProviders, llmProvider) || 'https://host/v1'} onChange={(event) => setLlmBaseUrl(event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-llm-api-key">API Key</label><input id="cfg-llm-api-key" className="input mono" type="password" value={llmApiKey} placeholder={llmApiKeyConfigured ? '已配置；留空保持不变' : '请输入供应商 API Key'} onChange={(event) => setLlmApiKey(event.target.value)} /></div>
                      <div className="field"><label className="label" htmlFor="cfg-llm-clear-key">清除 API Key</label><select id="cfg-llm-clear-key" className="select" value={String(llmClearApiKey)} onChange={(event) => setLlmClearApiKey(event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-llm-model">模型</label><input id="cfg-llm-model" className="input mono" value={llmModel} list="cfg-llm-model-list" placeholder="先拉取或手动填写模型名" onChange={(event) => setLlmModel(event.target.value)} /><datalist id="cfg-llm-model-list">{llmModels.map((model) => <option key={model} value={model} />)}</datalist></div>
                      <div className="field"><label className="label" htmlFor="cfg-llm-timeout">LLM timeout seconds</label><input id="cfg-llm-timeout" className="input mono" value={llmTimeoutSeconds} onChange={(event) => setLlmTimeoutSeconds(event.target.value)} /></div>
                      <div className="field field-full">
                        <div className="llm-actions-row">
                          <div className="btn-row llm-action-buttons">
                            <button className="btn" type="button" disabled={!signedIn || llmBusy} onClick={() => void checkLlmProviderConnection()}>
                              连接检查
                            </button>
                            <button className="btn" type="button" disabled={!signedIn || llmBusy} onClick={() => void loadLlmModels()}>
                              拉取模型
                            </button>
                          </div>
                          {llmModels.length > 0 ? (
                            <div className="llm-model-picker">
                              <label className="label" htmlFor="cfg-llm-model-select">选择已拉取模型</label>
                              <select
                                id="cfg-llm-model-select"
                                className="select mono"
                                value={llmModels.includes(llmModel) ? llmModel : ''}
                                onChange={(event) => setLlmModel(event.target.value)}
                              >
                                <option value="" disabled>选择模型（{llmModels.length} 个）</option>
                                {llmModels.map((model) => (
                                  <option key={model} value={model}>{model}</option>
                                ))}
                              </select>
                            </div>
                          ) : null}
                        </div>
                      </div>
                      {llmNotice ? (
                        <div className="field field-full">
                          {llmNotice.kind === 'error' ? (
                            <div className="error-banner" role="alert">
                              <strong>{llmNotice.title ?? 'LLM 操作失败'}</strong>
                              <div>{llmNotice.message}</div>
                            </div>
                          ) : (
                            <div className="llm-info-card" role="status" aria-live="polite">
                              <div className="llm-info-mark" aria-hidden="true">✓</div>
                              <div className="llm-info-body">
                                <div className="llm-info-title">{llmNotice.title ?? 'LLM 服务可用'}</div>
                                <div className="llm-info-message">{llmNotice.message}</div>
                                <div className="llm-info-meta">
                                  <span>供应商：{llmNotice.provider || llmProvider}</span>
                                  <span>接口：{llmNotice.baseUrl || llmBaseUrl || '供应商默认'}</span>
                                  {llmNotice.model ? <span>模型：{llmNotice.model}</span> : null}
                                  {typeof llmNotice.modelCount === 'number' ? (
                                    <span>可选模型：{llmNotice.modelCount}</span>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
              {!config && signedIn ? <div className="status-note">配置加载中或暂不可用。</div> : null}
            </Box>
          </div>

          <div className="span-12">
            <Box
              title="任务列表管理"
              subtitle="自动刷新间隔：3 秒 · running 任务不可删除"
              actions={
                <div className="filters">
                  {filters.map((item) => (
                    <button
                      className={filter === item ? 'filter active' : 'filter'}
                      key={item}
                      type="button"
                      onClick={() => changeFilter(item)}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              }
              dense
            >
              <div className="task-list-toolbar">
                <div className="task-type-tabs" role="tablist" aria-label="任务类型">
                  {taskTypeViews.map((item) => (
                    <button
                      aria-selected={taskTypeView === item.value}
                      className={taskTypeView === item.value ? 'filter active' : 'filter'}
                      key={item.value}
                      role="tab"
                      type="button"
                      onClick={() => changeTaskTypeView(item.value)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                <div className="pagination-summary">
                  当前显示 {taskTypeLabel(taskTypeView)} · {filteredJobs.length} 条
                </div>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    {isWhisperxView ? (
                      <tr>
                        <th>状态</th>
                        <th>进度</th>
                        <th>任务 ID</th>
                        <th>文件</th>
                        <th>时长</th>
                        <th>模型</th>
                        <th>语言</th>
                        <th>说话人</th>
                        <th>Artifacts</th>
                        <th>更新时间</th>
                        <th>操作</th>
                      </tr>
                    ) : (
                      <tr>
                        <th>状态</th>
                        <th>任务 ID</th>
                        <th>文件</th>
                        <th>清洗力度</th>
                        <th>Artifacts</th>
                        <th>更新时间</th>
                        <th>操作</th>
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {filteredJobs.length === 0 ? (
                      <tr>
                        <td colSpan={emptyColSpan}>登录后加载任务；当前类型或过滤条件暂无记录。</td>
                      </tr>
                    ) : (
                      pagedJobs.map((job) =>
                        isWhisperxView ? (
                          <tr key={job.jobId}>
                            <td>
                              <StatusPill status={job.status} />
                            </td>
                            <td>
                              <RuntimePhaseCompact phase={job.runtimePhase} />
                            </td>
                            <td className="job-id">{shortJobId(job.jobId)}</td>
                            <td>
                              <div className="truncate">{job.inputFilename ?? '—'}</div>
                            </td>
                            <td className="mono">{formatDuration(job.inputDurationSeconds)}</td>
                            <td>{optionValue(job, 'model')}</td>
                            <td>{optionValue(job, 'language')}</td>
                            <td>{optionValue(job, 'diarize')}</td>
                            <td className="mono">{job.artifacts.length}</td>
                            <td className="nowrap">{formatDate(job.updatedAt)}</td>
                            {renderJobActions(job)}
                          </tr>
                        ) : (
                          <tr key={job.jobId}>
                            <td>
                              <StatusPill status={job.status} />
                            </td>
                            <td className="job-id">{shortJobId(job.jobId)}</td>
                            <td>
                              <div className="truncate">{job.inputFilename ?? '—'}</div>
                            </td>
                            <td>{optionValue(job, 'markdownCleanupStrength', 'markdown_cleanup_strength')}</td>
                            <td className="mono">{job.artifacts.length}</td>
                            <td className="nowrap">{formatDate(job.updatedAt)}</td>
                            {renderJobActions(job)}
                          </tr>
                        ),
                      )
                    )}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <div className="pagination-summary">
                  第 {currentPage} / {pageCount} 页 · 共 {filteredJobs.length} 条 · 每页 {pageSize} 条
                </div>
                <div className="btn-row">
                  <button
                    className="btn"
                    type="button"
                    disabled={currentPage <= 1}
                    onClick={() => setPage(Math.max(1, currentPage - 1))}
                  >
                    上一页
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={currentPage >= pageCount}
                    onClick={() => setPage(Math.min(pageCount, currentPage + 1))}
                  >
                    下一页
                  </button>
                </div>
              </div>
            </Box>
          </div>

          <div className="span-12">
            <div className="danger-callout">
              删除任务前必须弹确认框：将永久删除上传文件、输出文件、日志和事件记录；running 状态任务禁用删除入口。
            </div>
          </div>
        </div>
      </section>

      {loginOpen ? (
        <aside className="login-modal" aria-hidden={false}>
          <button
            className="scrim"
            type="button"
            aria-label="关闭登录弹窗"
            onClick={() => setLoginOpen(false)}
          />
          <form
            className="login-panel login-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-login-title"
            onSubmit={signedIn ? (event) => event.preventDefault() : login}
          >
            <div className="panel-head compact">
              <div>
                <h2 id="admin-login-title">{signedIn ? '账号管理' : '管理员登录'}</h2>
                <p className="small">登录后可管理运行配置、历史任务和诊断信息。</p>
              </div>
              <button className="btn" type="button" onClick={() => setLoginOpen(false)}>
                关闭
              </button>
            </div>
            <div className={signedIn ? 'token-banner' : 'token-banner signed-out'}>
              <div>
                <strong>{signedIn ? '已登录' : '未登录'}</strong>
                <div className="small">token 与用户名保存到 localStorage</div>
              </div>
              <StatusPill status={signedIn ? 'valid' : 'idle'} />
            </div>
            {error ? <div className="error-banner">{error}</div> : null}
            <div className="form-grid">
              <div className="field">
                <label className="label" htmlFor="admin-username">
                  管理员账号
                </label>
                <input
                  id="admin-username"
                  className="input"
                  value={username ?? ''}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </div>
              <div className="field">
                <label className="label" htmlFor="admin-password">
                  {signedIn ? '当前密码' : '登录/当前密码'}
                </label>
                <input
                  id="admin-password"
                  className="input"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              {signedIn ? (
                <div className="field field-full">
                  <label className="label" htmlFor="admin-new-password">
                    新密码
                  </label>
                  <input
                    id="admin-new-password"
                    className="input"
                    type="password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                  />
                </div>
              ) : null}
            </div>
            <div className="btn-row">
              {signedIn ? (
                <>
                  <button className="btn" type="button" onClick={() => void saveAccount()} disabled={busy}>
                    修改账号名
                  </button>
                  <button className="btn btn-primary" type="button" onClick={() => void changePassword()} disabled={busy}>
                    修改密码
                  </button>
                </>
              ) : (
                <button className="btn btn-primary" type="submit" disabled={busy}>
                  登录
                </button>
              )}
            </div>
            <div className="small">token 失效时清理会话，并提示重新登录。</div>
          </form>
        </aside>
      ) : null}

      <aside className={selectedJob ? 'drawer open' : 'drawer'} aria-hidden={!selectedJob}>
        <button className="scrim" type="button" aria-label="关闭详情" onClick={closeDetail} />
        <div className="panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
          <div className="panel-head">
            <div>
              <div className="eyebrow">任务详情弹窗</div>
              <h2 id="drawer-title">{selectedJob?.jobId ?? '—'}</h2>
              <p className="small">查看完整元数据、错误详情、输出下载按钮、任务运行日志和后端运行日志。</p>
            </div>
            <button className="btn" type="button" onClick={closeDetail}>
              关闭 <span className="kbd">Esc</span>
            </button>
          </div>
          <div className="panel-body">
            {selectedJob ? (
              <>
                <div className="job-detail-summary">
                  <MetaList
                    items={[
                      { label: '完整任务 ID', value: selectedJob.jobId, mono: true },
                      { label: '文件名', value: selectedJob.inputFilename ?? '—' },
                      { label: '任务类型', value: taskTypeLabel(String(selectedJob.taskType)) },
                      { label: '文件大小', value: formatBytes(selectedJob.inputSizeBytes) },
                      { label: '状态', value: <StatusPill status={selectedJob.status} /> },
                      {
                        label: '当前进度',
                        value:
                          selectedJob.taskType === taskTypeWhisperx
                            ? runtimePhaseSummary(selectedJob.runtimePhase)
                            : '—',
                      },
                      { label: '更新时间', value: formatDate(selectedJob.updatedAt) },
                      { label: '错误详情', value: selectedJob.error ?? '—' },
                    ]}
                  />

                  <ArtifactZipDownload
                    job={selectedJob}
                    zipUrl={(jobId) => api.artifactsZipUrl(jobId)}
                  />
                </div>

                <div className="job-detail-logs">
                  <div className="preview task-run-log">
                    <div className="preview-head">
                      <strong>任务运行日志</strong>
                    </div>
                    <Timeline
                      rows={selectedEvents.map((event) => ({
                        time: formatDate(event.timestamp),
                        text: eventTimelineText(event),
                      }))}
                    />
                  </div>

                  <div className="preview cli-log-panel">
                    <div className="preview-head">
                      <strong>后端运行日志</strong>
                      <button className="btn" type="button" onClick={() => void downloadLog()}>
                        下载日志
                      </button>
                    </div>
                    <div className="cli-log-scroll" tabIndex={0} aria-label="后端运行日志内容">
                      <pre className="log">{selectedLog || '暂无日志。'}</pre>
                    </div>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
      </aside>
    </AppShell>
  );
}
