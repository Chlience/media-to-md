# Media-to-MD 后端

后端是一个本地 FastAPI 服务，负责接收上传、创建任务、调用本机 CLI、收集输出、记录日志和提供受保护的管理 API。

## 职责边界

后端负责：

- 保存上传文件到 backend-owned 任务目录。
- 为 WhisperX CLI 和 PDF 任务构造安全的 argv 列表，不通过 shell 拼接命令。
- 调用本机 `whisperx` 与 `opendataloader-pdf`，或在 OpenAI 兼容模式下调用远端 WhisperX HTTP 服务。
- 发现并登记 manifest 中允许下载的 artifacts。
- 保存 `logs/job.log` 和 `logs/events.jsonl`。
- 提供公开任务状态/结果 API 和管理员 API。

后端不负责：

- 在任务运行时临时安装模型或外部 CLI。
- 公网身份体系、多租户隔离、GPU 调度、HTTPS 终止。
- 兼容发布前的旧任务 manifest 或旧 artifact 文件名。

## 安装外部 CLI

默认后端任务直接调用本机 `whisperx` 和 `opendataloader-pdf`，不会在任务运行时临时安装外部包。若音视频转写使用 `whisperx_backend=openai`，则只调用已启动的 WhisperX OpenAI 兼容服务。CLI 模式建议用独立的 `uv tool` 安装外部命令：

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
```

如果需要 OpenDataLoader PDF 的 Hybrid/OCR 能力：

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
```

启用 `opendataloader_pdf_args.hybrid = "docling-fast"` 前，需要先启动本机 Hybrid 服务：

```bash
opendataloader-pdf-hybrid --port 5002
```

系统依赖示例：

```bash
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

安装后确认命令对后端进程可见：

```bash
whisperx --help
opendataloader-pdf --help
java -version
ffmpeg -version
```

若找不到 `whisperx` 或 `opendataloader-pdf`，执行 `uv tool update-shell` 后重新打开终端，或手动把 `uv tool` 的可执行目录加入 `PATH`。

## 启动

```bash
cd backend
cp config.example.json config.json
uv sync --dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动前再次检查外部命令：

```bash
whisperx --help
opendataloader-pdf --help
java -version
ffmpeg -version
```

## 配置

`config.example.json` 是运行配置模板。环境变量仅用于少量覆盖：

| 环境变量 | 作用 |
| --- | --- |
| `WHISPERX_CONFIG_FILE` | 指定配置文件路径；设为空字符串可禁用配置文件读取。 |
| `MEDIA_TO_MD_API_BASE_URL` | 覆盖返回给前端的 API 地址。 |
| `WHISPERX_MODEL` / `WHISPERX_MODEL_DIR` | 覆盖默认模型与模型缓存目录。 |
| `WHISPERX_MODEL_CACHE_ONLY` | 覆盖是否只使用本地模型缓存。 |
| `WHISPERX_ARGS_JSON` | 覆盖 `whisperx_args`。 |
| `WHISPERX_BACKEND` | 音视频转写执行方式：`cli` 或 `openai`。 |
| `WHISPERX_OPENAI_BASE_URL` | OpenAI 兼容 WhisperX 服务地址，如 `http://localhost:9000/v1`。 |
| `WHISPERX_OPENAI_API_KEY` | 调用 OpenAI 兼容服务时发送的 Bearer Key。 |
| `WHISPERX_OPENAI_TIMEOUT_SECONDS` | OpenAI 兼容服务请求超时时间。 |
| `OPENDATALOADER_PDF_ARGS_JSON` | 覆盖 `opendataloader_pdf_args`。 |
| `WHISPERX_ADMIN_USERNAME` / `WHISPERX_ADMIN_PASSWORD` | 覆盖管理员账号。 |

`MEDIA_TO_MD_API_BASE_URL` 同时会作为前端启动/构建时变量使用；修改后需要重启前端 dev server，生产包需要重新构建。若浏览器保存过旧地址，可在管理页先应用 API 地址到本浏览器，或清理 localStorage 的 `media_to_md_api_base_url`。

### 允许的 WhisperX 参数

`batch_size`, `device`, `device_index`, `compute_type`, `threads`, `chunk_size`, `vad_method`, `vad_onset`, `vad_offset`, `align_model`, `diarize_model`, `min_speakers`, `max_speakers`, `speaker_embeddings`, `no_align`

这些参数会转换为对应的 WhisperX CLI flag，例如：

```json
"whisperx_args": {
  "batch_size": 8,
  "compute_type": "float16",
  "device": "cuda"
}
```


### WhisperX OpenAI 兼容模式

设置 `whisperx_backend = "openai"` 后，音视频任务会调用 `whisperx_openai_base_url` 对应的 `/v1/audio/transcriptions`，并把返回的 `verbose_json` 转成原有的 `result.txt`、`result.srt`、`result.vtt` 和 `result.json` artifacts。详见 `docs/whisperx-openai-backend.md`。

### 允许的 PDF 参数

`format`, `pages`, `threads`, `image_output`, `image_format`, `table_method`, `reading_order`, `hybrid`, `hybrid_mode`, `hybrid_timeout`

示例：

```json
"opendataloader_pdf_args": {
  "format": ["markdown", "text"],
  "image_output": "off",
  "threads": 1,
  "hybrid": "off"
}
```

后端始终为 OpenDataLoader 提供任务托管输出目录。为保证 artifact 收集与下载安全，配置中不开放自定义输出目录、标准输出重定向、图片目录或远程 Hybrid URL。

## API 概览

公开 API：

- `GET /api/health`
- `POST /api/jobs/upload`
- `GET /api/jobs/{job_id}/status`
- `GET /api/jobs/{job_id}/results`
- `GET /api/jobs/{job_id}/artifacts.zip`
- `GET /api/jobs/{job_id}/download/{artifact_name}`

管理员 API：

- `POST /api/admin/login`
- `GET /api/admin/account`
- `PUT /api/admin/account`
- `GET /api/admin/config`
- `PUT /api/admin/config`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}/events`
- `GET /api/jobs/{job_id}/logs`
- `GET /api/jobs/{job_id}/logs/download`
- `DELETE /api/jobs/{job_id}`

OpenAPI 文档由 FastAPI 自动提供：`/docs`。

## 输出与清洗

PDF runner 在需要 Markdown 后处理时会自动确保 JSON 输出可用于清洗。后处理保留原始 Markdown，同时写出 `<origin>_clear.md`。清洗逻辑会基于 OpenDataLoader JSON 中的图片区域、隐藏文本、短碎片和图片/图注邻域启发式，尽量减少图片内文字进入正文。

## 测试

```bash
cd backend
uv run pytest
uv run --with ruff ruff check .
```
