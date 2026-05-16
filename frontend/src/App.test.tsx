import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { App, getHashRoute } from './App';
import { startJobStatusPolling } from './services/jobs';
import type { JobStatus } from './types/api';

const DEFAULT_UPLOAD_LIMIT_BYTES = 512 * 1024 * 1024;
const DEFAULT_HEALTH_RESPONSE = {
  status: 'ok',
  upload_limits: {
    whisperx: { max_mb: 512, max_bytes: DEFAULT_UPLOAD_LIMIT_BYTES },
    pdf: { max_mb: 256, max_bytes: 256 * 1024 * 1024 },
  },
};

function stubHealthFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
    }),
  );
}

describe('hash routing shell', () => {
  afterEach(() => {
    window.location.hash = '';
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('renders the workbench for the default route using the prototype shell', async () => {
    stubHealthFetch();
    window.location.hash = '';
    const { container } = render(<App />);
    expect(screen.getByText('Media-to-MD')).toBeInTheDocument();
    expect(screen.getByText('GitHub: media-to-md · 音视频/PDF → Markdown')).toBeInTheDocument();
    expect(screen.queryByLabelText('API base URL')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本地转换工作台' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /本地转换工作台/ })).toHaveClass('active');
    expect(screen.queryByText(/TranscriptionPage/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '清空当前任务' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('音视频转写当前状态')).toBeInTheDocument();
    expect(container.querySelector('.phase-current > .phase-badge')).not.toBeInTheDocument();
    expect(container.querySelector('.phase-current > .status-pill')).not.toBeInTheDocument();
    expect(screen.getByText('Idle')).toBeInTheDocument();
    expect(screen.getByText('待提交')).toBeInTheDocument();
    expect(screen.getAllByText('进行中').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('语音活动检测')).not.toBeInTheDocument();
    expect(screen.queryByText('准备')).not.toBeInTheDocument();
    expect(screen.queryByText(/轮询/)).not.toBeInTheDocument();
    expect(screen.queryByText('运行日志')).not.toBeInTheDocument();
    expect(screen.queryByText('文档预览')).not.toBeInTheDocument();
    expect(screen.queryByText('结果说明')).not.toBeInTheDocument();
    expect(screen.queryByText(/普通上传页只暴露必要参数/)).not.toBeInTheDocument();
    expect(screen.getByText('从音视频文件中提取字幕与转写文本')).toBeInTheDocument();
    expect(await screen.findByText(/接受常见的音频\/视频文件，单个文件不超过 512\.0 MB/)).toBeInTheDocument();
    expect(screen.queryByText(/audio\/\*|video\/\*/)).not.toBeInTheDocument();
    const languageModeSelect = screen.getByLabelText('语言识别') as HTMLSelectElement;
    expect(languageModeSelect.value).toBe('auto');
    expect(screen.getByLabelText('语言代码')).toBeDisabled();
    expect(screen.getByLabelText('语言代码')).toHaveAttribute('placeholder', '默认 auto；手动可填 en、zh、ja');
    expect(screen.queryByLabelText('说话人分离')).not.toBeInTheDocument();
    expect(screen.queryByText(/说话人分离默认开启/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('LLM 润色')).not.toBeInTheDocument();
    expect(screen.queryByText(/额外生成 LLM 润色版 Markdown/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('输出格式')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/output_formats=/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('最少说话人数')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('最多说话人数')).not.toBeInTheDocument();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['abc'], 'sample.mp3', { type: 'audio/mpeg' });
    fireEvent.change(fileInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    expect(screen.getByText('大小 3 B')).toBeInTheDocument();
    expect(screen.queryByText(/类型 audio\/mpeg/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.getByText('将 PDF 转换为适合大模型处理的 Markdown/TXT')).toBeInTheDocument();
    expect(screen.getByText(/接受常见的 PDF 文档，单个文件不超过 256\.0 MB/)).toBeInTheDocument();
    const pdfFileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdfFile = new File(['pdf'], 'paper.pdf', { type: 'application/pdf' });
    fireEvent.change(pdfFileInput, {
      target: { files: { 0: pdfFile, length: 1, item: () => pdfFile } },
    });
    expect(screen.getAllByText('paper.pdf').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('大小 3 B')).toBeInTheDocument();
    expect(screen.queryByText(/时长 .*大小 3 B/)).not.toBeInTheDocument();
    const cleanupSelect = screen.getByLabelText('Markdown 清洗力度') as HTMLSelectElement;
    expect(cleanupSelect.value).toBe('balanced');
    fireEvent.click(screen.getByRole('button', { name: /音视频转写/ }));
    expect(screen.queryByLabelText('LLM 润色')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.queryByLabelText('LLM 润色')).not.toBeInTheDocument();
    expect([...cleanupSelect.options].map((option) => option.textContent)).toEqual([
      '关闭',
      '保守',
      '均衡',
      '激进',
    ]);
    expect(screen.queryByText('均衡默认')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上传并启动任务' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Artifacts 下载' })).toBeInTheDocument();
    expect(screen.getByText(/artifacts.zip/)).toBeInTheDocument();
  });

  it('rejects files larger than the backend-reported upload limit before submission', async () => {
    stubHealthFetch();
    const { container } = render(<App />);
    expect(await screen.findByText(/接受常见的音频\/视频文件，单个文件不超过 512\.0 MB/)).toBeInTheDocument();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const oversizedFile = new File(['x'], 'too-large.mp4', { type: 'video/mp4' });
    Object.defineProperty(oversizedFile, 'size', {
      configurable: true,
      value: DEFAULT_UPLOAD_LIMIT_BYTES + 1024 * 1024,
    });

    fireEvent.change(fileInput, {
      target: { files: { 0: oversizedFile, length: 1, item: () => oversizedFile } },
    });

    expect(screen.getByText(/文件超过最大上传限制/)).toBeInTheDocument();
    expect(screen.getByText('尚未选择文件')).toBeInTheDocument();
    expect(screen.queryByText('too-large.mp4')).not.toBeInTheDocument();
  });

  it('preserves separate selected files when switching workbench task types', async () => {
    stubHealthFetch();
    const { container } = render(<App />);
    expect(await screen.findByText('接受常见的音频/视频文件，单个文件不超过 512.0 MB。')).toBeInTheDocument();

    const mediaInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['media'], 'meeting.mp3', { type: 'audio/mpeg' });
    fireEvent.change(mediaInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    expect(screen.getAllByText('meeting.mp3').length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.queryByText('meeting.mp3')).not.toBeInTheDocument();
    const pdfInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdfFile = new File(['pdf'], 'contract.pdf', { type: 'application/pdf' });
    fireEvent.change(pdfInput, {
      target: { files: { 0: pdfFile, length: 1, item: () => pdfFile } },
    });
    expect(screen.getAllByText('contract.pdf').length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole('button', { name: /音视频转写/ }));
    expect(screen.getAllByText('meeting.mp3').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('contract.pdf')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.getAllByText('contract.pdf').length).toBeGreaterThanOrEqual(1);
  });

  it('ignores late results from a replaced same-type workbench job', async () => {
    let uploadCount = 0;
    let resolveOldResults: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/upload')) {
          uploadCount += 1;
          return new Response(
            JSON.stringify({ job_id: uploadCount === 1 ? 'job-old' : 'job-new', status: 'queued' }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-old/start') || url.endsWith('/jobs/job-new/start')) {
          expect(init?.method).toBe('POST');
          return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
        }
        if (url.endsWith('/jobs/job-old/status')) {
          return new Response(
            JSON.stringify({
              job_id: 'job-old',
              status: 'succeeded',
              task_type: 'whisperx',
              input_filename: 'old.mp3',
              input_size_bytes: 3,
              options: { task_type: 'whisperx', language: 'auto' },
              artifacts: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-old/results')) {
          return new Promise<Response>((resolve) => {
            resolveOldResults = resolve;
          });
        }
        if (url.endsWith('/jobs/job-new/status')) {
          return new Response(
            JSON.stringify({
              job_id: 'job-new',
              status: 'running',
              task_type: 'whisperx',
              input_filename: 'new.mp3',
              input_size_bytes: 3,
              options: { task_type: 'whisperx', language: 'auto' },
              artifacts: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    const { container } = render(<App />);
    expect(await screen.findByText('接受常见的音频/视频文件，单个文件不超过 512.0 MB。')).toBeInTheDocument();
    const oldInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const oldFile = new File(['old'], 'old.mp3', { type: 'audio/mpeg' });
    fireEvent.change(oldInput, {
      target: { files: { 0: oldFile, length: 1, item: () => oldFile } },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并启动任务' }));
    expect(await screen.findByText('job-old')).toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/jobs/job-old/results'))).toBe(true),
    );

    const newInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const newFile = new File(['new'], 'new.mp3', { type: 'audio/mpeg' });
    fireEvent.change(newInput, {
      target: { files: { 0: newFile, length: 1, item: () => newFile } },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并启动任务' }));
    expect(await screen.findByText('job-new')).toBeInTheDocument();

    resolveOldResults(
      new Response(
        JSON.stringify({
          job_id: 'job-old',
          status: 'succeeded',
          task_type: 'whisperx',
          input_filename: 'old.mp3',
          input_size_bytes: 3,
          artifacts: [{ name: 'old.md', format: 'markdown', size_bytes: 9, path: 'old.md' }],
        }),
        { headers: { 'Content-Type': 'application/json' } },
      ),
    );
    await Promise.resolve();

    expect(screen.getByText('job-new')).toBeInTheDocument();
    expect(screen.queryByText('job-old')).not.toBeInTheDocument();
    expect(screen.queryByText('下载 artifacts.zip')).not.toBeInTheDocument();
  });

  it('preserves a submitted workbench job while visiting task management and keeps polling', async () => {
    let statusCalls = 0;
    const runningJob = {
      job_id: 'job-route',
      status: 'running',
      task_type: 'whisperx',
      input_filename: 'lecture.mp3',
      input_size_bytes: 5,
      options: { task_type: 'whisperx', language: 'auto' },
      runtime_phase: {
        process: 'whisperx',
        code: 'running',
        label: '运行中',
        detail: '后台仍在处理。',
        stage_percent: 50,
        source: 'system',
      },
      artifacts: [],
    };
    const succeededJob = {
      ...runningJob,
      status: 'succeeded',
      runtime_phase: {
        process: 'whisperx',
        code: 'succeeded',
        label: '已完成',
        detail: '任务已成功完成。',
        stage_percent: 100,
        source: 'system',
      },
      artifacts: [{ name: 'lecture.md', format: 'markdown', size_bytes: 12, path: 'lecture.md' }],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/upload')) {
          expect(init?.method).toBe('POST');
          return new Response(JSON.stringify({ job_id: 'job-route', status: 'queued' }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-route/start')) {
          expect(init?.method).toBe('POST');
          return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
        }
        if (url.endsWith('/jobs/job-route/status')) {
          statusCalls += 1;
          return new Response(JSON.stringify(statusCalls === 1 ? runningJob : succeededJob), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-route/results')) {
          return new Response(JSON.stringify(succeededJob), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    const { container } = render(<App />);
    expect(await screen.findByText('接受常见的音频/视频文件，单个文件不超过 512.0 MB。')).toBeInTheDocument();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['media'], 'lecture.mp3', { type: 'audio/mpeg' });
    fireEvent.change(fileInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并启动任务' }));

    expect(await screen.findByText('job-route')).toBeInTheDocument();
    expect(await screen.findByText('Running')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /任务管理页/ }));
    expect(await screen.findByRole('heading', { name: '任务管理页' })).toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 2100));

    fireEvent.click(screen.getByRole('button', { name: /本地转换工作台/ }));
    expect(await screen.findByText('job-route')).toBeInTheDocument();
    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载 artifacts.zip' })).toHaveAttribute(
      'href',
      'http://localhost:8000/api/jobs/job-route/artifacts.zip',
    );
    expect(statusCalls).toBeGreaterThanOrEqual(2);
  }, 7000);

  it('keeps submitted audio/video and PDF jobs in independent workbench slots', async () => {
    const uploads: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/upload')) {
          const body = init?.body instanceof FormData ? init.body : null;
          const taskType = String(body?.get('task_type') ?? 'whisperx');
          uploads.push(taskType);
          return new Response(
            JSON.stringify({ job_id: taskType === 'pdf' ? 'job-pdf' : 'job-media', status: 'queued' }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-media/start') || url.endsWith('/jobs/job-pdf/start')) {
          return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
        }
        if (url.endsWith('/jobs/job-media/status')) {
          return new Response(
            JSON.stringify({
              job_id: 'job-media',
              status: 'running',
              task_type: 'whisperx',
              input_filename: 'standup.mp3',
              input_size_bytes: 5,
              options: { task_type: 'whisperx', language: 'auto' },
              artifacts: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-pdf/status')) {
          return new Response(
            JSON.stringify({
              job_id: 'job-pdf',
              status: 'running',
              task_type: 'pdf',
              input_filename: 'brief.pdf',
              input_size_bytes: 3,
              options: { task_type: 'pdf', markdown_cleanup_strength: 'balanced' },
              artifacts: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    const { container } = render(<App />);
    expect(await screen.findByText('接受常见的音频/视频文件，单个文件不超过 512.0 MB。')).toBeInTheDocument();
    const mediaInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['media'], 'standup.mp3', { type: 'audio/mpeg' });
    fireEvent.change(mediaInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并启动任务' }));
    expect(await screen.findByText('job-media')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    const pdfInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const pdfFile = new File(['pdf'], 'brief.pdf', { type: 'application/pdf' });
    fireEvent.change(pdfInput, {
      target: { files: { 0: pdfFile, length: 1, item: () => pdfFile } },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并启动任务' }));
    expect(await screen.findByText('job-pdf')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /音视频转写/ }));
    expect(await screen.findByText('job-media')).toBeInTheDocument();
    expect(screen.queryByText('job-pdf')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(await screen.findByText('job-pdf')).toBeInTheDocument();
    expect(screen.queryByText('job-media')).not.toBeInTheDocument();
    expect(uploads).toEqual(['whisperx', 'pdf']);
  });

  it('restores a persisted workbench job id after a browser reload', async () => {
    window.localStorage.setItem(
      'media_to_md_workbench_tasks_v1',
      JSON.stringify({
        activeTaskType: 'pdf',
        slots: {
          pdf: {
            jobId: 'job-persisted-pdf',
            fileMeta: { name: 'restored.pdf', size: 3 },
            cleanupStrength: 'aggressive',
          },
        },
      }),
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-persisted-pdf/status')) {
          return new Response(
            JSON.stringify({
              job_id: 'job-persisted-pdf',
              status: 'running',
              task_type: 'pdf',
              input_filename: 'restored.pdf',
              input_size_bytes: 3,
              options: { task_type: 'pdf', markdown_cleanup_strength: 'aggressive' },
              artifacts: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    render(<App />);

    expect(screen.getByRole('button', { name: /PDF 文档解析/ })).toHaveClass('active');
    expect(await screen.findByText('job-persisted-pdf')).toBeInTheDocument();
    expect(screen.getAllByText('restored.pdf').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText('Markdown 清洗力度')).toHaveValue('aggressive');
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('restores a succeeded persisted workbench job with artifact download', async () => {
    window.localStorage.setItem(
      'media_to_md_workbench_tasks_v1',
      JSON.stringify({
        activeTaskType: 'pdf',
        slots: {
          pdf: {
            jobId: 'job-persisted-done',
            fileMeta: { name: 'done.pdf', size: 8 },
            cleanupStrength: 'balanced',
          },
        },
      }),
    );
    const statusJob = {
      job_id: 'job-persisted-done',
      status: 'succeeded',
      task_type: 'pdf',
      input_filename: 'done.pdf',
      input_size_bytes: 8,
      options: { task_type: 'pdf', markdown_cleanup_strength: 'balanced' },
      artifacts: [],
    };
    const resultJob = {
      ...statusJob,
      artifacts: [{ name: 'done.md', format: 'markdown', size_bytes: 24, path: 'done.md' }],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return new Response(JSON.stringify(DEFAULT_HEALTH_RESPONSE), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-persisted-done/status')) {
          return new Response(JSON.stringify(statusJob), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-persisted-done/results')) {
          return new Response(JSON.stringify(resultJob), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    render(<App />);

    expect(await screen.findByText('job-persisted-done')).toBeInTheDocument();
    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载 artifacts.zip' })).toHaveAttribute(
      'href',
      'http://localhost:8000/api/jobs/job-persisted-done/artifacts.zip',
    );
  });

  it('does not emit success results after polling is stopped during result fetch', async () => {
    let resolveResults: (status: JobStatus) => void = () => undefined;
    const api = {
      fetchStatus: vi.fn(async () => ({
        jobId: 'job-stop',
        status: 'succeeded',
        taskType: 'whisperx',
        artifacts: [],
      })),
      fetchResults: vi.fn(
        () =>
          new Promise<JobStatus>((resolve) => {
            resolveResults = resolve;
          }),
      ),
    };
    const onStatus = vi.fn();
    const onSuccessResults = vi.fn();

    const controller = startJobStatusPolling({
      api: api as never,
      jobId: 'job-stop',
      intervalMs: 60_000,
      onStatus,
      onSuccessResults,
    });

    await waitFor(() => expect(api.fetchResults).toHaveBeenCalledTimes(1));
    controller.stop();
    resolveResults({
      jobId: 'job-stop',
      status: 'succeeded',
      taskType: 'whisperx',
      artifacts: [{ name: 'late.md', format: 'markdown', sizeBytes: 4 }],
    });
    await Promise.resolve();

    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onSuccessResults).not.toHaveBeenCalled();
  });

  it('renders admin for /#/admin without browser-history routing', () => {
    window.location.hash = '#/admin';
    const { container } = render(<App />);
    expect(screen.getByRole('heading', { name: '任务管理页' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /任务管理页/ })).toHaveClass('active');
    expect(screen.queryByText(/AdminJobsPage/)).not.toBeInTheDocument();
    expect(container.querySelector('.page-head .status-pill')).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '管理员登录' })).toBeInTheDocument();
    expect(container.querySelector('form.login-panel.login-dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('管理员账号')).toBeInTheDocument();
    expect(screen.getByLabelText('登录/当前密码')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument();
    expect(container.querySelector('.page-head')?.textContent).not.toContain('保存 config');
    const configBox = screen.getByRole('heading', { name: '后端运行配置' }).closest('section');
    expect(screen.queryByRole('heading', { name: '后端 API 配置' })).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('API Base URL')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByText(/前端 API 地址为启动配置/)).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByText(/MEDIA_TO_MD_API_BASE_URL/)).not.toBeInTheDocument();
    const defaultModelInput = within(configBox as HTMLElement).getByLabelText('默认模型');
    expect(defaultModelInput).toHaveValue('small');
    expect(within(configBox as HTMLElement).getByLabelText('音视频最大上传 MB')).toHaveValue(512);
    expect(within(configBox as HTMLElement).getByLabelText('PDF 最大上传 MB')).toHaveValue(512);
    fireEvent.change(defaultModelInput, { target: { value: 'medium' } });
    expect(defaultModelInput).toHaveValue('medium');
    expect(within(configBox as HTMLElement).getByLabelText('Device')).toHaveValue('');
    expect(within(configBox as HTMLElement).getByLabelText('Compute type')).toHaveValue('');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveAttribute('placeholder', '后端默认');
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('Batch size'), {
      target: { value: '6' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('6');
    expect(within(configBox as HTMLElement).getByLabelText('No align')).toHaveValue('');
    expect(within(configBox as HTMLElement).getByLabelText('Min speakers')).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByLabelText('Max speakers')).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByLabelText('Speaker embeddings')).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByLabelText('音视频转写润色服务')).toHaveValue('false');
    expect(within(configBox as HTMLElement).getByLabelText('PDF 润色服务')).toHaveValue('false');
    expect(within(configBox as HTMLElement).getByLabelText('供应商')).toHaveValue('openai');
    expect(within(configBox as HTMLElement).getByLabelText('接口地址')).toHaveAttribute(
      'placeholder',
      'https://api.openai.com/v1',
    );
    expect(within(configBox as HTMLElement).getByLabelText('API Key')).toHaveAttribute(
      'placeholder',
      '请输入供应商 API Key',
    );
    expect(within(configBox as HTMLElement).getByLabelText('模型')).toHaveValue('');
    const fetchModelsButton = within(configBox as HTMLElement).getByRole('button', { name: '拉取模型' });
    const checkConnectionButton = within(configBox as HTMLElement).getByRole('button', { name: '连接检查' });
    expect(fetchModelsButton).toBeInTheDocument();
    expect(checkConnectionButton).toBeInTheDocument();
    expect(
      checkConnectionButton.compareDocumentPosition(fetchModelsButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(configBox as HTMLElement).queryByLabelText('选择已拉取模型')).not.toBeInTheDocument();
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('供应商'), {
      target: { value: 'deepseek' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('接口地址')).toHaveValue(
      'https://api.deepseek.com/v1',
    );
    expect(within(configBox as HTMLElement).getByLabelText('仅使用本地缓存')).toHaveValue('false');
    expect(within(configBox as HTMLElement).queryByLabelText('OpenAI Base URL')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByText(/本机 CLI 模式显示/)).toBeInTheDocument();
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('执行方式'), {
      target: { value: 'openai' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('默认模型')).toHaveValue('large-v2');
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('默认模型'), {
      target: { value: 'large-v3' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('OpenAI Base URL')).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByLabelText('OpenAI API Key')).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByLabelText('OpenAI timeout seconds')).toHaveValue('3600');
    expect(within(configBox as HTMLElement).getByLabelText('转 MP3 后上传')).toHaveValue('true');
    expect(within(configBox as HTMLElement).getByLabelText('MP3 bitrate')).toHaveValue('64k');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveAttribute('placeholder', '远端默认');
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('Batch size'), {
      target: { value: '12' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('12');
    expect(within(configBox as HTMLElement).getByLabelText('No align')).toHaveValue('');
    expect(within(configBox as HTMLElement).queryByLabelText('Device')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('Compute type')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('仅使用本地缓存')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('Min speakers')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('Max speakers')).not.toBeInTheDocument();
    expect(within(configBox as HTMLElement).queryByLabelText('Speaker embeddings')).not.toBeInTheDocument();
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('执行方式'), {
      target: { value: 'cli' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('默认模型')).toHaveValue('medium');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('6');
    fireEvent.change(within(configBox as HTMLElement).getByLabelText('执行方式'), {
      target: { value: 'openai' },
    });
    expect(within(configBox as HTMLElement).getByLabelText('默认模型')).toHaveValue('large-v3');
    expect(within(configBox as HTMLElement).getByLabelText('Batch size')).toHaveValue('12');
    expect(configBox).toContainElement(screen.getByRole('button', { name: '保存 config' }));
    expect(configBox?.textContent).not.toContain('读取 /admin/config · 保存 /admin/config · 展示当前生效参数');
    expect(screen.queryByLabelText('WhisperX args JSON')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('OpenDataLoader PDF args JSON')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '音视频转写任务' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('columnheader', { name: '进度' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'PDF 文档解析任务' }));
    expect(screen.getByRole('tab', { name: 'PDF 文档解析任务' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('columnheader', { name: '清洗力度' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上一页' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeInTheDocument();
  });

  it('shows fetched LLM models on the right and updates the model field from selection', async () => {
    window.localStorage.setItem('whisperx_admin_token', 'token');
    window.localStorage.setItem('whisperx_admin_username', 'admin');
    const configResponse = {
      whisperx_model: 'small',
      whisperx_cli_model: 'small',
      whisperx_openai_model: 'large-v2',
      whisperx_model_dir: null,
      whisperx_backend: 'cli',
      whisperx_openai_base_url: null,
      whisperx_openai_api_key_configured: false,
      whisperx_openai_timeout_seconds: 3600,
      whisperx_openai_transcode_to_mp3: true,
      whisperx_openai_mp3_bitrate: '64k',
      model_cache_only: false,
      nltk_data_dir: null,
      whisperx_args: [],
      whisperx_args_config: {},
      whisperx_cli_args: [],
      whisperx_cli_args_config: {},
      whisperx_openai_args_config: {},
      opendataloader_pdf_args: [],
      opendataloader_pdf_args_config: {},
      max_whisperx_upload_mb: 512,
      max_pdf_upload_mb: 256,
      whisperx_llm_polish_enabled: true,
      pdf_llm_polish_enabled: false,
      llm_polish_provider: 'deepseek',
      llm_polish_base_url: null,
      llm_polish_api_key_configured: false,
      llm_polish_model: null,
      llm_polish_timeout_seconds: 60,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/jobs')) {
          return new Response(JSON.stringify({ jobs: [] }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config')) {
          return new Response(JSON.stringify(configResponse), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/llm/models')) {
          expect(init?.method).toBe('POST');
          return new Response(
            JSON.stringify({
              provider: 'deepseek',
              base_url: 'https://api.deepseek.com/v1',
              models: ['deepseek-chat', 'deepseek-reasoner'],
              message: '已拉取 2 个模型。',
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/admin/llm/check')) {
          expect(JSON.parse(String(init?.body))).toMatchObject({
            provider: 'deepseek',
            model: 'deepseek-reasoner',
          });
          return new Response(
            JSON.stringify({
              ok: true,
              provider: 'deepseek',
              base_url: 'https://api.deepseek.com/v1',
              model: 'deepseek-reasoner',
              message: '连接成功；已使用模型 deepseek-reasoner 完成 chat/completions 测试（10s 超时）。',
              models: [],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    window.location.hash = '#/admin';
    render(<App />);

    const configBox = screen.getByRole('heading', { name: '后端运行配置' }).closest('section');
    const llmModelInput = await within(configBox as HTMLElement).findByLabelText('模型');
    const checkButton = within(configBox as HTMLElement).getByRole('button', { name: '连接检查' });
    const fetchButton = within(configBox as HTMLElement).getByRole('button', { name: '拉取模型' });

    fireEvent.click(fetchButton);

    const fetchedModelSelect = await within(configBox as HTMLElement).findByLabelText('选择已拉取模型');
    expect(llmModelInput).toHaveValue('deepseek-chat');
    fireEvent.change(fetchedModelSelect, { target: { value: 'deepseek-reasoner' } });
    expect(llmModelInput).toHaveValue('deepseek-reasoner');

    fireEvent.click(checkButton);

    const llmInfo = await within(configBox as HTMLElement).findByRole('status');
    expect(llmInfo).toHaveTextContent('连接检查通过');
    expect(llmInfo).toHaveTextContent('chat/completions 测试');
    expect(llmInfo).toHaveTextContent('供应商：deepseek');
    expect(llmInfo).toHaveTextContent('接口：https://api.deepseek.com/v1');
    expect(llmInfo).toHaveTextContent('模型：deepseek-reasoner');
    expect(llmInfo).not.toHaveTextContent('可选模型：');
  });

  it('shows a right-side notice after saving backend config', async () => {
    window.localStorage.setItem('whisperx_admin_token', 'token');
    window.localStorage.setItem('whisperx_admin_username', 'admin');
    const configResponse = {
      whisperx_model: 'small',
      whisperx_cli_model: 'small',
      whisperx_openai_model: 'large-v2',
      whisperx_model_dir: null,
      whisperx_backend: 'cli',
      whisperx_openai_base_url: null,
      whisperx_openai_api_key_configured: false,
      whisperx_openai_timeout_seconds: 3600,
      whisperx_openai_transcode_to_mp3: true,
      whisperx_openai_mp3_bitrate: '64k',
      model_cache_only: false,
      nltk_data_dir: null,
      whisperx_args: [],
      whisperx_args_config: {},
      whisperx_cli_args: [],
      whisperx_cli_args_config: {},
      whisperx_openai_args_config: {},
      opendataloader_pdf_args: [],
      opendataloader_pdf_args_config: {},
      max_whisperx_upload_mb: 512,
      max_pdf_upload_mb: 256,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/jobs')) {
          return new Response(JSON.stringify({ jobs: [] }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config')) {
          if (init?.method === 'PUT') {
            expect(JSON.parse(String(init.body))).toMatchObject({
              whisperx_cli_model: 'small',
              whisperx_openai_model: 'large-v2',
              whisperx_backend: 'cli',
              whisperx_openai_transcode_to_mp3: true,
              whisperx_openai_mp3_bitrate: '64k',
              whisperx_llm_polish_enabled: false,
              pdf_llm_polish_enabled: false,
              llm_polish_provider: 'openai',
              llm_polish_timeout_seconds: 60,
              max_whisperx_upload_mb: 512,
              max_pdf_upload_mb: 256,
            });
          }
          return new Response(JSON.stringify(configResponse), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    window.location.hash = '#/admin';
    render(<App />);

    const configBox = screen.getByRole('heading', { name: '后端运行配置' }).closest('section');
    expect(await within(configBox as HTMLElement).findByLabelText('默认模型')).toHaveValue('small');
    fireEvent.click(within(configBox as HTMLElement).getByRole('button', { name: '保存 config' }));

    expect(await screen.findByRole('status')).toHaveTextContent('配置已保存');
    expect(screen.getByText('配置已保存')).toHaveClass('config-toast-success');
  });

  it('shows a right-side save failure notice without trailing punctuation', async () => {
    window.localStorage.setItem('whisperx_admin_token', 'token');
    window.localStorage.setItem('whisperx_admin_username', 'admin');
    const configResponse = {
      whisperx_model: 'small',
      whisperx_cli_model: 'small',
      whisperx_openai_model: 'large-v2',
      whisperx_model_dir: null,
      whisperx_backend: 'cli',
      whisperx_openai_base_url: null,
      whisperx_openai_api_key_configured: false,
      whisperx_openai_timeout_seconds: 3600,
      whisperx_openai_transcode_to_mp3: true,
      whisperx_openai_mp3_bitrate: '64k',
      model_cache_only: false,
      nltk_data_dir: null,
      whisperx_args: [],
      whisperx_args_config: {},
      whisperx_cli_args: [],
      whisperx_cli_args_config: {},
      whisperx_openai_args_config: {},
      opendataloader_pdf_args: [],
      opendataloader_pdf_args_config: {},
      max_whisperx_upload_mb: 512,
      max_pdf_upload_mb: 256,
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/jobs')) {
          return new Response(JSON.stringify({ jobs: [] }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config') && init?.method === 'PUT') {
          return new Response(JSON.stringify({ detail: 'OpenAI timeout seconds 必须是大于 0 的数字。' }), {
            status: 400,
            statusText: 'Bad Request',
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config')) {
          return new Response(JSON.stringify(configResponse), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    window.location.hash = '#/admin';
    render(<App />);

    const configBox = screen.getByRole('heading', { name: '后端运行配置' }).closest('section');
    expect(await within(configBox as HTMLElement).findByLabelText('默认模型')).toHaveValue('small');
    fireEvent.click(within(configBox as HTMLElement).getByRole('button', { name: '保存 config' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '保存失败 OpenAI timeout seconds 必须是大于 0 的数字',
    );
    expect(screen.queryByText(/Config 保存失败/)).not.toBeInTheDocument();
  });

  it('shows password management instead of login/logout inside signed-in account modal', async () => {
    window.localStorage.setItem('whisperx_admin_token', 'token');
    window.localStorage.setItem('whisperx_admin_username', 'admin');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/jobs')) {
          return new Response(JSON.stringify({ jobs: [] }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config')) {
          return new Response(
            JSON.stringify({
              whisperx_model: 'small',
              whisperx_model_dir: null,
              model_cache_only: false,
              nltk_data_dir: null,
              whisperx_args: [],
              whisperx_args_config: {},
              opendataloader_pdf_args: [],
              opendataloader_pdf_args_config: {},
              max_whisperx_upload_mb: 512,
              max_pdf_upload_mb: 256,
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    window.location.hash = '#/admin';
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '账号管理' }));

    const dialog = screen.getByRole('dialog', { name: '账号管理' });
    expect(within(dialog).queryByRole('button', { name: '登录' })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: '登出' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '修改账号名' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '修改密码' })).toBeInTheDocument();
    expect(within(dialog).getByLabelText('当前密码')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('新密码')).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
  });

  it('closes the task detail drawer with Escape after showing the full inline log', async () => {
    window.localStorage.setItem('whisperx_admin_token', 'token');
    window.localStorage.setItem('whisperx_admin_username', 'admin');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const jobPayload = {
          job_id: 'job-esc',
          status: 'succeeded',
          task_type: 'whisperx',
          input_filename: 'sample.wav',
          input_size_bytes: 3,
          updated_at: '2026-05-10T00:00:00Z',
          options: { task_type: 'whisperx', model: 'small', language: 'auto' },
          runtime_phase: {
            process: 'whisperx',
            code: 'succeeded',
            label: '已完成',
            detail: '任务已成功完成，可下载输出文件。',
            stage_percent: 100,
            source: 'system',
          },
          artifacts: [
            {
              name: 'result.txt',
              format: 'txt',
              size_bytes: 32,
              path: 'output/result.txt',
              download_url: null,
            },
          ],
        };
        if (url.endsWith('/jobs')) {
          return new Response(
            JSON.stringify({
              jobs: [jobPayload],
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-esc/status')) {
          return new Response(JSON.stringify(jobPayload), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/admin/config')) {
          return new Response(
            JSON.stringify({
              whisperx_model: 'small',
              whisperx_model_dir: null,
              whisperx_backend: 'cli',
              whisperx_openai_base_url: null,
              whisperx_openai_api_key_configured: false,
              whisperx_openai_timeout_seconds: 3600,
              whisperx_openai_transcode_to_mp3: true,
              whisperx_openai_mp3_bitrate: '64k',
              model_cache_only: false,
              nltk_data_dir: null,
              whisperx_args: [],
              whisperx_args_config: {},
              opendataloader_pdf_args: [],
              opendataloader_pdf_args_config: {},
              max_whisperx_upload_mb: 512,
              max_pdf_upload_mb: 256,
            }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/jobs/job-esc/events')) {
          return new Response(JSON.stringify({ events: [] }), {
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.endsWith('/jobs/job-esc/logs')) {
          return new Response(
            JSON.stringify({ job_id: 'job-esc', log: 'first log line\nlast log line\n' }),
            { headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
      }),
    );

    window.location.hash = '#/admin';
    render(<App />);

    expect(await screen.findByText('sample.wav')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '详情' }));

    expect(await screen.findByRole('dialog', { name: 'job-esc' })).toBeInTheDocument();
    const zipLink = screen.getByRole('link', { name: '下载 artifacts.zip' });
    expect(zipLink).toHaveAttribute('href', 'http://localhost:8000/api/jobs/job-esc/artifacts.zip');
    expect(screen.queryByText('result.txt')).not.toBeInTheDocument();
    expect(screen.getByText('任务运行日志')).toBeInTheDocument();
    expect(screen.getByText('后端运行日志')).toBeInTheDocument();
    expect(screen.getByText(/first log line/)).toBeInTheDocument();
    expect(screen.getByText(/last log line/)).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'job-esc' })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(/last log line/)).not.toBeInTheDocument();
  });

  it('maps only #/admin to the admin route', () => {
    expect(getHashRoute('#/admin')).toBe('admin');
    expect(getHashRoute('#/other')).toBe('workbench');
    expect(getHashRoute('')).toBe('workbench');
  });
});
