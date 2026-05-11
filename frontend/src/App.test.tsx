import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { App, getHashRoute } from './App';
import { MAX_UPLOAD_SIZE_BYTES } from './config/upload';

describe('hash routing shell', () => {
  afterEach(() => {
    window.location.hash = '';
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('renders the workbench for the default route using the prototype shell', () => {
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
    expect(screen.getByText(/接受常见的音频\/视频文件，单个文件不超过/)).toBeInTheDocument();
    expect(screen.queryByText(/audio\/\*|video\/\*/)).not.toBeInTheDocument();
    const languageModeSelect = screen.getByLabelText('语言识别') as HTMLSelectElement;
    expect(languageModeSelect.value).toBe('auto');
    expect(screen.getByLabelText('语言代码')).toBeDisabled();
    expect(screen.getByLabelText('语言代码')).toHaveAttribute('placeholder', '默认 auto；手动可填 en、zh、ja');
    const diarizeSelect = screen.getByLabelText('说话人分离') as HTMLSelectElement;
    expect(diarizeSelect.value).toBe('true');
    expect(screen.queryByLabelText('输出格式')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/output_formats=/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('最少说话人数')).not.toBeDisabled();
    expect(screen.getByLabelText('最多说话人数')).not.toBeDisabled();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['abc'], 'sample.mp3', { type: 'audio/mpeg' });
    fireEvent.change(fileInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    expect(screen.getByText('大小 3 B')).toBeInTheDocument();
    expect(screen.queryByText(/类型 audio\/mpeg/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.getByText('将 PDF 转换为适合大模型处理的 Markdown/TXT')).toBeInTheDocument();
    expect(screen.getByText(/接受常见的 PDF 文档，单个文件不超过/)).toBeInTheDocument();
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

  it('rejects files larger than the frontend upload limit before submission', () => {
    const { container } = render(<App />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const oversizedFile = new File(['x'], 'too-large.mp4', { type: 'video/mp4' });
    Object.defineProperty(oversizedFile, 'size', {
      configurable: true,
      value: MAX_UPLOAD_SIZE_BYTES + 1024 * 1024,
    });

    fireEvent.change(fileInput, {
      target: { files: { 0: oversizedFile, length: 1, item: () => oversizedFile } },
    });

    expect(screen.getByText(/文件超过最大上传限制/)).toBeInTheDocument();
    expect(screen.getByText('尚未选择文件')).toBeInTheDocument();
    expect(screen.queryByText('too-large.mp4')).not.toBeInTheDocument();
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
    expect(within(configBox as HTMLElement).getByText(/前端 API 地址为启动配置/)).toBeInTheDocument();
    expect(within(configBox as HTMLElement).getByText('http://localhost:8000/api')).toBeInTheDocument();
    const defaultModelInput = within(configBox as HTMLElement).getByLabelText('默认模型');
    expect(defaultModelInput).toHaveValue('small');
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
    expect(within(configBox as HTMLElement).getByText(/OpenAI 模式只显示接口配置/)).toBeInTheDocument();
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
      model_cache_only: false,
      nltk_data_dir: null,
      whisperx_args: [],
      whisperx_args_config: {},
      whisperx_cli_args: [],
      whisperx_cli_args_config: {},
      whisperx_openai_args_config: {},
      opendataloader_pdf_args: [],
      opendataloader_pdf_args_config: {},
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
      model_cache_only: false,
      nltk_data_dir: null,
      whisperx_args: [],
      whisperx_args_config: {},
      whisperx_cli_args: [],
      whisperx_cli_args_config: {},
      whisperx_openai_args_config: {},
      opendataloader_pdf_args: [],
      opendataloader_pdf_args_config: {},
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
              model_cache_only: false,
              nltk_data_dir: null,
              whisperx_args: [],
              whisperx_args_config: {},
              opendataloader_pdf_args: [],
              opendataloader_pdf_args_config: {},
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
