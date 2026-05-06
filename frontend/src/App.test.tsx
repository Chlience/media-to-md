import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { App, getHashRoute } from './App';

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
    expect(screen.getByText('语音活动检测')).toBeInTheDocument();
    expect(screen.queryByText('准备')).not.toBeInTheDocument();
    expect(screen.queryByText(/轮询/)).not.toBeInTheDocument();
    expect(screen.queryByText('运行日志')).not.toBeInTheDocument();
    expect(screen.queryByText('文档预览')).not.toBeInTheDocument();
    expect(screen.queryByText('结果说明')).not.toBeInTheDocument();
    expect(screen.queryByText(/普通上传页只暴露必要参数/)).not.toBeInTheDocument();
    expect(screen.getByText('从音视频文件中提取字幕与转写文本')).toBeInTheDocument();
    expect(screen.getByText('接受常见的音频/视频文件。')).toBeInTheDocument();
    expect(screen.queryByText(/audio\/\*|video\/\*/)).not.toBeInTheDocument();
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const mediaFile = new File(['abc'], 'sample.mp3', { type: 'audio/mpeg' });
    fireEvent.change(fileInput, {
      target: { files: { 0: mediaFile, length: 1, item: () => mediaFile } },
    });
    expect(screen.getByText('大小 3 B')).toBeInTheDocument();
    expect(screen.queryByText(/类型 audio\/mpeg/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /PDF 文档解析/ }));
    expect(screen.getByText('将 PDF 转换为适合大模型处理的 Markdown/TXT')).toBeInTheDocument();
    expect(screen.getByText('接受常见的 PDF 文档。')).toBeInTheDocument();
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
    expect(configBox).toContainElement(screen.getByLabelText('API Base URL'));
    expect(within(configBox as HTMLElement).getByLabelText('API Base URL')).toHaveValue('http://localhost:8000/api');
    expect(configBox).toContainElement(screen.getByRole('button', { name: '保存 config' }));
    expect(configBox?.textContent).not.toContain('读取 /admin/config · 保存 /admin/config · 展示当前生效参数');
    expect(screen.queryByLabelText('WhisperX args JSON')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('OpenDataLoader PDF args JSON')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '音视频转写任务' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: 'PDF 文档解析任务' }));
    expect(screen.getByRole('tab', { name: 'PDF 文档解析任务' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('columnheader', { name: '清洗力度' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上一页' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeInTheDocument();
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
              api_base_url: 'http://localhost:8000/api',
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

  it('maps only #/admin to the admin route', () => {
    expect(getHashRoute('#/admin')).toBe('admin');
    expect(getHashRoute('#/other')).toBe('workbench');
    expect(getHashRoute('')).toBe('workbench');
  });
});
