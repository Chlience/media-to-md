import {
  AdminAccountInfo,
  AdminSession,
  Artifact,
  API_BASE_URL,
  BackendConfig,
  HealthResponse,
  JobCreateResponse,
  JobEvent,
  JobOptions,
  JobStatus,
  JsonObject,
  LlmConnectionCheckResponse,
  LlmModelsResponse,
  jobOptionsToFormFields,
} from '../types/api';
import {
  asObject,
  parseAdminAccountInfo,
  parseAdminSession,
  parseBackendConfig,
  parseHealthResponse,
  parseJobCreateResponse,
  parseJobEvent,
  parseJobStatus,
  parseLlmConnectionCheckResponse,
  parseLlmModelsResponse,
} from '../types/parsers';

export interface UploadableFile extends Blob {
  name: string;
}

export class ApiException extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly responseText?: string,
  ) {
    super(message);
    this.name = 'ApiException';
  }

  static async fromResponse(response: Response): Promise<ApiException> {
    const body = await response.text().catch(() => '');
    const detail = parseErrorDetail(body);
    return new ApiException(
      `${detail || response.statusText || 'Request failed'}（${response.status}）`,
      response.status,
      body,
    );
  }

  static network(url: string): ApiException {
    return new ApiException(`无法连接后端：${url}`);
  }
}

function parseErrorDetail(body: string): string | null {
  if (!body) return null;
  try {
    const object = asObject(JSON.parse(body), 'error response');
    const detail = object.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item) => JSON.stringify(item)).join('; ');
  } catch {
    // Fall through to raw body.
  }
  return body;
}

function blankToNull(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? '';
  return trimmed === '' ? null : trimmed;
}

