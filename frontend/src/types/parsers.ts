import {
  AdminAccountInfo,
  AdminSession,
  Artifact,
  BackendConfig,
  JobCreateResponse,
  JobEvent,
  JobStatus,
  JsonObject,
  RuntimePhase,
} from './api';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asObject(value: unknown, context = 'response'): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${context} must be an object`);
  return value;
}

function asString(value: unknown, defaultValue = ''): string {
  return typeof value === 'string' ? value : defaultValue;
}

function asNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

function asBoolean(value: unknown, defaultValue = false): boolean {
  return typeof value === 'boolean' ? value : defaultValue;
}

function asWhisperxBackend(value: unknown): 'cli' | 'openai' {
  return value === 'openai' ? 'openai' : 'cli';
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function asUnknownRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? { ...value } : {};
}

export function parseBackendConfig(json: unknown): BackendConfig {
  const object = asObject(json, 'BackendConfig');
  const rawWhisperxArgs = object.whisperx_args;
  const rawWhisperxCliArgs = object.whisperx_cli_args;
  const rawPdfArgs = object.opendataloader_pdf_args;
  const rawWhisperxArgsConfig = object.whisperx_args_config;
  const rawWhisperxCliArgsConfig = object.whisperx_cli_args_config;
  const rawWhisperxOpenaiArgsConfig = object.whisperx_openai_args_config;
  const rawPdfArgsConfig = object.opendataloader_pdf_args_config;
  const whisperxArgsConfig = asUnknownRecord(rawWhisperxArgsConfig);

  return {
    model: asString(object.whisperx_model ?? object.model, 'small'),
    cliModel: asString(object.whisperx_cli_model ?? object.whisperx_model ?? object.model, 'small'),
    openaiModel: asString(
      object.whisperx_openai_model ?? object.whisperx_model ?? object.model,
      'large-v2',
    ),
    modelDir: asNullableString(object.whisperx_model_dir ?? object.model_dir),
    whisperxBackend: asWhisperxBackend(object.whisperx_backend),
    whisperxOpenaiBaseUrl: asNullableString(object.whisperx_openai_base_url),
    whisperxOpenaiApiKeyConfigured: asBoolean(object.whisperx_openai_api_key_configured, false),
    whisperxOpenaiTimeoutSeconds: asNumber(object.whisperx_openai_timeout_seconds) ?? 3600,
    modelCacheOnly: asBoolean(object.model_cache_only, false),
    whisperxArgs: asStringArray(rawWhisperxArgs),
    whisperxArgsConfig,
    whisperxCliArgs: asStringArray(rawWhisperxCliArgs),
    whisperxCliArgsConfig: isRecord(rawWhisperxCliArgsConfig)
      ? { ...rawWhisperxCliArgsConfig }
      : whisperxArgsConfig,
    whisperxOpenaiArgsConfig: isRecord(rawWhisperxOpenaiArgsConfig)
      ? { ...rawWhisperxOpenaiArgsConfig }
      : whisperxArgsConfig,
    pdfArgs: asStringArray(rawPdfArgs),
    pdfArgsConfig: asUnknownRecord(rawPdfArgsConfig),
    nltkDataDir: asNullableString(object.nltk_data_dir),
  };
}

export function parseJobCreateResponse(json: unknown): JobCreateResponse {
  const object = asObject(json, 'JobCreateResponse');
  return {
    jobId: asString(object.job_id),
    status: asString(object.status, 'queued'),
  };
}

export function parseAdminSession(json: unknown): AdminSession {
  const object = asObject(json, 'AdminSession');
  return {
    accessToken: asString(object.access_token),
    tokenType: asString(object.token_type, 'bearer'),
    username: asString(object.username),
    expiresAt: Math.trunc(asNumber(object.expires_at) ?? 0),
  };
}

export function parseAdminAccountInfo(json: unknown): AdminAccountInfo {
  const object = asObject(json, 'AdminAccountInfo');
  return {
    username: asString(object.username),
    updatedAt: asString(object.updated_at),
  };
}

export function parseArtifact(json: unknown): Artifact {
  const object = asObject(json, 'Artifact');
  return {
    name: asString(object.name),
    format: asString(object.format),
    path: asNullableString(object.path),
    sizeBytes: Math.trunc(asNumber(object.size_bytes) ?? 0),
    downloadUrl: asNullableString(object.download_url),
  };
}

export function parseJobEvent(json: unknown): JobEvent {
  const object = asObject(json, 'JobEvent');
  return {
    timestamp: asString(object.timestamp),
    type: asString(object.type),
    message: asString(object.message),
    status: asNullableString(object.status),
    data: asUnknownRecord(object.data),
  };
}

export function parseRuntimePhase(json: unknown): RuntimePhase | null {
  if (!isRecord(json)) return null;
  return {
    process: asNullableString(json.process),
    code: asString(json.code),
    label: asString(json.label),
    detail: asString(json.detail),
    stagePercent: asNumber(json.stage_percent),
    source: asNullableString(json.source),
    updatedAt: asNullableString(json.updated_at),
  };
}

export function parseJobStatus(json: unknown): JobStatus {
  const object = asObject(json, 'JobStatus');
  const options = isRecord(object.options) ? { ...object.options } : null;
  const artifacts = Array.isArray(object.artifacts)
    ? object.artifacts.map(parseArtifact)
    : [];
  const rawJsonResult = object.json_result;
  const taskType = object.task_type ?? options?.task_type;

  return {
    jobId: asString(object.job_id),
    status: asString(object.status),
    taskType: String(taskType),
    createdAt: asNullableString(object.created_at),
    updatedAt: asNullableString(object.updated_at),
    inputFilename: asNullableString(object.input_filename),
    inputSizeBytes: asNumber(object.input_size_bytes),
    inputDurationSeconds: asNumber(object.input_duration_seconds),
    options,
    error: asNullableString(object.error),
    logPath: asNullableString(object.log_path),
    log: asNullableString(object.log),
    runtimePhase: parseRuntimePhase(object.runtime_phase),
    artifacts,
    jsonResult: isRecord(rawJsonResult) ? (rawJsonResult as JsonObject) : null,
  };
}
