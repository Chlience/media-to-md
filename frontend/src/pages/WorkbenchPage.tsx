import { DragEvent, ReactNode, useEffect, useRef, useState } from 'react';
import { WhisperXApiClient, UploadableFile } from '../api/client';
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

function parseOptionalSpeakerCount(value: string, label: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${label}必须是大于等于 1 的整数。`);
  }
  return parsed;
}

const whisperxPhaseSteps = [
  {
    code: 'queued',
    label: '等待启动',
    detail: '任务已创建，等待后端启动转写。',
  },
  {
    code: 'starting',
    label: '启动转写任务',
    detail: '启动本地 CLI 或调用 OpenAI 兼容 WhisperX 服务。',
  },
  {
    code: 'model',
    label: '加载模型与参数',
    detail: '初始化设备、模型、缓存和语言设置。',
  },
  {
    code: 'vad',
    label: '语音活动检测',
    detail: '识别音频中的有效语音片段。',
  },
  {
    code: 'transcription',
    label: '语音转文字',
    detail: '持续生成转录文本片段。',
  },
  {
    code: 'alignment',
    label: '时间戳对齐',
    detail: '执行 alignment，整理字幕时间戳。',
  },
  {
    code: 'diarization',
    label: '说话人分离',
    detail: '为转写片段分配 SPEAKER 标签。',
  },
  {
    code: 'finalizing',
    label: '整理输出文件',
    detail: '收集 txt、srt、vtt 等下载产物。',
  },
  {
    code: 'succeeded',
    label: '已完成',
    detail: '任务成功结束，可下载结果。',
  },
] as const;

const phaseOrder: Map<string, number> = new Map(
  whisperxPhaseSteps.map((step, index) => [step.code, index]),
);

function resolveWhisperxPhase(job: JobStatus | null) {
  if (!job) {
    return {
      code: 'idle',
      label: '待提交',
      detail: '选择音视频文件后上传并启动转写。',
    };
  }
  if (job.runtimePhase) return job.runtimePhase;
  if (job.status === 'queued') return whisperxPhaseSteps[0];
  if (job.status === 'running') return whisperxPhaseSteps[1];
  if (job.status === 'succeeded') return whisperxPhaseSteps[whisperxPhaseSteps.length - 1];
  if (job.status === 'failed') {
    return {
      code: 'failed',
      label: '失败',
      detail: '任务失败，请进入管理员页面查看错误详情和日志。',
    };
  }
  if (job.status === 'cancelled') {
    return { code: 'cancelled', label: '已取消', detail: '任务已取消。' };
  }
  return { code: String(job.status), label: String(job.status), detail: '等待后端返回最新状态。' };
}

function PhaseBadge({ children, tone }: { children: ReactNode; tone: 'done' | 'active' | 'pending' }) {
  return <span className={`phase-badge phase-${tone}`}>{children}</span>;
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
  const currentIndex = phaseOrder.get(phase.code) ?? -1;

  return (
    <div className="phase-module" aria-label="音视频转写当前状态">
      <div className="phase-current">
        <div>
          <div className="phase-eyebrow">音视频转写当前状态</div>
          <h3>{phase.label}</h3>
          <p>{phase.detail}</p>
        </div>
      </div>
      <div className="phase-list">
        {whisperxPhaseSteps.map((step, index) => {
          const tone =
            currentIndex < 0
              ? 'pending'
              : index < currentIndex
                ? 'done'
                : index === currentIndex
                  ? 'active'
                  : 'pending';
          return (
            <div className={`phase-step phase-step-${tone}`} key={step.code}>
              <PhaseBadge tone={tone}>{index + 1}</PhaseBadge>
              <div>
                <div className="phase-step-title">{step.label}</div>
                <div className="small">{step.detail}</div>
              </div>
            </div>
          );
        })}
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
  const [diarize, setDiarize] = useState(false);
  const [minSpeakers, setMinSpeakers] = useState('');
  const [maxSpeakers, setMaxSpeakers] = useState('');
  const [cleanupStrength, setCleanupStrength] =
    useState<PdfCleanupStrength>(pdfCleanupStrengthBalanced);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => pollerRef.current?.stop(), []);

  const acceptedCopy =
    taskType === taskTypePdf
      ? '接受常见的 PDF 文档。'
      : '接受常见的音频/视频文件。';

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
    setFile(nextFile);
    setJob(null);
    setError(null);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    selectFile(event.dataTransfer.files.item(0));
  };

  const submit = async () => {
    if (!file) {
      setError('请先选择一个文件。');
      return;
    }
    pollerRef.current?.stop();
    setSubmitting(true);
    setError(null);
    try {
      const shouldDiarize = taskType === taskTypeWhisperx && diarize;
      const parsedMinSpeakers = shouldDiarize
        ? parseOptionalSpeakerCount(minSpeakers, '最少说话人数')
        : null;
      const parsedMaxSpeakers = shouldDiarize
        ? parseOptionalSpeakerCount(maxSpeakers, '最多说话人数')
        : null;
      if (
        parsedMinSpeakers !== null &&
        parsedMaxSpeakers !== null &&
        parsedMinSpeakers > parsedMaxSpeakers
      ) {
        throw new Error('最少说话人数不能大于最多说话人数。');
      }
      const uploaded = await api.uploadAndStart({
        file: fileToUploadable(file),
        options:
          taskType === taskTypePdf
            ? { taskType: taskTypePdf, markdownCleanupStrength: cleanupStrength }
            : {
                taskType: taskTypeWhisperx,
                language: languageMode === 'auto' ? 'auto' : language.trim() || 'auto',
                diarize,
                minSpeakers: parsedMinSpeakers,
                maxSpeakers: parsedMaxSpeakers,
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
                  <div className="field">
                    <label className="label" htmlFor="diarize-enabled">
                      说话人分离
                    </label>
                    <select
                      id="diarize-enabled"
                      className="select"
                      value={String(diarize)}
                      onChange={(event) => setDiarize(event.target.value === 'true')}
                    >
                      <option value="false">关闭</option>
                      <option value="true">开启</option>
                    </select>
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="min-speakers">
                      最少说话人数
                    </label>
                    <input
                      id="min-speakers"
                      className="input mono"
                      type="number"
                      min="1"
                      value={minSpeakers}
                      onChange={(event) => setMinSpeakers(event.target.value)}
                      placeholder="自动"
                      disabled={!diarize}
                    />
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="max-speakers">
                      最多说话人数
                    </label>
                    <input
                      id="max-speakers"
                      className="input mono"
                      type="number"
                      min="1"
                      value={maxSpeakers}
                      onChange={(event) => setMaxSpeakers(event.target.value)}
                      placeholder="自动"
                      disabled={!diarize}
                    />
                  </div>
                  <div className="field field-full">
                    <label className="label" htmlFor="media-output-formats">
                      输出格式
                    </label>
                    <input
                      id="media-output-formats"
                      className="input mono"
                      value={diarize ? 'output_formats=txt,srt,vtt,json' : 'output_formats=txt,srt,vtt'}
                      readOnly
                    />
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

            <div style={{ height: 16 }} />

            <Box title="Artifacts 下载" subtitle="成功后打包为单个 ZIP">
              <ArtifactZipDownload job={job} zipUrl={(jobId) => api.artifactsZipUrl(jobId)} />
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
          </div>
        </div>
      </section>
    </AppShell>
  );
}
