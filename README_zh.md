<h1 align="center">Media-to-MD</h1>

<p align="center">
  <strong>本地部署的音视频 / PDF 转 Markdown 工作台。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> · <a href="#部署教程">部署教程</a> · <a href="#配置说明">配置说明</a> · <a href="#验证">验证</a> · <a href="#文档">文档</a>
</p>

<p align="center">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi" />
  <img alt="React" src="https://img.shields.io/badge/React-frontend-61DAFB?logo=react" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-typed-blue?logo=typescript" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-build-646CFF?logo=vite" />
  <img alt="Vitest" src="https://img.shields.io/badge/Vitest-tested-6E9F18?logo=vitest" />
  <img alt="Storage" src="https://img.shields.io/badge/storage-local%20filesystem-orange" />
</p>

---

## Media-to-MD 是什么？

Media-to-MD 是一个面向个人工作站或内网机器的本地转换服务，用来把音视频和 PDF 转成适合大模型继续处理的 Markdown、TXT、SRT、VTT 和 JSON 文件。

它不提供公网 SaaS、多用户隔离、GPU 调度、HTTPS 证书管理或 Docker 编排；这些部署边界由使用者自行维护。

## 功能

- 音视频转写：支持本机 `whisperx` CLI，也支持 OpenAI 兼容 WhisperX HTTP 服务；输出 SRT，并从返回的 SRT 派生 TXT。
- WhisperX OpenAI 模式支持在管理页从 `/models` 拉取远端模型，并在远端声明进度 sidecar 时显示运行阶段。
- PDF 解析：调用本机 `opendataloader-pdf`，输出 Markdown/TXT，并生成清洗后的 `*_clear.md`。
- LLM 润色可分别为 WhisperX 转写和 OpenDataLoader PDF 输出独立启用。
- Web 工作台：拖拽上传、任务轮询、状态展示、结果 ZIP 下载。
- 管理页：单管理员登录、任务列表、详情、事件、日志、删除任务和后端运行配置。
- 本地任务存储：上传文件、输出产物、日志、事件和 manifest 都保存在本机文件系统。

## 技术栈

| 层 | 选择 |
| --- | --- |
| 后端 | FastAPI, uv, pytest |
| 前端 | React, TypeScript, Vite, Vitest |
| 音视频 runner | 本机 `whisperx` CLI 或 OpenAI 兼容 WhisperX HTTP 服务 |
| PDF runner | 本机 `opendataloader-pdf` CLI |
| 存储 | 本地文件系统任务目录 |

## 部署教程

### 1. 安装系统依赖

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

WhisperX 处理音视频通常需要 `ffmpeg`；PDF 解析依赖 Java 11+。

### 2. 选择音视频转写执行方式

#### 方式 A：本机 WhisperX CLI

适合直接在 Media-to-MD 后端所在机器上运行 WhisperX：

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
uv tool update-shell
```

如果需要 OpenDataLoader PDF 的 Hybrid/OCR 能力：

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
opendataloader-pdf-hybrid --port 5002
```

验证命令可被后端进程找到：

```bash
whisperx --help
opendataloader-pdf --help
java -version
ffmpeg -version
```

#### 方式 B：OpenAI 兼容 WhisperX 服务

适合把 GPU、模型加载和 WhisperX 服务独立到另一个本机进程或局域网机器。

本地部署可使用：

<https://github.com/Chlience/whisperx-openai-server>

启动该服务后，把 Media-to-MD 的 `whisperx_openai_base_url` 指向服务的 `/v1` 地址：

```json
{
  "whisperx_backend": "openai",
  "whisperx_openai_base_url": "http://localhost:9000/v1",
  "whisperx_openai_api_key": null,
  "whisperx_openai_model": "large-v2"
}
```

`whisperx_openai_model` 应使用远端 `/v1/models` 返回的模型 id。管理页可以请求 `OpenAI Base URL + /models`，在右侧下拉框展示返回的模型，并把选中的 id 写回默认模型字段。

OpenAI 模式会向 `/v1/audio/transcriptions` 发送同步 multipart 请求，固定请求 `response_format=srt` 并启用说话人分离；后端保存 `result.srt` 后，会删除 SRT 序号行和时间行派生 `result.txt`。Media-to-MD 只转发适合放入远端 multipart 请求的任务级参数：`batch_size`、`chunk_size`、`no_align`、`min_speakers`、`max_speakers`、`speaker_embeddings`。

