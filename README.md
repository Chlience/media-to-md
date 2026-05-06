# Media-to-MD

Media-to-MD 是一个本地单机服务，把复杂媒体和文档转换成适合大模型继续处理的 Markdown / TXT 等文件。当前版本聚焦两条稳定路径：

- **音视频转写**：上传常见音频/视频文件，调用本机 `whisperx` 提取字幕、转写文本和可选时间轴文件。
- **PDF 文档解析**：上传 PDF，调用本机 `opendataloader-pdf` 输出原始 Markdown/TXT，并额外生成去除图片文字污染的 `*_clear.md`。

项目默认面向个人本地工作站或内网机器，不包含公网 SaaS、多用户隔离、GPU 调度、HTTPS 或 Docker 编排。

## 功能概览

- 拖拽上传音视频或 PDF。
- 任务状态轮询、结果 ZIP 下载和单文件 artifact 下载。
- WhisperX 支持默认模型、本地模型目录、缓存只读模式、语言选择和说话人分离开关。
- PDF 支持 Markdown/TXT 输出、图片输出策略、页码范围、表格/阅读顺序、Hybrid 模式和 Markdown 清洗力度。
- 管理页提供单管理员登录、任务列表/分页/筛选、详情、事件、日志、删除任务和后端运行配置维护。
- 后端保存上传文件、输出文件、事件和日志；公开页面不展示运行日志或文档预览。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI、uv、pytest、直接调用本机 `whisperx` / `opendataloader-pdf` |
| 前端 | React、TypeScript、Vite、Vitest |
| 数据 | 本地文件系统任务目录，不依赖数据库 |

## 目录结构

```text
backend/                  FastAPI 后端、任务存储、CLI runner、配置模板
frontend/                 React/Vite 前端工作台和管理页
docs/                     架构、本地安装、直接 CLI 和模型缓存说明
.env.example              可选环境变量覆盖模板
```

## 快速开始

### 1. 安装并验证外部命令

后端运行时直接调用本机 CLI，不会在任务运行时临时拉取包。建议把 WhisperX 与 OpenDataLoader PDF 安装成独立的 `uv tool`，避免和后端 FastAPI 虚拟环境相互污染。

先安装系统依赖：

```bash
# Ubuntu / Debian 示例
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

再安装 Python CLI：

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
```

如果需要 OpenDataLoader PDF 的 Hybrid/OCR 能力，安装带 extra 的版本：

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
```

启用 `opendataloader_pdf_args.hybrid = "docling-fast"` 前，需要先启动本机 Hybrid 服务：

```bash
opendataloader-pdf-hybrid --port 5002
```

确认 `uv` 的工具目录已在后端进程的 `PATH` 中。必要时执行 `uv tool update-shell` 后重新打开终端。

验证命令：

```bash
whisperx --help
opendataloader-pdf --help
java -version
ffmpeg -version
```

PDF 解析依赖 Java 11+；WhisperX 处理音视频通常需要 `ffmpeg`。若命令缺失，请先修正 `PATH`，再启动后端。

### 2. 配置后端

```bash
cp backend/config.example.json backend/config.json
```

编辑 `backend/config.json`，至少修改管理员密码：

```json
{
  "admin_username": "admin",
  "admin_password": "change-me-before-use"
}
```

完整配置以 `backend/config.example.json` 为准。`.env.example` 只提供少量环境变量覆盖，不是主要配置入口。

### 3. 启动后端

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

默认 API 地址为：`http://localhost:8000/api`。Swagger/OpenAPI 地址：`http://localhost:8000/docs`。

### 4. 启动前端

```bash
cd frontend
npm install
MEDIA_TO_MD_API_BASE_URL=http://localhost:8000/api npm run dev
```

浏览器访问 Vite 输出的地址，普通工作台在 `/#/`，管理页在 `/#/admin`。

## 运行配置

后端配置的单一事实源是 `backend/config.json`。管理页保存配置时也会写回这个文件。

### 常用根配置

| 键 | 含义 |
| --- | --- |
| `data_root` | 任务数据根目录，保存上传、输出、日志和事件。 |
| `api_base_url` | 前端默认 API 地址，也可由 `MEDIA_TO_MD_API_BASE_URL` 覆盖。 |
| `whisperx_model` | WhisperX 默认模型名或后端可访问的本地模型目录。 |
| `whisperx_model_dir` | 模型缓存目录，传给 WhisperX 的 `--model_dir`。 |
| `model_cache_only` | 是否只使用本地缓存模型。 |
| `nltk_data_dir` | NLTK 数据目录，通常放在模型缓存目录下。 |
| `admin_username` / `admin_password` | 本地单管理员账号。 |

### WhisperX 可配置参数

`whisperx_args` 只保留常用且适合本地服务维护的参数：

`batch_size`, `device`, `device_index`, `compute_type`, `threads`, `chunk_size`, `vad_method`, `vad_onset`, `vad_offset`, `align_model`

### OpenDataLoader PDF 可配置参数

`opendataloader_pdf_args` 只保留不会绕开后端任务输出边界的参数：

`format`, `pages`, `threads`, `image_output`, `image_format`, `table_method`, `reading_order`, `hybrid`, `hybrid_mode`, `hybrid_timeout`

后端会拒绝自定义输出目录、标准输出重定向、图片目录、远程 Hybrid URL 等容易破坏任务 artifact 收集边界的参数。

## 任务数据与输出

每个任务位于：

```text
<data_root>/jobs/<job_id>/
  input/               上传文件
  output/              转换产物
  logs/job.log         运行日志
  logs/events.jsonl    任务事件
  manifest.json        任务元数据和可下载 artifact 清单
```

公开下载入口只允许下载 manifest 中列出的 artifact。PDF 任务在生成 Markdown 时会保留原始 Markdown，并输出当前清洗产物 `<origin>_clear.md`，其 artifact format 为 `markdown_clear`。

## 验证

```bash
cd backend
uv run pytest
uv run --with ruff ruff check .
```

```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

更多细节见：

- [本地安装与烟测](docs/local-setup.md)
- [架构说明](docs/architecture.md)
- [直接 CLI runner 契约](docs/direct-cli-runners.md)
- [WhisperX 模型缓存与说话人分离](docs/whisperx-cache-and-diarization.md)
