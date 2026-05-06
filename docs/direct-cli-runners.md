# 直接 CLI Runner 契约

后端运行任务时直接调用本机命令，不通过 shell 拼接字符串，也不会在任务运行时临时安装包。部署者需要提前安装并验证命令在 `PATH` 中。

## 安装建议

推荐把 WhisperX 和 OpenDataLoader PDF 安装为独立 `uv tool`：

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
```

需要 PDF Hybrid/OCR 能力时：

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
```

启用 `opendataloader_pdf_args.hybrid = "docling-fast"` 前，需要先启动本机 Hybrid 服务：

```bash
opendataloader-pdf-hybrid --port 5002
```

系统依赖：

- WhisperX 读取音视频通常需要 `ffmpeg`。
- OpenDataLoader PDF 需要 Java 11+。

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

验证：

```bash
whisperx --help
opendataloader-pdf --help
ffmpeg -version
java -version
```

## WhisperX

后端构造的核心形式：

```bash
whisperx <input-media> \
  --model <model-or-local-path> \
  --output_dir <job-output> \
  --output_format <format> \
  --model_dir <cache-dir> \
  <whisperx_args>
```

公开上传页只允许用户选择语言和少量任务参数；模型、缓存和批处理等运行参数由后端配置或管理页维护。

允许的 `whisperx_args`：

`batch_size`, `device`, `device_index`, `compute_type`, `threads`, `chunk_size`, `vad_method`, `vad_onset`, `vad_offset`, `align_model`

## OpenDataLoader PDF

后端构造的核心形式：

```bash
opendataloader-pdf <input.pdf> \
  -o <job-output> \
  --format <formats> \
  <opendataloader_pdf_args>
```

当请求 Markdown 输出时，后端会确保 JSON 也可用于后处理。后处理会保留原始 Markdown，并生成 `<origin>_clear.md`。

允许的 `opendataloader_pdf_args`：

`format`, `pages`, `threads`, `image_output`, `image_format`, `table_method`, `reading_order`, `hybrid`, `hybrid_mode`, `hybrid_timeout`

不开放的参数包括自定义输出目录、标准输出重定向、图片目录和远程 Hybrid URL，因为它们会绕开后端任务目录和 artifact 收集边界。

## 错误处理

- 命令缺失、Java 缺失或返回非零退出码时，任务会失败并写入日志。
- 管理员可在任务详情中查看事件和运行日志。
- 普通用户页面只显示任务状态和下载入口，不显示日志。
