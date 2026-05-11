# WhisperX OpenAI 兼容后端接入

Media-to-MD 的音视频转写现在有两种执行方式：

- `cli`：默认方式，后端直接调用本机 `whisperx` 命令。
- `openai`：后端通过 OpenAI 兼容的 HTTP 接口调用 `whisperx-openai-server`，不再在 Media-to-MD 进程里直接跑 WhisperX。

PDF 任务不受影响，仍走 `opendataloader-pdf`。

## 适用场景

如果你已经单独启动了 `whisperx-openai-server`，或者想把 GPU/模型加载放在另一个服务进程/机器里，就把 Media-to-MD 切到 `openai` 模式。

## 本地部署服务

如果需要在本机或局域网机器上部署 OpenAI 兼容 WhisperX 服务，可以使用：

<https://github.com/Chlience/whisperx-openai-server>

按该项目说明启动服务后，把 Media-to-MD 的 `whisperx_openai_base_url` 指向服务地址即可。例如服务监听 `9000` 端口时，可以配置为 `http://localhost:9000/v1`。

## 配置方式

编辑 `backend/config.json`：

```json
{
  "whisperx_backend": "openai",
  "whisperx_openai_base_url": "http://localhost:9000/v1",
  "whisperx_openai_api_key": null,
  "whisperx_openai_timeout_seconds": 3600,
  "whisperx_cli_model": "small",
  "whisperx_openai_model": "large-v2",
  "whisperx_openai_args": {
    "batch_size": 8,
    "chunk_size": 30,
    "diarize_model": "/home/chlience/model/pyannote-speaker-diarization-community-1"
  }
}
```

也可以用环境变量覆盖：

```bash
export WHISPERX_BACKEND=openai
export WHISPERX_OPENAI_BASE_URL=http://localhost:9000/v1
export WHISPERX_OPENAI_API_KEY=your-server-api-key
export WHISPERX_OPENAI_TIMEOUT_SECONDS=3600
export WHISPERX_OPENAI_ARGS_JSON='{"batch_size":8}'
```

如果 `whisperx-openai-server` 启用了 `WHISPERX_SERVER_API_KEY`，这里的 `WHISPERX_OPENAI_API_KEY` 要填同一个值；否则可以留空。

## Base URL 写法

以下三种写法都可以：

- `http://localhost:9000`
- `http://localhost:9000/v1`
- `http://localhost:9000/v1/audio/transcriptions`

Media-to-MD 最终会调用 `/v1/audio/transcriptions`。

## 运行时进度

OpenAI 音频转写接口是同步阻塞接口，标准协议没有任务进度字段。为了兼容其他 OpenAI-compatible 服务，Media-to-MD 不会向 multipart 表单添加任何非标准进度字段。

当远端是 `whisperx-openai-server` 且 `/health` 返回：

```json
{
  "runtime_progress": true,
  "runtime_progress_header": "X-Request-ID"
}
```

Media-to-MD 会自动启用该服务的非 OpenAI sidecar 进度能力：

1. 对 `/v1/audio/transcriptions` 请求附加 `X-Request-ID: <job_id>`。
2. 并行轮询 `/runtime/progress/<job_id>`。
3. 把阶段和百分比写入任务 Log。

如果远端没有这个能力，或者 `/health` 不存在，任务仍按普通 OpenAI 兼容模式执行，只显示提交、等待和完成/失败日志。

## 请求参数映射

Media-to-MD 会向 OpenAI 兼容接口发送 multipart 表单：

- 固定发送：`file`, `model`, `response_format=verbose_json`, `timestamp_granularities[]=segment`
- 语言：前台选择 `auto` 时不发送 `language`；手动选择时发送语言代码。
- 说话人分离：开启时发送 `diarize=true`，以及可选的 `min_speakers` / `max_speakers`。
- `whisperx_openai_args` 中会转发给远端的字段：`batch_size`, `chunk_size`, `no_align`, `align_model`, `diarize_model`, `min_speakers`, `max_speakers`, `speaker_embeddings`。

`device`, `compute_type`, `model_dir`, `nltk_data_dir` 这类运行环境参数仍保留在 CLI 配置里，但在 `openai` 模式下主要由远端 `whisperx-openai-server` 自己控制。旧版 `whisperx_args` 仍会作为兼容回退读取；保存配置时会拆为 `whisperx_cli_args` 与 `whisperx_openai_args`。

## 输出文件

OpenAI 兼容接口一次返回 JSON；Media-to-MD 会把它转换成原有 artifacts：

- `result.json`：原始 `verbose_json` 响应。
- `result.txt`：`text` 字段。
- `result.srt` / `result.vtt`：由 `segments` 生成的字幕。

所以前端下载、ZIP 打包、任务列表逻辑保持不变。

## 管理页配置

管理页的「后端运行配置 → WhisperX」里新增了：

- 执行方式：本机 CLI / OpenAI 兼容接口。
- OpenAI Base URL。
- OpenAI API Key：留空会保持已配置值不变。
- OpenAI timeout seconds。
- 清除 OpenAI Key。

保存后会写回 `backend/config.json`，并重建后端 runner。
