import { useEffect, useMemo, useRef, useState } from 'react';
import { WhisperXApiClient, UploadableFile } from '../api/client';
import { startJobStatusPolling, JobPollingController } from './jobs';
import {
  isTerminalStatus,
  JobStatus,
  PdfCleanupStrength,
  pdfCleanupStrengthBalanced,
  pdfCleanupStrengths,
  taskTypePdf,
  taskTypeWhisperx,
  TaskType,
  UploadLimit,
  UploadLimits,
} from '../types/api';

export type LanguageMode = 'auto' | 'manual';

export interface WorkbenchFileMeta {
  name: string;
  size: number;
}

export interface WorkbenchTaskSlot {
  file: File | null;
  fileMeta: WorkbenchFileMeta | null;
  job: JobStatus | null;
  error: string | null;
  isSubmitting: boolean;
  languageMode: LanguageMode;
  language: string;
  cleanupStrength: PdfCleanupStrength;
}

export interface WorkbenchTasksController {
  activeTaskType: TaskType;
  activeSlot: WorkbenchTaskSlot;
  slots: Record<TaskType, WorkbenchTaskSlot>;
  uploadLimits: UploadLimits | null;
  uploadLimitsError: string | null;
  currentUploadLimit: UploadLimit | null;
  requireUploadLimit(): boolean;
  switchTaskType(next: TaskType): void;
  selectFile(nextFile: File | null): boolean;
  submit(): Promise<void>;
  clearActiveSlot(): void;
  setLanguageMode(next: LanguageMode): void;
  setLanguage(next: string): void;
  setCleanupStrength(next: PdfCleanupStrength): void;
}

interface PersistedWorkbenchSlot {
  jobId?: string | null;
  fileMeta?: WorkbenchFileMeta | null;
  languageMode?: LanguageMode;
  language?: string;
  cleanupStrength?: PdfCleanupStrength;
}

interface PersistedWorkbenchState {
  activeTaskType?: TaskType;
  slots?: Partial<Record<TaskType, PersistedWorkbenchSlot>>;
}

interface WorkbenchState {
  activeTaskType: TaskType;
  slots: Record<TaskType, WorkbenchTaskSlot>;
}

const storageKey = 'media_to_md_workbench_tasks_v1';
const taskTypes = [taskTypeWhisperx, taskTypePdf] as const;