设备、compute type、缓存路径、说话人分离模型和 align model 都由 WhisperX 服务端控制，Media-to-MD 不再转发。对齐模型由 WhisperX 根据检测语言自动选择；如需覆盖，应在远端服务自身配置。

如果远端是 `whisperx-openai-server`，并且 `/health` 声明了运行时进度能力，Media-to-MD 会附加远端要求的 request id header，并轮询 sidecar 进度端点显示当前阶段和当前阶段进度。其他 OpenAI 兼容转写服务没有该 sidecar 时仍可正常使用，只是不显示细粒度阶段。

### 3. 配置后端

```bash
cp backend/config.example.json backend/config.json
```

至少修改管理员密码：

```json
{
  "admin_username": "admin",
  "admin_password": "change-me-before-use"
}
```

## 配置说明

常用后端配置项：

| Key | 用途 |
| --- | --- |
| `data_root` | 任务数据目录 |
| `whisperx_backend` | `cli` 或 `openai` |
| `whisperx_cli_model` | CLI 模式默认模型 |
| `whisperx_openai_model` | OpenAI 模式默认模型 |
| `whisperx_model_dir` | 本机模型缓存目录 |
| `model_cache_only` | 是否只使用本地缓存 |
| `whisperx_cli_args` | CLI 模式参数 |
| `whisperx_openai_args` | OpenAI multipart 转发参数：`batch_size`、`chunk_size`、`no_align`、`min_speakers`、`max_speakers`、`speaker_embeddings` |
| `opendataloader_pdf_args` | PDF runner 参数 |
| `whisperx_llm_polish_enabled` / `pdf_llm_polish_enabled` | WhisperX 与 PDF 任务独立的后端 LLM 润色开关 |
| `llm_polish_*` | 共用的 LLM 润色供应商、Base URL、API Key、模型与超时配置 |
| `max_whisperx_upload_mb` / `max_pdf_upload_mb` | 音视频转写与 PDF 解析分别使用的上传大小限制；通过 `/api/health` 暴露，并可在管理页修改 |
| `admin_username` / `admin_password` | 管理页账号 |

完整字段以 `backend/config.example.json` 为准。管理页保存配置时也会写回 `backend/config.json`。

### 4. 启动后端

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

默认 API 地址：

```text
http://localhost:8000/api
```

Swagger / OpenAPI：

```text
http://localhost:8000/docs
```

### 5. 启动前端

```bash
cd frontend
npm install
MEDIA_TO_MD_API_BASE_URL=http://localhost:8000/api npm run dev
```

访问 Vite 输出的地址：

- 工作台：`/#/`
- 管理页：`/#/admin`

`MEDIA_TO_MD_API_BASE_URL` 是前端启动 / 构建时变量。修改后需要重启 Vite dev server；生产包需要重新构建。管理页只读展示当前 API 地址，不再写入浏览器本地覆盖。

### 6. 生产构建

后端可以用你自己的 systemd、supervisor、pm2、tmux 或反向代理方案托管。前端生产包示例：

```bash
cd frontend
MEDIA_TO_MD_API_BASE_URL=https://your-domain.example/api npm run build
```

静态产物在：

```text
frontend/dist/
```

公网访问时建议在外层反向代理处理 HTTPS、域名、访问控制和上传大小限制。

## 任务数据

每个任务位于：

```text
<data_root>/jobs/<job_id>/
  input/               上传文件
  output/              转换产物
  logs/job.log         运行日志
  logs/events.jsonl    任务事件
  manifest.json        任务元数据和 artifact 清单
```

前端下载入口默认下载 `artifacts.zip`。

## 验证

后端：

```bash
cd backend
uv run pytest
uv run --with ruff ruff check .
```

前端：

```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

## 文档

- [本地安装与烟测](docs/local-setup.md)
- [架构说明](docs/architecture.md)
- [直接 CLI runner 契约](docs/direct-cli-runners.md)
- [WhisperX 模型缓存与说话人分离](docs/whisperx-cache-and-diarization.md)
- [WhisperX OpenAI 兼容后端接入](docs/whisperx-openai-backend.md)
