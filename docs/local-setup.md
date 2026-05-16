# 本地安装与烟测

## 前置条件

- Python 3.12+
- uv
- Node.js 与 npm
- Java 11+ 运行时或 JDK（PDF 必需）
- ffmpeg（WhisperX 读取音视频常用）
- 本机可执行命令：`opendataloader-pdf`；如果音视频使用默认 CLI 模式，还需要 `whisperx`

## 安装 WhisperX 与 OpenDataLoader PDF

推荐把外部 CLI 安装为独立的 `uv tool`，后端只负责调用 `PATH` 中已有的 `whisperx` 和 `opendataloader-pdf`：

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
```

如果需要 PDF Hybrid/OCR 模式，安装带 extra 的 OpenDataLoader PDF：

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
```

启用 `opendataloader_pdf_args.hybrid = "docling-fast"` 前，需要先启动本机 Hybrid 服务：

```bash
opendataloader-pdf-hybrid --port 5002
```

Ubuntu / Debian 可这样安装系统依赖：

```bash
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

如果安装后 shell 找不到命令，执行：

```bash
uv tool update-shell
```

然后重新打开终端，或手动把 `uv tool dir` 对应的可执行目录加入 `PATH`。

## 检查

```bash
python --version
uv --version
node --version
npm --version
java -version
ffmpeg -version
whisperx --help
opendataloader-pdf --help
```

CLI 模式下后端进程必须也能看到这些命令。最小运行时检查是：

```bash
java -version
ffmpeg -version
whisperx --help
opendataloader-pdf --help
```

## 可选：使用 WhisperX OpenAI 兼容服务

如果不想让 Media-to-MD 直接调用 `whisperx` CLI，可以先单独启动 `whisperx-openai-server`，再在 `backend/config.json` 中设置：

本地部署可使用 <https://github.com/Chlience/whisperx-openai-server>。按该项目说明启动服务后，把 `whisperx_openai_base_url` 指向它的 `/v1` 地址即可。

```json
{
  "whisperx_backend": "openai",
  "whisperx_openai_base_url": "http://localhost:9000/v1",
  "whisperx_openai_api_key": null,
  "whisperx_openai_transcode_to_mp3": true,
  "whisperx_openai_mp3_bitrate": "64k"
}
```

此时音视频任务会调用 `/v1/audio/transcriptions`，请求远端前默认先把已接收文件转成临时 MP3 以降低第二跳上传体积，并在 Media-to-MD 侧生成 `result.srt` 与从 SRT 派生的 `result.txt`。

## 后端

```bash
cd backend
cp config.example.json config.json
uv sync --dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/api/health
```

## 前端

```bash
cd frontend
npm install
MEDIA_TO_MD_API_BASE_URL=http://localhost:8000/api npm run dev
```

`MEDIA_TO_MD_API_BASE_URL` 是前端启动/构建时变量；修改后需要重启 Vite dev server，生产包需要重新构建。如果使用 `.env` 文件，请放到 `frontend/.env`，或在启动命令前显式导出变量。管理页只读展示当前启动配置，不再提供浏览器本地覆盖。

访问：

- 工作台：`http://localhost:5173/#/`
- 管理页：`http://localhost:5173/#/admin`

如果从 Windows 浏览器访问 WSL/Linux 中的前端，确保 Vite 使用 `--host 0.0.0.0`，并使用宿主机可访问的 IP 或端口转发地址。

## 音视频烟测

1. 在工作台选择音视频转写。
2. 上传一个小音频文件。
3. 等待任务结束。
4. 下载 artifacts ZIP，确认包含 `txt`、`srt`、`vtt`，以及按需公开的 `json`。

## PDF 烟测

1. 确认 `java -version` 成功。
2. 在工作台选择 PDF 文档解析。
3. 上传一个小 PDF。
4. 下载 artifacts ZIP，确认包含原始 Markdown/TXT 和 `<origin>_clear.md`。

## 验证命令

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
