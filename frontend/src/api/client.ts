import {
  AdminAccountInfo,
  AdminSession,
  Artifact,
  BackendConfig,
  JobCreateResponse,
  JobEvent,
  JobOptions,
  JobStatus,
  JsonObject,
  jobOptionsToFormFields,
} from '../types/api';
import { readApiBaseUrl } from '../services/apiBaseUrl';
import {
  asObject,
  parseAdminAccountInfo,
  parseAdminSession,
  parseBackendConfig,
  parseJobCreateResponse,
  parseJobEvent,
  parseJobStatus,
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
  constructor(private configuredBaseUrl?: string) {}

  get baseUrl(): string {
    return this.configuredBaseUrl ?? readApiBaseUrl();
  }

  setBaseUrl(baseUrl: string | null | undefined): void {
    this.configuredBaseUrl = baseUrl?.trim() || undefined;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  async health(): Promise<{ status: string }> {
    const response = await this.request('/health');
    const object = asObject(await response.json(), 'HealthResponse');
    return { status: String(object.status ?? '') };
  }

  async fetchConfig(adminToken: string): Promise<BackendConfig> {
    const response = await this.request('/admin/config', {
      bearerToken: adminToken,
    });
    return parseBackendConfig(await response.json());
  }

  async updateConfig(params: {
    adminToken: string;
    model: string;
    modelDir?: string | null;
    modelCacheOnly: boolean;
    nltkDataDir?: string | null;
    apiBaseUrl?: string | null;
    whisperxArgs: Record<string, unknown>;
    pdfArgs?: Record<string, unknown>;
  }): Promise<BackendConfig> {
    const response = await this.request('/admin/config', {
      method: 'PUT',
      bearerToken: params.adminToken,
      jsonBody: {
        api_base_url: blankToNull(params.apiBaseUrl),
        whisperx_model: params.model.trim(),
        whisperx_model_dir: blankToNull(params.modelDir),
        model_cache_only: params.modelCacheOnly,
        nltk_data_dir: blankToNull(params.nltkDataDir),
        whisperx_args: params.whisperxArgs,
        opendataloader_pdf_args: params.pdfArgs ?? {},
      },
    });
    return parseBackendConfig(await response.json());
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
    } = {},
  ): Promise<Response> {
    const headers = new Headers();
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
