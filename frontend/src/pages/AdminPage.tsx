import { FormEvent, useEffect, useMemo, useState } from 'react';
import { WhisperXApiClient } from '../api/client';
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
  taskTypeLabel,
  taskTypePdf,
  taskTypeWhisperx,
  WhisperxBackend,
} from '../types/api';
import { normalizeApiBaseUrl, readApiBaseUrl, saveApiBaseUrl } from '../services/apiBaseUrl';

const api = new WhisperXApiClient();
const sessionStore = new AdminSessionStore();
const filters = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'] as const;
const taskTypeViews = [
  { value: taskTypeWhisperx, label: '音视频转写任务' },
  { value: taskTypePdf, label: 'PDF 文档解析任务' },
] as const;
const pageSize = 10;
const defaultWhisperxModel = 'small';
const defaultModelCacheOnly = false;
const defaultWhisperxBackend: WhisperxBackend = 'cli';
const defaultOpenaiTimeoutSeconds = '3600';
const defaultWhisperxArgDisplay = {
  device: '',
  computeType: 'default',
  batchSize: '8',
  chunkSize: '',
  alignModel: '',
  diarizeModel: '',
  minSpeakers: '',
  maxSpeakers: '',
  speakerEmbeddings: false,
  noAlign: false,
} as const;

