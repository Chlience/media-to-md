# WhisperX 模型缓存与说话人分离

## 模型来源

`whisperx_model` 可以是 WhisperX/Faster-Whisper 支持的模型名，也可以是后端机器可访问的本地模型目录。若使用本地目录，请确保目录结构满足上游 `whisperx` / `faster-whisper` 的加载要求。

示例配置：

```json
{
  "whisperx_model": "/models/faster-whisper-large-v2",
  "whisperx_model_dir": "/models/whisperx-cache",
  "model_cache_only": true
}
```

## 缓存只读模式

`model_cache_only=true` 会要求运行时只使用本地已有缓存。适合离线机器，但前提是：

- Whisper/Faster-Whisper 模型已在本地。
- 对齐模型已在本地缓存或通过 `align_model` 指定。
- 说话人分离所需模型已在本地，且相关权限/令牌已处理。
- NLTK 数据目录可用。

如果缓存不完整，任务会失败；管理员可通过日志查看缺失文件或下载请求。

## 对齐模型

可通过 `whisperx_args.align_model` 指定对齐模型名或本地路径。不同语言需要匹配的 wav2vec2/对齐模型。若中文或其他语言对齐失败，建议先用命令行直接运行 `whisperx` 验证上游模型加载，再把稳定参数写入后端配置。

## 说话人分离

普通工作台可以开启 diarize。说话人分离通常需要额外模型和本地缓存。若运行环境没有准备好，建议先关闭 diarize，确认基础转写成功后再启用。

管理员可以在运行配置中设置说话人分离相关参数：

```json
{
  "whisperx_args": {
    "diarize_model": "/models/whisperx-cache/pyannote-speaker-diarization-community-1",
    "min_speakers": 1,
    "max_speakers": 4,
    "speaker_embeddings": true
  }
}
```

`diarize_model` 建议指向已下载到本机的 pyannote diarization 模型目录。`min_speakers` / `max_speakers` 可留空由模型自动判断；只有需要把说话人向量写入 JSON 时才开启 `speaker_embeddings`。Hugging Face token 不通过管理页保存，若仍需访问 gated 模型，请在启动后端或直接运行 CLI 的环境中提供 token。

## 常见问题

### 本地模型路径被当成 Hugging Face repo id

确认传给 `--model` 的本地目录是 `whisperx` 当前版本支持的模型目录，并且后端配置没有多余引号或不可见字符。必要时先在同一 shell 中直接执行：

```bash
whisperx sample.mp3 --model /path/to/model --model_dir /path/to/cache
```

### NLTK 下载触发网络或安全拦截

把 NLTK 数据提前放入本地目录，并设置：

```json
{
  "nltk_data_dir": "/path/to/cache/nltk_data"
}
```

### 离线模式失败

关闭 `model_cache_only` 可以让上游工具尝试下载缺失模型；如果机器必须离线，则需要先在有网络的环境中准备完整缓存。
