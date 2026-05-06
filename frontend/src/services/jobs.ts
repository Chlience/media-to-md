import { WhisperXApiClient } from '../api/client';
import { isTerminalStatus, JobStatus } from '../types/api';

export type JobStatusHandler = (status: JobStatus) => void;
export type JobErrorHandler = (error: unknown) => void;

export interface JobPollingController {
  stop(): void;
}

export function startJobStatusPolling(params: {
  api: WhisperXApiClient;
  jobId: string;
  intervalMs?: number;
  onStatus: JobStatusHandler;
  onSuccessResults?: JobStatusHandler;
  onError?: JobErrorHandler;
}): JobPollingController {
  const intervalMs = params.intervalMs ?? 2000;
  let stopped = false;
  let timer: ReturnType<typeof setInterval> | null = null;

  const stop = () => {
    stopped = true;
    if (timer !== null) clearInterval(timer);
    timer = null;
  };

  const refresh = async () => {
    try {
      const status = await params.api.fetchStatus(params.jobId);
      if (stopped) return;
      params.onStatus(status);
      if (!isTerminalStatus(status.status)) return;
      stop();
      if (status.status === 'succeeded' && params.onSuccessResults) {
        params.onSuccessResults(await params.api.fetchResults(params.jobId));
      }
    } catch (error) {
      if (!stopped) params.onError?.(error);
    }
  };

  timer = setInterval(refresh, intervalMs);
  void refresh();

  return { stop };
}

export function downloadTextFile(params: {
  filename: string;
  text: string;
  mimeType?: string;
}): void {
  const blob = new Blob([params.text], {
    type: params.mimeType ?? 'text/plain;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = params.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
