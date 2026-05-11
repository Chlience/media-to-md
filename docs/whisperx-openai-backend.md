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
    "chunk_size": 30
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

管理页拉取 WhisperX OpenAI 模型时会按 LLM 润色同样的 OpenAI-compatible 规则请求：

- 先把配置地址规范化为 OpenAI Base URL（没有 `/v1` 时补上 `/v1`，如果填了 `/audio/transcriptions` 或 `/models` 会先还原到 Base URL）。
- 再访问 `OpenAI Base URL + /models`。

## 运行时进度

OpenAI 音频转写接口是同步阻塞接口，标准协议没有任务进度字段。为了兼容其他 OpenAI-compatible 服务，Media-to-MD 不会向 multipart 表单添加任何非标准进度字段。

当远端是 `whisperx-openai-server` 且 `/health` 返回：

```json
{
  "runtime_progress": true,
  "runtime_progress_header": "X-Request-ID",
  "runtime_progress_endpoint": "/runtime/progress/{request_id}",
  "runtime_progress_protocol": {
    "name": "whisperx-runtime-progress",
    "version": 1,
    "transports": ["polling"],
    "request_id_header": "X-Request-ID",
    "snapshot_endpoint": "/runtime/progress/{request_id}",
    "features": {
      "stagePercent": true,
      "stageDisplay": true,
      "stageKind": true,
      "terminalStatus": true
    }
  }
}
```

Media-to-MD 会自动启用该服务的非 OpenAI sidecar 进度能力：

1. 对 `/v1/audio/transcriptions` 请求附加 `X-Request-ID: <job_id>`。
2. 并行轮询 `/runtime/progress/<job_id>`。
3. 优先使用 sidecar 返回的 `stageKind`、`stageLabel`、`stageDetail` 和 `stagePercent` 显示当前阶段。
4. 如果远端只支持旧格式，则回退到 `stage` / `stagePercent` / `message`。

如果远端没有这个能力，或者 `/health` 不存在，任务仍按普通 OpenAI 兼容模式执行，只显示提交、等待和完成/失败日志。

## 请求参数映射

Media-to-MD 会向 OpenAI 兼容接口发送 multipart 表单：

- 固定发送：`file`, `model`, `response_format=srt`, `diarize=true`
- 语言：前台选择 `auto` 时不发送 `language`；手动选择时发送语言代码。
- 说话人分离：始终开启；工作台不再提供关闭或每任务说话人数配置。
- `whisperx_openai_args` 中会转发给远端的字段：`batch_size`, `chunk_size`, `no_align`, `align_model`, `min_speakers`, `max_speakers`, `speaker_embeddings`。

`device`, `compute_type`, `model_dir`, `nltk_data_dir`、`diarize_model` 这类运行环境/模型加载参数在 `openai` 模式下由远端 `whisperx-openai-server` 自己控制，Media-to-MD 不转发。旧版 `whisperx_args` 仍会作为兼容回退读取；保存配置时会拆为 `whisperx_cli_args` 与 `whisperx_openai_args`。

## 输出文件

OpenAI 兼容接口直接返回 SRT；Media-to-MD 会把它保存为字幕并派生纯文本 artifacts：

- `result.srt`：远端返回的 SRT 字幕。
- `result.txt`：从 `result.srt` 删除序号行和时间行后派生的纯文本。

所以前端下载、ZIP 打包、任务列表只公开 SRT 与派生 TXT。

## 管理页配置

管理页的「后端运行配置 → WhisperX」里新增了：

- 执行方式：本机 CLI / OpenAI 兼容接口。
- OpenAI Base URL。
- OpenAI API Key：留空会保持已配置值不变。
- OpenAI timeout seconds。
- 清除 OpenAI Key。
- 拉取 WhisperX 模型：请求 `OpenAI Base URL + /models`，返回后可在右侧下拉框选择，并自动写入上方默认模型字段。

保存后会写回 `backend/config.json`，并重建后端 runner。