function fileToUploadable(file: File): UploadableFile {
  return file as UploadableFile;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function fileSizeLimitError(file: File, limit: UploadLimit): string | null {
  if (file.size <= limit.maxBytes) return null;
  return `文件超过最大上传限制：最大 ${formatBytes(limit.maxBytes)}，当前 ${formatBytes(file.size)}。`;
}

function isTaskType(value: unknown): value is TaskType {
  return value === taskTypeWhisperx || value === taskTypePdf;
}

function isLanguageMode(value: unknown): value is LanguageMode {
  return value === 'auto' || value === 'manual';
}

function isCleanupStrength(value: unknown): value is PdfCleanupStrength {
  return (pdfCleanupStrengths as readonly string[]).includes(String(value));
}

function isFileMeta(value: unknown): value is WorkbenchFileMeta {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.name === 'string' && typeof record.size === 'number' && record.size >= 0;
}

function readPersistedState(): PersistedWorkbenchState | null {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedWorkbenchState;
    return typeof parsed === 'object' && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

function writePersistedState(state: WorkbenchState): void {
  const persisted: PersistedWorkbenchState = {
    activeTaskType: state.activeTaskType,
    slots: Object.fromEntries(
      taskTypes.map((taskType) => {
        const slot = state.slots[taskType];
        return [
          taskType,
          {
            jobId: slot.job?.jobId ?? null,
            fileMeta: slot.fileMeta,
            languageMode: slot.languageMode,
            language: slot.language,
            cleanupStrength: slot.cleanupStrength,
          },
        ];
      }),
    ) as PersistedWorkbenchState['slots'],
  };

  try {
    window.localStorage.setItem(storageKey, JSON.stringify(persisted));
  } catch {
    // Storage can be unavailable in private/incognito modes. Runtime state still works.
  }
}

function slotFromPersisted(
  taskType: TaskType,
  persistedSlot: PersistedWorkbenchSlot | undefined,
): WorkbenchTaskSlot {
  const fileMeta = isFileMeta(persistedSlot?.fileMeta) ? persistedSlot.fileMeta : null;
  const jobId = typeof persistedSlot?.jobId === 'string' && persistedSlot.jobId.trim()
    ? persistedSlot.jobId.trim()
    : null;
  return {
    file: null,
    fileMeta,
    job: jobId
      ? {
          jobId,
          status: 'queued',
          taskType,
          inputFilename: fileMeta?.name ?? null,
          inputSizeBytes: fileMeta?.size ?? null,
          artifacts: [],
        }
      : null,
    error: null,
    isSubmitting: false,
    languageMode: isLanguageMode(persistedSlot?.languageMode) ? persistedSlot.languageMode : 'auto',
    language: typeof persistedSlot?.language === 'string' ? persistedSlot.language : '',
    cleanupStrength: isCleanupStrength(persistedSlot?.cleanupStrength)
      ? persistedSlot.cleanupStrength
      : pdfCleanupStrengthBalanced,
  };
}

function createInitialState(): WorkbenchState {
  const persisted = readPersistedState();
  const activeTaskType = isTaskType(persisted?.activeTaskType)
    ? persisted.activeTaskType
    : taskTypeWhisperx;
  return {
    activeTaskType,
    slots: {
      [taskTypeWhisperx]: slotFromPersisted(taskTypeWhisperx, persisted?.slots?.[taskTypeWhisperx]),
      [taskTypePdf]: slotFromPersisted(taskTypePdf, persisted?.slots?.[taskTypePdf]),
    },
  };
}

function withFileMeta(job: JobStatus, fallback: WorkbenchFileMeta | null): WorkbenchFileMeta | null {
  if (job.inputFilename) {
    return {
      name: job.inputFilename,
      size: job.inputSizeBytes ?? fallback?.size ?? 0,
    };
  }
  return fallback;
}

export function useWorkbenchTasks(): WorkbenchTasksController {
  const apiRef = useRef<WhisperXApiClient | null>(null);
  if (!apiRef.current) apiRef.current = new WhisperXApiClient();
  const api = apiRef.current;
  const pollersRef = useRef<Partial<Record<TaskType, JobPollingController | null>>>({});
  const [state, setState] = useState<WorkbenchState>(() => createInitialState());
  const [uploadLimits, setUploadLimits] = useState<UploadLimits | null>(null);
  const [uploadLimitsError, setUploadLimitsError] = useState<string | null>(null);

  const setSlot = (
    taskType: TaskType,
    updater: (slot: WorkbenchTaskSlot) => WorkbenchTaskSlot,
  ) => {
    setState((current) => ({
      ...current,
      slots: {
        ...current.slots,
        [taskType]: updater(current.slots[taskType]),
      },
    }));
  };

  const stopPolling = (taskType: TaskType) => {
    pollersRef.current[taskType]?.stop();
    pollersRef.current[taskType] = null;
  };

  const updateJob = (taskType: TaskType, nextJob: JobStatus) => {
    setSlot(taskType, (slot) => ({
      ...slot,
      job: nextJob,
      fileMeta: withFileMeta(nextJob, slot.fileMeta),
    }));
  };

  const startPolling = (taskType: TaskType, jobId: string) => {
    stopPolling(taskType);
    pollersRef.current[taskType] = startJobStatusPolling({
      api,
      jobId,
      intervalMs: 2000,
      onStatus: (status) => {
        updateJob(taskType, status);
        if (isTerminalStatus(status.status) && status.status !== 'succeeded') {
          pollersRef.current[taskType] = null;
        }
      },
      onSuccessResults: (status) => {
        updateJob(taskType, status);
        pollersRef.current[taskType] = null;
      },
      onError: (nextError) => {
        setSlot(taskType, (slot) => ({ ...slot, error: errorMessage(nextError) }));
      },
    });
  };

  const hydrateJob = async (taskType: TaskType, jobId: string) => {
    try {
      const status = await api.fetchStatus(jobId);
      updateJob(taskType, status);
      if (!isTerminalStatus(status.status)) {
        startPolling(taskType, jobId);
        return;
      }
      if (status.status === 'succeeded') {
        try {
          updateJob(taskType, await api.fetchResults(jobId));
        } catch (nextError) {
          setSlot(taskType, (slot) => ({
            ...slot,
            error: `无法恢复任务结果 ${jobId}：${errorMessage(nextError)}`,
          }));
        }
      }
    } catch (nextError) {
      setSlot(taskType, (slot) => ({
        ...slot,
        error: `无法恢复任务 ${jobId}：${errorMessage(nextError)}`,
      }));
    }
  };

  useEffect(() => {
    writePersistedState(state);
  }, [state]);

  useEffect(() => {
    let active = true;
    void api
      .health()
      .then((response) => {
        if (!active) return;
        if (!response.uploadLimits) {
          throw new Error('后端 /health 未返回上传限制。');
        }
        setUploadLimits(response.uploadLimits);
        setUploadLimitsError(null);
      })
      .catch((nextError) => {
        if (!active) return;
        const message = `无法读取上传限制：${errorMessage(nextError)}`;
        setUploadLimits(null);
        setUploadLimitsError(message);
        setState((current) => ({
          ...current,
          slots: {
            ...current.slots,
            [current.activeTaskType]: {
              ...current.slots[current.activeTaskType],
              error: current.slots[current.activeTaskType].error ?? message,
            },
          },
        }));
      });
    return () => {
      active = false;
    };
  }, [api]);

  useEffect(() => {
    for (const taskType of taskTypes) {
      const jobId = state.slots[taskType].job?.jobId;
      if (jobId) void hydrateJob(taskType, jobId);
    }
    return () => {
      for (const taskType of taskTypes) stopPolling(taskType);
    };
    // Restore persisted jobs exactly once on App/provider mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeSlot = state.slots[state.activeTaskType];
  const currentUploadLimit = uploadLimits?.[state.activeTaskType] ?? null;

  const controller = useMemo<WorkbenchTasksController>(() => {
    const requireUploadLimit = (): UploadLimit | null => {
      if (currentUploadLimit) return currentUploadLimit;
      setSlot(state.activeTaskType, (slot) => ({
        ...slot,
        error: uploadLimitsError ?? '正在读取后端上传限制，请稍后再选择文件。',
      }));
      return null;
    };

    const selectFile = (nextFile: File | null): boolean => {
      const taskType = state.activeTaskType;
      stopPolling(taskType);
      if (!nextFile) {
        setSlot(taskType, (slot) => ({
          ...slot,
          file: null,
          fileMeta: null,
          job: null,
          error: null,
          isSubmitting: false,
        }));
        return true;
      }

      const limit = requireUploadLimit();
      if (!limit) {
        setSlot(taskType, (slot) => ({ ...slot, file: null, fileMeta: null, job: null }));
        return false;
      }
      const sizeError = fileSizeLimitError(nextFile, limit);
      if (sizeError) {
        setSlot(taskType, (slot) => ({
          ...slot,
          file: null,
          fileMeta: null,
          job: null,
          error: sizeError,
          isSubmitting: false,
        }));
        return false;
      }

      setSlot(taskType, (slot) => ({
        ...slot,
        file: nextFile,
        fileMeta: { name: nextFile.name, size: nextFile.size },
        job: null,
        error: null,
        isSubmitting: false,
      }));
      return true;
    };

    const submit = async (): Promise<void> => {
      const taskType = state.activeTaskType;
      const slot = state.slots[taskType];
      const selectedFile = slot.file;
      if (!selectedFile) {
        setSlot(taskType, (currentSlot) => ({
          ...currentSlot,
          error: currentSlot.fileMeta
            ? '请重新选择文件后再上传；浏览器刷新后无法恢复本地文件内容。'
            : currentSlot.error ?? '请先选择一个文件。',
        }));
        return;
      }
      const limit = requireUploadLimit();
      if (!limit) return;
      const sizeError = fileSizeLimitError(selectedFile, limit);
      if (sizeError) {
        stopPolling(taskType);
        setSlot(taskType, (currentSlot) => ({
          ...currentSlot,
          file: null,
          fileMeta: null,
          job: null,
          error: sizeError,
          isSubmitting: false,
        }));
        return;
      }

      stopPolling(taskType);
      setSlot(taskType, (currentSlot) => ({ ...currentSlot, isSubmitting: true, error: null }));
      try {
        const uploaded = await api.uploadAndStart({
          file: fileToUploadable(selectedFile),
          options:
            taskType === taskTypePdf
              ? {
                  taskType: taskTypePdf,
                  markdownCleanupStrength: slot.cleanupStrength,
                }
              : {
                  taskType: taskTypeWhisperx,
                  language: slot.languageMode === 'auto' ? 'auto' : slot.language.trim() || 'auto',
                },
        });
        const initial: JobStatus = {
          jobId: uploaded.jobId,
          status: uploaded.status,
          taskType,
          inputFilename: selectedFile.name,
          inputSizeBytes: selectedFile.size,
          artifacts: [],
        };
        updateJob(taskType, initial);
        startPolling(taskType, uploaded.jobId);
      } catch (nextError) {
        setSlot(taskType, (currentSlot) => ({ ...currentSlot, error: errorMessage(nextError) }));
      } finally {
        setSlot(taskType, (currentSlot) => ({ ...currentSlot, isSubmitting: false }));
      }
    };

    return {
      activeTaskType: state.activeTaskType,
      activeSlot,
      slots: state.slots,
      uploadLimits,
      uploadLimitsError,
      currentUploadLimit,
      requireUploadLimit: () => requireUploadLimit() !== null,
      switchTaskType: (next: TaskType) => {
        if (next === state.activeTaskType) return;
        setState((current) => ({ ...current, activeTaskType: next }));
      },
      selectFile,
      submit,
      clearActiveSlot: () => selectFile(null),
      setLanguageMode: (next: LanguageMode) => {
        setSlot(taskTypeWhisperx, (slot) => ({ ...slot, languageMode: next }));
      },
      setLanguage: (next: string) => {
        setSlot(taskTypeWhisperx, (slot) => ({ ...slot, language: next }));
      },
      setCleanupStrength: (next: PdfCleanupStrength) => {
        setSlot(taskTypePdf, (slot) => ({ ...slot, cleanupStrength: next }));
      },
    };
  }, [activeSlot, currentUploadLimit, state, uploadLimits, uploadLimitsError]);

  return controller;
}
