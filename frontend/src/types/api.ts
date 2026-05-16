export const FALLBACK_API_BASE_URL = 'http://localhost:8000/api';

function normalizeApiBaseUrl(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? '';
  if (!trimmed) return null;
  return trimmed.replace(/\/+$/, '');
}

export const ENV_API_BASE_URL = normalizeApiBaseUrl(import.meta.env.MEDIA_TO_MD_API_BASE_URL);
export const DEFAULT_API_BASE_URL = ENV_API_BASE_URL ?? FALLBACK_API_BASE_URL;
export const API_BASE_URL = DEFAULT_API_BASE_URL;

export const taskTypeWhisperx = 'whisperx' as const;
export const taskTypePdf = 'pdf' as const;

export type TaskType = typeof taskTypeWhisperx | typeof taskTypePdf;
export type WhisperxBackend = 'cli' | 'openai';

export const pdfCleanupStrengthOff = 'off' as const;
export const pdfCleanupStrengthConservative = 'conservative' as const;
export const pdfCleanupStrengthBalanced = 'balanced' as const;
export const pdfCleanupStrengthAggressive = 'aggressive' as const;

export const pdfCleanupStrengths = [
  pdfCleanupStrengthOff,
  pdfCleanupStrengthConservative,
  pdfCleanupStrengthBalanced,
  pdfCleanupStrengthAggressive,
] as const;

export type PdfCleanupStrength = (typeof pdfCleanupStrengths)[number];

export const supportedPdfArtifactFormats = [
  'markdown',
  'markdown_clear',
  'markdown_llm',
  'text',
] as const;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue | undefined };

export type JobStatusValue =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | string;

export interface WhisperxJobOptions {
  taskType: typeof taskTypeWhisperx;
  language: string;
  model?: string | null;
  modelCacheOnly?: boolean | null;
}

export interface PdfJobOptions {
  taskType: typeof taskTypePdf;
  markdownCleanupStrength?: PdfCleanupStrength;
}

export type JobOptions = WhisperxJobOptions | PdfJobOptions;

export interface UploadLimit {
  maxMb: number;
  maxBytes: number;
}

export interface UploadLimits {
  whisperx: UploadLimit;
  pdf: UploadLimit;
}

export interface HealthResponse {
  status: string;
  uploadLimits: UploadLimits | null;
}

export interface BackendConfig {
  model: string;
  cliModel: string;
  openaiModel: string;
  modelDir: string | null;
  whisperxBackend: WhisperxBackend;
  whisperxOpenaiBaseUrl: string | null;
  whisperxOpenaiApiKeyConfigured: boolean;
  whisperxOpenaiTimeoutSeconds: number;
  whisperxOpenaiTranscodeToMp3: boolean;
  whisperxOpenaiMp3Bitrate: string;
  modelCacheOnly: boolean;
  whisperxArgs: string[];
  whisperxArgsConfig: Record<string, unknown>;
  whisperxCliArgs: string[];
  whisperxCliArgsConfig: Record<string, unknown>;
  whisperxOpenaiArgsConfig: Record<string, unknown>;
  pdfArgs: string[];
  pdfArgsConfig: Record<string, unknown>;
  nltkDataDir: string | null;
  whisperxLlmPolishEnabled: boolean;
  pdfLlmPolishEnabled: boolean;
  llmPolishProvider: string;
  llmPolishBaseUrl: string | null;
  llmPolishApiKeyConfigured: boolean;
  llmPolishModel: string | null;
  llmPolishTimeoutSeconds: number;
  llmPolishProviders: LlmProviderInfo[];
  maxWhisperxUploadMb: number;
  maxPdfUploadMb: number;
}

export interface LlmProviderInfo {
  id: string;
  label: string;
  baseUrl: string | null;
}

export interface LlmModelsResponse {
  provider: string;
  baseUrl: string;
  models: string[];
  message: string;
}

export interface LlmConnectionCheckResponse {
  ok: boolean;
  provider: string;
  baseUrl: string | null;
  model: string | null;
  message: string;
  models: string[];
}

export interface JobCreateResponse {
  jobId: string;
  status: JobStatusValue;
}

export interface AdminSession {
  accessToken: string;
  tokenType: string;
  username: string;
  expiresAt: number;
}

export interface AdminAccountInfo {
  username: string;
  updatedAt: string;
}

export interface Artifact {
  name: string;
  format: string;
  sizeBytes: number;
  path?: string | null;
  downloadUrl?: string | null;
}

export interface JobEvent {
  timestamp: string;
  type: 'created' | 'status' | 'log' | 'artifact' | 'error' | 'system' | 'progress' | string;
  message: string;
  status?: JobStatusValue | null;
  data: Record<string, unknown>;
}

export interface RuntimePhase {
  process?: string | null;
  code: string;
  label: string;
  detail: string;
  stagePercent?: number | null;
  source?: string | null;
  updatedAt?: string | null;
}

export interface JobStatus {
  jobId: string;
  status: JobStatusValue;
  taskType: TaskType | string;
  createdAt?: string | null;
  updatedAt?: string | null;
  inputFilename?: string | null;
  inputSizeBytes?: number | null;
  inputDurationSeconds?: number | null;
  options?: Record<string, unknown> | null;
  error?: string | null;
  logPath?: string | null;
  log?: string | null;
  runtimePhase?: RuntimePhase | null;
  artifacts: Artifact[];
  jsonResult?: Record<string, unknown> | null;
}

export function isTerminalStatus(status: JobStatusValue): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled';
}

export function isTextArtifact(artifact: Pick<Artifact, 'format' | 'name'>): boolean {
  const format = artifact.format.toLowerCase();
  const name = artifact.name.toLowerCase();
  return (
    (supportedPdfArtifactFormats as readonly string[]).includes(format) ||
    format === 'txt' ||
    name.endsWith('.txt') ||
    name.endsWith('.md') ||
    name.endsWith('_clear.md')
  );
}

export function taskTypeLabel(taskType: string): string {
  if (taskType === taskTypePdf) return 'PDF 文档解析';
  if (taskType === taskTypeWhisperx) return '音视频转写';
  return taskType;
}

export function jobOptionsToFormFields(options: JobOptions): Record<string, string> {
  if (options.taskType === taskTypePdf) {
    return {
      task_type: taskTypePdf,
      markdown_cleanup_strength:
        options.markdownCleanupStrength ?? pdfCleanupStrengthBalanced,
    };
  }

  const fields: Record<string, string> = {
    task_type: taskTypeWhisperx,
    language: options.language === 'auto' ? 'auto' : options.language,
  };
  const selectedModel = options.model?.trim();
  if (selectedModel) fields.model = selectedModel;
  if (options.modelCacheOnly !== undefined && options.modelCacheOnly !== null) {
    fields.model_cache_only = String(options.modelCacheOnly);
  }
  return fields;
}
