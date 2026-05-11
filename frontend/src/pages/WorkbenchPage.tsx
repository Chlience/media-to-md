import { DragEvent, useEffect, useRef, useState } from 'react';
import { WhisperXApiClient, UploadableFile } from '../api/client';
import {
  RuntimeProgressBar,
  runtimePercentText,
} from '../components/RuntimeProgress';
import { MAX_UPLOAD_SIZE_BYTES } from '../config/upload';
import { AppShell, PageHeader } from '../components/Shell';
import {
  ArtifactZipDownload,
  Box,
  MetaList,
  StatusPill,
  formatBytes,
  formatDuration,
} from '../components/Primitives';
import {
  JobStatus,
  PdfCleanupStrength,
  pdfCleanupStrengthBalanced,
  taskTypePdf,
  taskTypeWhisperx,
  TaskType,
} from '../types/api';
import { startJobStatusPolling } from '../services/jobs';

type LanguageMode = 'auto' | 'manual';

const api = new WhisperXApiClient();

function fileToUploadable(file: File): UploadableFile {
  return file as UploadableFile;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fileSizeLimitError(file: File): string | null {
  if (file.size <= MAX_UPLOAD_SIZE_BYTES) return null;
  return `文件超过最大上传限制：最大 ${formatBytes(MAX_UPLOAD_SIZE_BYTES)}，当前 ${formatBytes(file.size)}。`;
}

function resolveWhisperxPhase(job: JobStatus | null) {
  if (!job) {
    return {
      process: 'whisperx',
      code: 'idle',
      label: '待提交',
      detail: '选择音视频文件后上传并启动转写。',
      stagePercent: null,
    };
  }
  if (job.runtimePhase) return job.runtimePhase;
  if (job.status === 'queued') {
    return {
      process: 'whisperx',
      code: 'queued',
      label: '等待启动',
      detail: '任务已创建，等待后端启动转写。',
      stagePercent: null,
    };
  }
  if (job.status === 'running') {
    return {
      process: 'whisperx',
      code: 'starting',
      label: '启动转写任务',
      detail: '后端已接收任务，正在启动本地 CLI 或 OpenAI 兼容调用。',
      stagePercent: null,
    };
  }
  if (job.status === 'succeeded') {
    return {
      process: 'whisperx',
      code: 'succeeded',
      label: '已完成',
      detail: '任务成功结束，可下载结果。',
      stagePercent: 100,
    };
  }
  if (job.status === 'failed') {
    return {
      process: 'whisperx',
      code: 'failed',
      label: '失败',
      detail: '任务失败，请进入管理员页面查看错误详情和日志。',
      stagePercent: null,
    };
  }
  if (job.status === 'cancelled') {
    return {
      process: 'whisperx',
      code: 'cancelled',
      label: '已取消',
      detail: '任务已取消。',
      stagePercent: null,
    };
  }
  return {
    process: 'whisperx',
    code: String(job.status),
    label: String(job.status),
    detail: '等待后端返回最新状态。',
    stagePercent: null,
  };
}

function fileInfoLabel(job: JobStatus | null, file: File | null): string {
  if (job) {
    const isPdfJob = job.taskType === taskTypePdf;
    const size = formatBytes(job.inputSizeBytes);
    return isPdfJob
      ? `大小 ${size}`
      : `时长 ${formatDuration(job.inputDurationSeconds)} · 大小 ${size}`;
  }
  if (file) return `大小 ${formatBytes(file.size)}`;
  return '—';
}

function WhisperxPhaseModule({ job }: { job: JobStatus | null }) {
  const phase = resolveWhisperxPhase(job);

  return (
    <div className="phase-module" aria-label="音视频转写当前状态">
      <div className="phase-current">
        <div className="phase-content">
          <div className="phase-eyebrow">音视频转写当前状态</div>
          <h3>{phase.label}</h3>
          <p>{phase.detail}</p>
          <div className="phase-progress-label">{runtimePercentText(phase)}</div>
          <RuntimeProgressBar phase={phase} showText={false} />
        </div>
      </div>
    </div>
  );
}

export function WorkbenchPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const pollerRef = useRef<{ stop(): void } | null>(null);
  const [taskType, setTaskType] = useState<TaskType>(taskTypeWhisperx);
  const [languageMode, setLanguageMode] = useState<LanguageMode>('auto');
  const [language, setLanguage] = useState('');
  const [cleanupStrength, setCleanupStrength] =
    useState<PdfCleanupStrength>(pdfCleanupStrengthBalanced);
  const [llmPolish, setLlmPolish] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => pollerRef.current?.stop(), []);

  const acceptedCopy =
    taskType === taskTypePdf
      ? `接受常见的 PDF 文档，单个文件不超过 ${formatBytes(MAX_UPLOAD_SIZE_BYTES)}。`
      : `接受常见的音频/视频文件，单个文件不超过 ${formatBytes(MAX_UPLOAD_SIZE_BYTES)}。`;

  const reset = () => {
    pollerRef.current?.stop();
    pollerRef.current = null;
    setFile(null);
    setJob(null);
    setError(null);
    setSubmitting(false);
    if (inputRef.current) inputRef.current.value = '';
  };

  const switchTaskType = (next: TaskType) => {
    if (next === taskType) return;
    setTaskType(next);
    reset();
  };

  const selectFile = (nextFile: File | null) => {
    setJob(null);
    if (!nextFile) {
      setFile(null);
      setError(null);
      return;
    }
    const sizeError = fileSizeLimitError(nextFile);
    if (sizeError) {
      setFile(null);
      setError(sizeError);
      if (inputRef.current) inputRef.current.value = '';
      return;
    }
    setFile(nextFile);
    setError(null);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    selectFile(event.dataTransfer.files.item(0));
  };

  const submit = async () => {
    if (!file) {
      setError((currentError) => currentError ?? '请先选择一个文件。');
      return;
    }
    const sizeError = fileSizeLimitError(file);
    if (sizeError) {
      setFile(null);
      setError(sizeError);
      if (inputRef.current) inputRef.current.value = '';
      return;
    }
    pollerRef.current?.stop();
    setSubmitting(true);
    setError(null);
    try {
      const uploaded = await api.uploadAndStart({
        file: fileToUploadable(file),
        options:
          taskType === taskTypePdf
            ? {
                taskType: taskTypePdf,
                markdownCleanupStrength: cleanupStrength,
                llmPolish,
              }
            : {
                taskType: taskTypeWhisperx,
                language: languageMode === 'auto' ? 'auto' : language.trim() || 'auto',
                llmPolish,
              },
      });
      const initial: JobStatus = {
        jobId: uploaded.jobId,
        status: uploaded.status,
        taskType,
        inputFilename: file.name,
        inputSizeBytes: file.size,
        artifacts: [],
      };
      setJob(initial);
      pollerRef.current = startJobStatusPolling({
        api,
        jobId: uploaded.jobId,
        intervalMs: 2000,
        onStatus: setJob,
        onSuccessResults: setJob,
        onError: (nextError) => setError(errorMessage(nextError)),
      });
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell activeRoute="workbench">
      <section id="workbench" className="screen active" aria-labelledby="workbench-title">
        <PageHeader
          title="本地转换工作台"
          description="提交音视频转写或 PDF 文档解析任务，跟踪任务状态，并在成功后下载生成的 artifacts。"
        />

        <div className="grid-12">
          <div className="span-5">
            <Box title="提交任务" subtitle="切换类型会清空文件、状态和错误">
              <div className="segmented" role="tablist" aria-label="Task type">
                <button
                  className={taskType === taskTypeWhisperx ? 'active' : undefined}
                  type="button"
                  onClick={() => switchTaskType(taskTypeWhisperx)}
                >
                  <span className="seg-title">音视频转写</span>
                  <span className="seg-desc">从音视频文件中提取字幕与转写文本</span>
                </button>
                <button
                  className={taskType === taskTypePdf ? 'active' : undefined}
                  type="button"
                  onClick={() => switchTaskType(taskTypePdf)}
                >
                  <span className="seg-title">PDF 文档解析</span>
                  <span className="seg-desc">将 PDF 转换为适合大模型处理的 Markdown/TXT</span>
                </button>
              </div>

              <div style={{ height: 16 }} />

              <div
                className="dropzone"
                onDragOver={(event) => event.preventDefault()}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                role="button"
                tabIndex={0}
              >
                <div>
                  <div className="drop-icon">↑</div>
                  <h3>拖拽文件到这里，或点击选择文件</h3>
                  <p className="small">{acceptedCopy}</p>
                  {file ? <div className="selected-file">{file.name}</div> : <div style={{ height: 12 }} />}
                  <button className="btn" type="button">
                    选择文件
                  </button>
                  <input
                    ref={inputRef}
                    type="file"
                    accept={taskType === taskTypePdf ? 'application/pdf,.pdf' : 'audio/*,video/*'}
                    onChange={(event) => selectFile(event.target.files?.item(0) ?? null)}
                  />
                </div>
              </div>

              <div style={{ height: 16 }} />

              {taskType === taskTypeWhisperx ? (
                <div className="form-grid">
                  <div className="field">
                    <label className="label" htmlFor="language-mode">
                      语言识别
                    </label>
                    <select
                      id="language-mode"
                      className="select"
                      value={languageMode}
                      onChange={(event) => setLanguageMode(event.target.value as LanguageMode)}
                    >
                      <option value="auto">自动识别</option>
                      <option value="manual">手动指定</option>
                    </select>
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="language-code">
                      语言代码
                    </label>
                    <input
                      id="language-code"
                      className="input"
                      value={language}
                      onChange={(event) => setLanguage(event.target.value)}
                      placeholder="默认 auto；手动可填 en、zh、ja"
                      disabled={languageMode === 'auto'}
                    />
                  </div>
                  <div className="field field-full">
                    <div className="status-note">
                      说话人分离默认开启，由后端统一执行，不需要单独配置。
                    </div>
                  </div>
                </div>
              ) : (
                <div className="form-grid">
                  <div className="field">
                    <label className="label" htmlFor="cleanup-strength">
                      Markdown 清洗力度
                    </label>
                    <select
                      id="cleanup-strength"
                      className="select"
                      value={cleanupStrength}
                      onChange={(event) => setCleanupStrength(event.target.value as PdfCleanupStrength)}
                    >
                      <option value="off">关闭</option>
                      <option value="conservative">保守</option>
                      <option value="balanced">均衡</option>
                      <option value="aggressive">激进</option>
                    </select>
                  </div>
                </div>
              )}
              <div style={{ height: 16 }} />
              <div className="form-grid">
                <div className="field">
                  <label className="label" htmlFor="llm-polish-enabled">
                    LLM 润色
                  </label>
                  <select
                    id="llm-polish-enabled"
                    className="select"
                    value={String(llmPolish)}
                    onChange={(event) => setLlmPolish(event.target.value === 'true')}
                  >
                    <option value="false">关闭</option>
                    <option value="true">开启</option>
                  </select>
                </div>
                <div className="field field-full">
                  <div className="status-note">
                    开启后会在原始转写/PDF 结果之外额外生成 LLM 润色版 Markdown；需先在管理员页面配置供应商、API Key、接口地址和模型。
                  </div>
                </div>
              </div>
              {error ? (
                <>
                  <div style={{ height: 16 }} />
                  <div className="error-banner">{error}</div>
                </>
              ) : null}

              <div style={{ height: 16 }} />
              <div className="btn-row submit-row">
                <button className="btn btn-primary" type="button" onClick={submit} disabled={isSubmitting}>
                  {isSubmitting ? '提交中…' : '上传并启动任务'}
                </button>
              </div>
            </Box>
          </div>

          <div className="span-7">
            <Box title="当前任务状态" actions={<StatusPill status={job?.status ?? 'idle'} />}>
              <MetaList
                items={[
                  { label: '任务 ID', value: job?.jobId ?? '尚未创建', mono: true },
                  { label: '文件名', value: job?.inputFilename ?? file?.name ?? '尚未选择文件' },
                  {
                    label: '文件信息',
                    value: fileInfoLabel(job, file),
                  },
                ]}
              />

              <div style={{ height: 16 }} />
              {taskType === taskTypeWhisperx || job?.taskType === taskTypeWhisperx ? (
                <WhisperxPhaseModule job={job} />
              ) : (
                <div className="status-note">
                  PDF 文档解析状态以任务总状态为准；详细运行记录仅在管理员页面查看。
                </div>
              )}

              {job?.error ? (
                <>
                  <div style={{ height: 16 }} />
                  <div className="error-banner">{job.error}</div>
                </>
              ) : null}
            </Box>

            <div style={{ height: 16 }} />

            <Box title="Artifacts 下载" subtitle="成功后打包为单个 ZIP">
              <ArtifactZipDownload job={job} zipUrl={(jobId) => api.artifactsZipUrl(jobId)} />
            </Box>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
