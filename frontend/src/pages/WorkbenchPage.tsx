import { DragEvent, useEffect, useRef } from 'react';
import { WhisperXApiClient } from '../api/client';
import {
  RuntimeProgressBar,
  runtimePercentText,
} from '../components/RuntimeProgress';
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
  taskTypePdf,
  taskTypeWhisperx,
  TaskType,
} from '../types/api';
import {
  LanguageMode,
  WorkbenchFileMeta,
  WorkbenchTasksController,
} from '../services/workbenchTasks';

const api = new WhisperXApiClient();

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

function fileInfoLabel(
  job: JobStatus | null,
  file: File | null,
  fileMeta: WorkbenchFileMeta | null,
): string {
  if (job) {
    const isPdfJob = job.taskType === taskTypePdf;
    const size = formatBytes(job.inputSizeBytes ?? fileMeta?.size);
    return isPdfJob
      ? `大小 ${size}`
      : `时长 ${formatDuration(job.inputDurationSeconds)} · 大小 ${size}`;
  }
  const size = file?.size ?? fileMeta?.size;
  if (size !== undefined && size !== null) return `大小 ${formatBytes(size)}`;
  return '—';
}

function fileNameLabel(
  job: JobStatus | null,
  file: File | null,
  fileMeta: WorkbenchFileMeta | null,
): string {
  return job?.inputFilename ?? file?.name ?? fileMeta?.name ?? '尚未选择文件';
}

function selectedFileLabel(file: File | null, fileMeta: WorkbenchFileMeta | null): string | null {
  if (file) return file.name;
  if (fileMeta) return `${fileMeta.name}（刷新后需重新选择）`;
  return null;
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

export function WorkbenchPage({ workbench }: { workbench: WorkbenchTasksController }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const taskType = workbench.activeTaskType;
  const {
    file,
    fileMeta,
    job,
    error,
    isSubmitting,
    languageMode,
    language,
    cleanupStrength,
  } = workbench.activeSlot;
  const currentUploadLimit = workbench.currentUploadLimit;

  useEffect(() => {
    if (!file && inputRef.current) inputRef.current.value = '';
  }, [file, taskType]);

  const requireUploadLimit = () => workbench.requireUploadLimit();

  const acceptedCopy =
    currentUploadLimit === null
      ? '正在读取后端上传限制，读取成功后才能选择文件。'
      : taskType === taskTypePdf
        ? `接受常见的 PDF 文档，单个文件不超过 ${formatBytes(currentUploadLimit.maxBytes)}。`
        : `接受常见的音频/视频文件，单个文件不超过 ${formatBytes(currentUploadLimit.maxBytes)}。`;

  const switchTaskType = (next: TaskType) => {
    if (next === taskType) return;
    workbench.switchTaskType(next);
  };

  const selectFile = (nextFile: File | null) => {
    const accepted = workbench.selectFile(nextFile);
    if (!accepted && inputRef.current) inputRef.current.value = '';
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!currentUploadLimit) {
      requireUploadLimit();
      return;
    }
    selectFile(event.dataTransfer.files.item(0));
  };

  const selectedLabel = selectedFileLabel(file, fileMeta);

  return (
    <AppShell activeRoute="workbench">
      <section id="workbench" className="screen active" aria-labelledby="workbench-title">
        <PageHeader
          title="本地转换工作台"
          description="提交音视频转写或 PDF 文档解析任务，跟踪任务状态，并在成功后下载生成的 artifacts。"
        />

        <div className="grid-12">
          <div className="span-5">
            <Box title="提交任务" subtitle="切换类型会保留各类型当前任务、文件和状态">
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
                onClick={() => {
                  if (currentUploadLimit) inputRef.current?.click();
                  else requireUploadLimit();
                }}
                role="button"
                tabIndex={0}
                aria-disabled={!currentUploadLimit}
              >
                <div>
                  <div className="drop-icon">↑</div>
                  <h3>拖拽文件到这里，或点击选择文件</h3>
                  <p className="small">{acceptedCopy}</p>
                  {selectedLabel ? <div className="selected-file">{selectedLabel}</div> : <div style={{ height: 12 }} />}
                  <button className="btn" type="button" disabled={!currentUploadLimit}>
                    选择文件
                  </button>
                  <input
                    key={taskType}
                    ref={inputRef}
                    type="file"
                    accept={taskType === taskTypePdf ? 'application/pdf,.pdf' : 'audio/*,video/*'}
                    disabled={!currentUploadLimit}
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
                      onChange={(event) => workbench.setLanguageMode(event.target.value as LanguageMode)}
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
                      onChange={(event) => workbench.setLanguage(event.target.value)}
                      placeholder="默认 auto；手动可填 en、zh、ja"
                      disabled={languageMode === 'auto'}
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
                      onChange={(event) => workbench.setCleanupStrength(event.target.value as PdfCleanupStrength)}
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
                <button className="btn btn-primary" type="button" onClick={() => void workbench.submit()} disabled={isSubmitting || !currentUploadLimit}>
                  {isSubmitting ? '提交中…' : currentUploadLimit ? '上传并启动任务' : '读取上传限制中…'}
                </button>
              </div>
            </Box>
          </div>

          <div className="span-7">
            <Box title="当前任务状态" actions={<StatusPill status={job?.status ?? 'idle'} />}>
              <MetaList
                items={[
                  { label: '任务 ID', value: job?.jobId ?? '尚未创建', mono: true },
                  { label: '文件名', value: fileNameLabel(job, file, fileMeta) },
                  {
                    label: '文件信息',
                    value: fileInfoLabel(job, file, fileMeta),
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