type Filter = (typeof filters)[number];
type TaskTypeView = (typeof taskTypeViews)[number]['value'];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
  const [apiBaseUrl, setApiBaseUrl] = useState(() => readApiBaseUrl());
  const [model, setModel] = useState(defaultWhisperxModel);
  const [modelDir, setModelDir] = useState('');
  const [whisperxBackend, setWhisperxBackend] = useState<WhisperxBackend>(defaultWhisperxBackend);
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiApiKeyConfigured, setOpenaiApiKeyConfigured] = useState(false);
  const [openaiClearApiKey, setOpenaiClearApiKey] = useState(false);
  const [openaiTimeoutSeconds, setOpenaiTimeoutSeconds] = useState(defaultOpenaiTimeoutSeconds);
  const [nltkDataDir, setNltkDataDir] = useState('');
  const [modelCacheOnly, setModelCacheOnly] = useState(defaultModelCacheOnly);
  const [whisperxArgs, setWhisperxArgs] = useState('{}');
  const [pdfArgs, setPdfArgs] = useState('{}');
  const [selectedJob, setSelectedJob] = useState<JobStatus | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<JobEvent[]>([]);
  const [selectedLog, setSelectedLog] = useState('');
  const [error, setError] = useState<string | null>(null);
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
  const emptyColSpan = isWhisperxView ? 10 : 7;

  const loadJobs = async (adminToken = token) => {
    if (!adminToken) return;
    const nextJobs = await api.fetchJobs({ adminToken, includeLog: false });
    setJobs(nextJobs);
  };

  const loadConfig = async (adminToken = token) => {
    if (!adminToken) return;
    const nextConfig = await api.fetchConfig(adminToken);
    setConfig(nextConfig);
    setApiBaseUrl(normalizeApiBaseUrl(nextConfig.apiBaseUrl ?? readApiBaseUrl()));
    setModel(nextConfig.model);
    setModelDir(nextConfig.modelDir ?? '');
    setWhisperxBackend(nextConfig.whisperxBackend);
    setOpenaiBaseUrl(nextConfig.whisperxOpenaiBaseUrl ?? '');
    setOpenaiApiKey('');
    setOpenaiApiKeyConfigured(nextConfig.whisperxOpenaiApiKeyConfigured);
    setOpenaiClearApiKey(false);
    setOpenaiTimeoutSeconds(String(nextConfig.whisperxOpenaiTimeoutSeconds || 3600));
    setNltkDataDir(nextConfig.nltkDataDir ?? '');
    setModelCacheOnly(nextConfig.modelCacheOnly);
    setWhisperxArgs(jsonPreview(nextConfig.whisperxArgsConfig));
    setPdfArgs(jsonPreview(nextConfig.pdfArgsConfig));
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

  const applyBrowserApiBaseUrl = (): string => {
    const normalized = saveApiBaseUrl(apiBaseUrl);
    api.setBaseUrl(normalized);
    setApiBaseUrl(normalized);
    setError(null);
    return normalized;
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

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      applyBrowserApiBaseUrl();
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
    try {
      const apiBaseUrlForSave = applyBrowserApiBaseUrl();
      const parsedOpenaiTimeoutSeconds = Number(openaiTimeoutSeconds || defaultOpenaiTimeoutSeconds);
      if (!Number.isFinite(parsedOpenaiTimeoutSeconds) || parsedOpenaiTimeoutSeconds <= 0) {
        throw new Error('OpenAI timeout seconds 必须是大于 0 的数字。');
      }
      const nextConfig = await api.updateConfig({
        adminToken: token,
        apiBaseUrl: apiBaseUrlForSave,
        model,
        modelDir,
        whisperxBackend,
        whisperxOpenaiBaseUrl: openaiBaseUrl,
        whisperxOpenaiApiKey: openaiApiKey,
        whisperxOpenaiClearApiKey: openaiClearApiKey,
        whisperxOpenaiTimeoutSeconds: parsedOpenaiTimeoutSeconds,
        modelCacheOnly,
        nltkDataDir,
        whisperxArgs: parseJsonObject(whisperxArgs),
        pdfArgs: parseJsonObject(pdfArgs),
      });
      const normalizedApiBaseUrl = saveApiBaseUrl(nextConfig.apiBaseUrl ?? apiBaseUrlForSave);
      setApiBaseUrl(normalizedApiBaseUrl);
      setConfig(nextConfig);
      setWhisperxBackend(nextConfig.whisperxBackend);
      setOpenaiBaseUrl(nextConfig.whisperxOpenaiBaseUrl ?? '');
      setOpenaiApiKey('');
      setOpenaiApiKeyConfigured(nextConfig.whisperxOpenaiApiKeyConfigured);
      setOpenaiClearApiKey(false);
      setOpenaiTimeoutSeconds(String(nextConfig.whisperxOpenaiTimeoutSeconds || 3600));
      setWhisperxArgs(jsonPreview(nextConfig.whisperxArgsConfig));
      setPdfArgs(jsonPreview(nextConfig.pdfArgsConfig));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy(false);
    }
  };

  const openDetail = async (job: JobStatus) => {
    setSelectedJob(job);
    setSelectedEvents([]);
    setSelectedLog('');
    if (!token) return;
    try {
      const [events, log] = await Promise.all([
        api.fetchJobEvents({ adminToken: token, jobId: job.jobId }),
        api.fetchJobLog({ adminToken: token, jobId: job.jobId }),
      ]);
      setSelectedEvents(events);
      setSelectedLog(log);
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
    String(parseJsonObjectOrEmpty(whisperxArgs)[key] ?? defaultValue);
  const whisperxArgBooleanValue = (key: string, defaultValue: boolean) => {
    const value = parseJsonObjectOrEmpty(whisperxArgs)[key];
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
      if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
    }
    return defaultValue;
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
    setArgValue(whisperxArgs, setWhisperxArgs, key, value);
  const setWhisperxBooleanArg = (key: string, value: boolean) => {
    const next = parseJsonObjectOrEmpty(whisperxArgs);
    if (value) {
      next[key] = true;
    } else {
      delete next[key];
    }
    setWhisperxArgs(formatJsonObject(next));
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
                <>
                  <button className="btn" type="button" onClick={applyBrowserApiBaseUrl} disabled={busy}>
                    应用 API 地址到本浏览器
                  </button>
                  <button className="btn btn-primary" type="button" onClick={() => void saveConfig()} disabled={!signedIn || busy}>
                    保存 config
                  </button>
                </>
              }
            >
              <div className="form-grid">
                <div className="field field-full">
                  <label className="label" htmlFor="cfg-api-base-url">API Base URL</label>
                  <input id="cfg-api-base-url" className="input mono" value={apiBaseUrl} onChange={(event) => setApiBaseUrl(event.target.value)} />
                </div>
              </div>
              <div style={{ height: 16 }} />
              <div className="config-grid">
                <div className="config-card">
                  <h3>WhisperX</h3>
                  <div className="config-inner">
                    <div className="form-grid">
                      <div className="field"><label className="label" htmlFor="cfg-whisperx-backend">执行方式</label><select id="cfg-whisperx-backend" className="select" value={whisperxBackend} onChange={(event) => setWhisperxBackend(event.target.value as WhisperxBackend)}><option value="cli">本机 CLI</option><option value="openai">OpenAI 兼容接口</option></select></div>
                      <div className="field"><label className="label" htmlFor="cfg-model">默认模型</label><input id="cfg-model" className="input" value={model} placeholder={defaultWhisperxModel} onChange={(event) => setModel(event.target.value)} /></div>
                      {whisperxBackend === 'openai' ? (
                        <>
                          <div className="field field-full"><div className="status-note">OpenAI 模式只显示接口配置，以及会随 multipart 请求转发给远端服务的参数；设备、缓存和 compute type 由远端服务控制。</div></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-base-url">OpenAI Base URL</label><input id="cfg-openai-base-url" className="input mono" value={openaiBaseUrl} placeholder="http://localhost:9000/v1" onChange={(event) => setOpenaiBaseUrl(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-api-key">OpenAI API Key</label><input id="cfg-openai-api-key" className="input mono" type="password" value={openaiApiKey} placeholder={openaiApiKeyConfigured ? '已配置；留空保持不变' : '未配置则不发送 Authorization'} onChange={(event) => setOpenaiApiKey(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-timeout">OpenAI timeout seconds</label><input id="cfg-openai-timeout" className="input mono" value={openaiTimeoutSeconds} onChange={(event) => setOpenaiTimeoutSeconds(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-openai-clear-key">清除 OpenAI Key</label><select id="cfg-openai-clear-key" className="select" value={String(openaiClearApiKey)} onChange={(event) => setOpenaiClearApiKey(event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-batch-size">Batch size</label><input id="cfg-batch-size" className="input mono" value={whisperxArgValue('batch_size', defaultWhisperxArgDisplay.batchSize)} onChange={(event) => setWhisperxArg('batch_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-chunk-size">Chunk size</label><input id="cfg-chunk-size" className="input mono" value={whisperxArgValue('chunk_size', defaultWhisperxArgDisplay.chunkSize)} placeholder="远端默认" onChange={(event) => setWhisperxArg('chunk_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-no-align">No align</label><select id="cfg-no-align" className="select" value={String(whisperxArgBooleanValue('no_align', defaultWhisperxArgDisplay.noAlign))} onChange={(event) => setWhisperxBooleanArg('no_align', event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-align-model">Align model</label><input id="cfg-align-model" className="input" value={whisperxArgValue('align_model', defaultWhisperxArgDisplay.alignModel)} placeholder="远端自动" onChange={(event) => setWhisperxArg('align_model', event.target.value)} /></div>
                          <div className="field field-full"><label className="label" htmlFor="cfg-diarize-model">Diarize model</label><input id="cfg-diarize-model" className="input mono" value={whisperxArgValue('diarize_model', defaultWhisperxArgDisplay.diarizeModel)} placeholder="远端默认不指定；例如 /models/pyannote-speaker-diarization-community-1" onChange={(event) => setWhisperxArg('diarize_model', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-min-speakers">Min speakers</label><input id="cfg-min-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('min_speakers', defaultWhisperxArgDisplay.minSpeakers)} placeholder="远端默认：自动" onChange={(event) => setWhisperxArg('min_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-max-speakers">Max speakers</label><input id="cfg-max-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('max_speakers', defaultWhisperxArgDisplay.maxSpeakers)} placeholder="远端默认：自动" onChange={(event) => setWhisperxArg('max_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-speaker-embeddings">Speaker embeddings</label><select id="cfg-speaker-embeddings" className="select" value={String(whisperxArgBooleanValue('speaker_embeddings', defaultWhisperxArgDisplay.speakerEmbeddings))} onChange={(event) => setWhisperxBooleanArg('speaker_embeddings', event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                        </>
                      ) : (
                        <>
                          <div className="field field-full"><div className="status-note">本机 CLI 模式显示本进程启动 whisperx 时会用到的本地运行参数；OpenAI 接口地址和 Key 不参与本机 CLI 调用。</div></div>
                          <div className="field"><label className="label" htmlFor="cfg-model-dir">模型缓存目录</label><input id="cfg-model-dir" className="input mono" value={modelDir} placeholder="默认不指定" onChange={(event) => setModelDir(event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-device">Device</label><select id="cfg-device" className="select" value={whisperxArgValue('device', defaultWhisperxArgDisplay.device)} onChange={(event) => setWhisperxArg('device', event.target.value)}><option value="">后端默认（未指定）</option><option value="cuda">cuda</option><option value="cpu">cpu</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-compute-type">Compute type</label><select id="cfg-compute-type" className="select" value={whisperxArgValue('compute_type', defaultWhisperxArgDisplay.computeType)} onChange={(event) => setWhisperxArg('compute_type', event.target.value)}><option value="default">default</option><option value="float16">float16</option><option value="float32">float32</option><option value="int8">int8</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-batch-size">Batch size</label><input id="cfg-batch-size" className="input mono" value={whisperxArgValue('batch_size', defaultWhisperxArgDisplay.batchSize)} onChange={(event) => setWhisperxArg('batch_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-chunk-size">Chunk size</label><input id="cfg-chunk-size" className="input mono" value={whisperxArgValue('chunk_size', defaultWhisperxArgDisplay.chunkSize)} placeholder="后端默认" onChange={(event) => setWhisperxArg('chunk_size', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-no-align">No align</label><select id="cfg-no-align" className="select" value={String(whisperxArgBooleanValue('no_align', defaultWhisperxArgDisplay.noAlign))} onChange={(event) => setWhisperxBooleanArg('no_align', event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
                          <div className="field"><label className="label" htmlFor="cfg-align-model">Align model</label><input id="cfg-align-model" className="input" value={whisperxArgValue('align_model', defaultWhisperxArgDisplay.alignModel)} placeholder="后端自动" onChange={(event) => setWhisperxArg('align_model', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-cache-only">仅使用本地缓存</label><select id="cfg-cache-only" className="select" value={String(modelCacheOnly)} onChange={(event) => setModelCacheOnly(event.target.value === 'true')}><option value="true">true</option><option value="false">false</option></select></div>
                          <div className="field field-full"><label className="label" htmlFor="cfg-diarize-model">Diarize model</label><input id="cfg-diarize-model" className="input mono" value={whisperxArgValue('diarize_model', defaultWhisperxArgDisplay.diarizeModel)} placeholder="后端默认不指定；例如 /models/whisperx-cache/pyannote-speaker-diarization-community-1" onChange={(event) => setWhisperxArg('diarize_model', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-min-speakers">Min speakers</label><input id="cfg-min-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('min_speakers', defaultWhisperxArgDisplay.minSpeakers)} placeholder="后端默认：自动" onChange={(event) => setWhisperxArg('min_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-max-speakers">Max speakers</label><input id="cfg-max-speakers" className="input mono" type="number" min="1" value={whisperxArgValue('max_speakers', defaultWhisperxArgDisplay.maxSpeakers)} placeholder="后端默认：自动" onChange={(event) => setWhisperxArg('max_speakers', event.target.value)} /></div>
                          <div className="field"><label className="label" htmlFor="cfg-speaker-embeddings">Speaker embeddings</label><select id="cfg-speaker-embeddings" className="select" value={String(whisperxArgBooleanValue('speaker_embeddings', defaultWhisperxArgDisplay.speakerEmbeddings))} onChange={(event) => setWhisperxBooleanArg('speaker_embeddings', event.target.value === 'true')}><option value="false">false</option><option value="true">true</option></select></div>
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
              <p className="small">查看完整元数据、错误详情、输出下载按钮、任务运行日志和 CLI运行日志。</p>
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
                        text: `${event.type}: ${event.message}`,
                      }))}
                    />
                  </div>

                  <div className="preview cli-log-panel">
                    <div className="preview-head">
                      <strong>CLI运行日志</strong>
                      <button className="btn" type="button" onClick={() => void downloadLog()}>
                        下载日志
                      </button>
                    </div>
                    <div className="cli-log-scroll" tabIndex={0} aria-label="CLI运行日志内容">
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