export class WhisperXApiClient {
  get baseUrl(): string {
    return API_BASE_URL;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  async health(): Promise<HealthResponse> {
    const response = await this.request('/health');
    return parseHealthResponse(await response.json());
  }

  async fetchConfig(adminToken: string): Promise<BackendConfig> {
    const response = await this.request('/admin/config', {
      bearerToken: adminToken,
    });
    return parseBackendConfig(await response.json());
  }

  async updateConfig(params: {
    adminToken: string;
    cliModel: string;
    openaiModel: string;
    modelDir?: string | null;
    whisperxBackend?: 'cli' | 'openai';
    whisperxOpenaiBaseUrl?: string | null;
    whisperxOpenaiApiKey?: string | null;
    whisperxOpenaiClearApiKey?: boolean;
    whisperxOpenaiTimeoutSeconds?: number;
    whisperxOpenaiTranscodeToMp3: boolean;
    whisperxOpenaiMp3Bitrate: string;
    modelCacheOnly: boolean;
    nltkDataDir?: string | null;
    maxWhisperxUploadMb: number;
    maxPdfUploadMb: number;
    whisperxCliArgs: Record<string, unknown>;
    whisperxOpenaiArgs: Record<string, unknown>;
    pdfArgs?: Record<string, unknown>;
    whisperxLlmPolishEnabled?: boolean;
    pdfLlmPolishEnabled?: boolean;
    llmPolishProvider?: string;
    llmPolishBaseUrl?: string | null;
    llmPolishApiKey?: string | null;
    llmPolishClearApiKey?: boolean;
    llmPolishModel?: string | null;
    llmPolishTimeoutSeconds?: number;
  }): Promise<BackendConfig> {
    const whisperxBackend = params.whisperxBackend ?? 'cli';
    const activeWhisperxArgs =
      whisperxBackend === 'openai' ? params.whisperxOpenaiArgs : params.whisperxCliArgs;
    const response = await this.request('/admin/config', {
      method: 'PUT',
      bearerToken: params.adminToken,
      jsonBody: {
        whisperx_cli_model: params.cliModel.trim(),
        whisperx_openai_model: params.openaiModel.trim(),
        whisperx_model_dir: blankToNull(params.modelDir),
        whisperx_backend: params.whisperxBackend ?? 'cli',
        whisperx_openai_base_url: blankToNull(params.whisperxOpenaiBaseUrl),
        whisperx_openai_api_key: blankToNull(params.whisperxOpenaiApiKey),
        whisperx_openai_clear_api_key: params.whisperxOpenaiClearApiKey ?? false,
        whisperx_openai_timeout_seconds: params.whisperxOpenaiTimeoutSeconds ?? 3600,
        whisperx_openai_transcode_to_mp3: params.whisperxOpenaiTranscodeToMp3,
        whisperx_openai_mp3_bitrate: params.whisperxOpenaiMp3Bitrate.trim(),
        model_cache_only: params.modelCacheOnly,
        nltk_data_dir: blankToNull(params.nltkDataDir),
        whisperx_args: activeWhisperxArgs,
        whisperx_cli_args: params.whisperxCliArgs,
        whisperx_openai_args: params.whisperxOpenaiArgs,
        opendataloader_pdf_args: params.pdfArgs ?? {},
        max_whisperx_upload_mb: params.maxWhisperxUploadMb,
        max_pdf_upload_mb: params.maxPdfUploadMb,
        whisperx_llm_polish_enabled: params.whisperxLlmPolishEnabled ?? false,
        pdf_llm_polish_enabled: params.pdfLlmPolishEnabled ?? false,
        llm_polish_provider: params.llmPolishProvider ?? 'openai',
        llm_polish_base_url: blankToNull(params.llmPolishBaseUrl),
        llm_polish_api_key: blankToNull(params.llmPolishApiKey),
        llm_polish_clear_api_key: params.llmPolishClearApiKey ?? false,
        llm_polish_model: blankToNull(params.llmPolishModel),
        llm_polish_timeout_seconds: params.llmPolishTimeoutSeconds ?? 60,
      },
    });
    return parseBackendConfig(await response.json());
  }

  async fetchLlmModels(params: {
    adminToken: string;
    provider?: string | null;
    baseUrl?: string | null;
    apiKey?: string | null;
    model?: string | null;
    timeoutSeconds?: number;
  }): Promise<LlmModelsResponse> {
    const response = await this.request('/admin/llm/models', {
      method: 'POST',
      bearerToken: params.adminToken,
      jsonBody: {
        provider: blankToNull(params.provider),
        base_url: blankToNull(params.baseUrl),
        api_key: blankToNull(params.apiKey),
        model: blankToNull(params.model),
        timeout_seconds: params.timeoutSeconds ?? null,
      },
    });
    return parseLlmModelsResponse(await response.json());
  }

  async fetchWhisperxOpenaiModels(params: {
    adminToken: string;
    baseUrl?: string | null;
    apiKey?: string | null;
    timeoutSeconds?: number;
  }): Promise<LlmModelsResponse> {
    const response = await this.request('/admin/whisperx-openai/models', {
      method: 'POST',
      bearerToken: params.adminToken,
      jsonBody: {
        base_url: blankToNull(params.baseUrl),
        api_key: blankToNull(params.apiKey),
        timeout_seconds: params.timeoutSeconds ?? null,
      },
    });
    return parseLlmModelsResponse(await response.json());
  }

  async checkLlmConnection(params: {
    adminToken: string;
    provider?: string | null;
    baseUrl?: string | null;
    apiKey?: string | null;
    model?: string | null;
    timeoutSeconds?: number;
  }): Promise<LlmConnectionCheckResponse> {
    const response = await this.request('/admin/llm/check', {
      method: 'POST',
      bearerToken: params.adminToken,
      jsonBody: {
        provider: blankToNull(params.provider),
        base_url: blankToNull(params.baseUrl),
        api_key: blankToNull(params.apiKey),
        model: blankToNull(params.model),
        timeout_seconds: params.timeoutSeconds ?? null,
      },
    });
    return parseLlmConnectionCheckResponse(await response.json());
  }

  async loginAdmin(params: {
    username: string;
    password: string;
  }): Promise<AdminSession> {
    const response = await this.request('/admin/login', {
      method: 'POST',
      jsonBody: {
        username: params.username,
        password: params.password,
      },
    });
    return parseAdminSession(await response.json());
  }

  async fetchAdminAccount(adminToken: string): Promise<AdminAccountInfo> {
    const response = await this.request('/admin/account', {
      bearerToken: adminToken,
    });
    return parseAdminAccountInfo(await response.json());
  }

  async updateAdminAccount(params: {
    adminToken: string;
    currentPassword: string;
    username?: string | null;
    newPassword?: string | null;
  }): Promise<AdminSession> {
    const jsonBody: JsonObject = {
      current_password: params.currentPassword,
    };
    if (params.username?.trim()) jsonBody.username = params.username.trim();
    if (params.newPassword) jsonBody.new_password = params.newPassword;

    const response = await this.request('/admin/account', {
      method: 'PUT',
      bearerToken: params.adminToken,
      jsonBody,
    });
    return parseAdminSession(await response.json());
  }

  async uploadJob(params: {
    file: UploadableFile;
    options: JobOptions;
  }): Promise<JobCreateResponse> {
    const formData = new FormData();
    formData.append('file', params.file, params.file.name);
    for (const [key, value] of Object.entries(jobOptionsToFormFields(params.options))) {
      formData.append(key, value);
    }

    const response = await this.request('/jobs/upload', {
      method: 'POST',
      body: formData,
      headers: {
        'X-Media-To-MD-Task-Type': params.options.taskType,
        'X-Media-To-MD-File-Size': String(params.file.size),
      },
    });
    return parseJobCreateResponse(await response.json());
  }

  async uploadAndStart(params: {
    file: UploadableFile;
    options: JobOptions;
  }): Promise<JobCreateResponse> {
    const uploaded = await this.uploadJob(params);
    await this.startJob(uploaded.jobId);
    return uploaded;
  }

  async startJob(jobId: string): Promise<void> {
    await this.request(`/jobs/${encodeURIComponent(jobId)}/start`, {
      method: 'POST',
    });
  }

  async fetchStatus(jobId: string): Promise<JobStatus> {
    const response = await this.request(`/jobs/${encodeURIComponent(jobId)}/status`);
    return parseJobStatus(await response.json());
  }

  async fetchResults(jobId: string): Promise<JobStatus> {
    const response = await this.request(`/jobs/${encodeURIComponent(jobId)}/results`);
    return parseJobStatus(await response.json());
  }

  async fetchJobs(params: {
    adminToken: string;
    includeLog?: boolean;
  }): Promise<JobStatus[]> {
    const query = params.includeLog ? '?include_log=true' : '';
    const response = await this.request(`/jobs${query}`, {
      bearerToken: params.adminToken,
    });
    const object = asObject(await response.json(), 'JobListResponse');
    const jobs = object.jobs;
    return Array.isArray(jobs) ? jobs.map(parseJobStatus) : [];
  }

  async fetchJobEvents(params: {
    adminToken: string;
    jobId: string;
  }): Promise<JobEvent[]> {
    const response = await this.request(
      `/jobs/${encodeURIComponent(params.jobId)}/events`,
      { bearerToken: params.adminToken },
    );
    const object = asObject(await response.json(), 'JobEventsResponse');
    const events = object.events;
    return Array.isArray(events) ? events.map(parseJobEvent) : [];
  }

  async fetchJobLog(params: {
    adminToken: string;
    jobId: string;
  }): Promise<string> {
    const response = await this.request(
      `/jobs/${encodeURIComponent(params.jobId)}/logs`,
      {
        bearerToken: params.adminToken,
        accept: 'application/json',
      },
    );
    const object = asObject(await response.json(), 'JobLogResponse');
    return typeof object.log === 'string' ? object.log : '';
  }

  async fetchRawJobLog(params: {
    adminToken: string;
    jobId: string;
  }): Promise<string> {
    const response = await this.request(
      `/jobs/${encodeURIComponent(params.jobId)}/logs/download`,
      {
        bearerToken: params.adminToken,
        accept: 'text/plain',
      },
    );
    return response.text();
  }

  async deleteJob(params: { adminToken: string; jobId: string }): Promise<void> {
    await this.request(`/jobs/${encodeURIComponent(params.jobId)}`, {
      method: 'DELETE',
      bearerToken: params.adminToken,
    });
  }

  downloadUrl(jobId: string, artifact: Pick<Artifact, 'name'>): string {
    return this.url(
      `/jobs/${encodeURIComponent(jobId)}/download/${encodeURIComponent(artifact.name)}`,
    );
  }

  artifactsZipUrl(jobId: string): string {
    return this.url(`/jobs/${encodeURIComponent(jobId)}/artifacts.zip`);
  }

  async fetchJsonArtifact(
    jobId: string,
    artifact: Pick<Artifact, 'name' | 'format'>,
  ): Promise<Record<string, unknown> | null> {
    if (artifact.format !== 'json') return null;
    const response = await this.requestAbsolute(this.downloadUrl(jobId, artifact));
    return asObject(await response.json(), 'JsonArtifact');
  }

  private async request(
    path: string,
    options: {
      method?: string;
      jsonBody?: unknown;
      body?: BodyInit;
      bearerToken?: string;
      accept?: string;
      headers?: Record<string, string>;
    } = {},
  ): Promise<Response> {
    return this.requestAbsolute(this.url(path), options);
  }

  private async requestAbsolute(
    url: string,
    options: {
      method?: string;
      jsonBody?: unknown;
      body?: BodyInit;
      bearerToken?: string;
      accept?: string;
      headers?: Record<string, string>;
    } = {},
  ): Promise<Response> {
    const headers = new Headers();
    for (const [key, value] of Object.entries(options.headers ?? {})) {
      headers.set(key, value);
    }
    if (options.accept) headers.set('Accept', options.accept);
    if (options.bearerToken) {
      headers.set('Authorization', `Bearer ${options.bearerToken}`);
    }

    let body = options.body;
    if (options.jsonBody !== undefined) {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(options.jsonBody);
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method: options.method ?? 'GET',
        headers,
        body,
      });
    } catch {
      throw ApiException.network(url);
    }

    if (!response.ok) throw await ApiException.fromResponse(response);
    return response;
  }
}
