"""OpenAI-compatible LLM polishing helpers for Media-to-MD outputs."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
DEFAULT_LLM_CHUNK_CHARS = 18000


@dataclass(frozen=True)
class LlmProviderPreset:
    id: str
    label: str
    base_url: str | None


LLM_PROVIDER_PRESETS: tuple[LlmProviderPreset, ...] = (
    LlmProviderPreset("openai", "OpenAI", "https://api.openai.com/v1"),
    LlmProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    LlmProviderPreset("moonshot", "Moonshot", "https://api.moonshot.cn/v1"),
    LlmProviderPreset(
        "dashscope",
        "阿里云 DashScope",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    LlmProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"),
    LlmProviderPreset("custom", "自定义 OpenAI 兼容接口", None),
)

_PROVIDER_BY_ID = {provider.id: provider for provider in LLM_PROVIDER_PRESETS}


@dataclass(frozen=True)
class LlmPolishConfig:
    enabled: bool = False
    provider: str = DEFAULT_LLM_PROVIDER
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    chunk_chars: int = DEFAULT_LLM_CHUNK_CHARS


@dataclass(frozen=True)
class LlmPolishJobResult:
    created_paths: tuple[Path, ...] = ()
    source_path: Path | None = None
    skipped_reason: str | None = None


class LlmPolishError(RuntimeError):
    """Raised when a configured LLM polishing request fails."""


def provider_infos() -> list[dict[str, str | None]]:
    return [
        {"id": provider.id, "label": provider.label, "base_url": provider.base_url}
        for provider in LLM_PROVIDER_PRESETS
    ]


def normalize_llm_provider(value: Any) -> str:
    provider = str(value or DEFAULT_LLM_PROVIDER).strip().lower()
    provider = provider.replace("-", "_")
    aliases = {
        "aliyun": "dashscope",
        "qwen": "dashscope",
        "kimi": "moonshot",
        "openai_compatible": "custom",
        "openai-compatible": "custom",
    }
    provider = aliases.get(provider, provider)
    if provider not in _PROVIDER_BY_ID:
        allowed = ", ".join(sorted(_PROVIDER_BY_ID))
        raise ValueError(f"llm_polish_provider must be one of: {allowed}")
    return provider


def default_base_url_for_provider(provider: str) -> str | None:
    return _PROVIDER_BY_ID[normalize_llm_provider(provider)].base_url


def resolve_llm_base_url(provider: str, base_url: str | None) -> str:
    configured = _optional_text(base_url)
    resolved = configured or default_base_url_for_provider(provider)
    if not resolved:
        raise LlmPolishError("LLM 接口地址未配置。")
    return _normalize_openai_base_url(resolved)


def llm_config_from_settings(settings: Any) -> LlmPolishConfig:
    return LlmPolishConfig(
        enabled=bool(getattr(settings, "llm_polish_enabled", False)),
        provider=normalize_llm_provider(
            getattr(settings, "llm_polish_provider", DEFAULT_LLM_PROVIDER)
        ),
        base_url=getattr(settings, "llm_polish_base_url", None),
        api_key=getattr(settings, "llm_polish_api_key", None),
        model=getattr(settings, "llm_polish_model", None),
        timeout_seconds=float(
            getattr(settings, "llm_polish_timeout_seconds", DEFAULT_LLM_TIMEOUT_SECONDS)
        ),
    )


def fetch_llm_models(config: LlmPolishConfig) -> list[str]:
    prepared = _prepare_request_config(config, require_model=False, require_enabled=False)
    url = _build_openai_compatible_url(prepared.base_url or "", "models")
    payload = _request_json("GET", url, None, prepared)
    return _extract_model_ids(payload)


def check_llm_connection(config: LlmPolishConfig) -> tuple[bool, str, list[str]]:
    try:
        models = fetch_llm_models(config)
    except Exception as exc:
        return False, str(exc), []
    model = _optional_text(config.model)
    if model and models and model not in models:
        return (
            True,
            f"连接成功；已拉取 {len(models)} 个模型，但当前模型不在返回列表中。",
            models,
        )
    if models:
        return True, f"连接成功；已拉取 {len(models)} 个模型。", models
    return True, "连接成功；供应商未返回可枚举模型。", models


def polish_job_outputs(
    storage: Any,
    job_id: str,
    *,
    task_type: str,
    config: LlmPolishConfig,
) -> LlmPolishJobResult:
    prepared = _prepare_request_config(config, require_model=True, require_enabled=True)
    output_root = storage.job_dir(job_id) / "output"
    source_path = _select_polish_source(output_root, task_type=task_type)
    if source_path is None:
        return LlmPolishJobResult(skipped_reason="未找到可用于 LLM 润色的文本输出。")
    text = source_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return LlmPolishJobResult(
            source_path=source_path,
            skipped_reason="文本输出为空，已跳过 LLM 润色。",
        )
    polished = polish_text(
        text, config=prepared, source_name=source_path.name, task_type=task_type
    )
    target_path = _polished_output_path(source_path, task_type=task_type)
    target_path.write_text(polished.rstrip() + "\n", encoding="utf-8")
    return LlmPolishJobResult(created_paths=(target_path,), source_path=source_path)


def polish_text(
    text: str,
    *,
    config: LlmPolishConfig,
    source_name: str,
    task_type: str = "generic",
) -> str:
    prepared = _prepare_request_config(config, require_model=True, require_enabled=False)
    chunks = _split_text(text, max_chars=max(1000, prepared.chunk_chars))
    if len(chunks) == 1:
        return _polish_chunk(
            chunks[0],
            config=prepared,
            source_name=source_name,
            task_type=task_type,
        )

    polished_chunks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_source = f"{source_name} 第 {index}/{len(chunks)} 段"
        polished_chunks.append(
            _polish_chunk(
                chunk,
                config=prepared,
                source_name=chunk_source,
                task_type=task_type,
            )
        )
    return "\n\n".join(polished_chunks)


def _prepare_request_config(
    config: LlmPolishConfig,
    *,
    require_model: bool,
    require_enabled: bool,
) -> LlmPolishConfig:
    if require_enabled and not config.enabled:
        raise LlmPolishError("LLM 润色未启用。")
    provider = normalize_llm_provider(config.provider)
    base_url = resolve_llm_base_url(provider, config.base_url)
    api_key = _optional_text(config.api_key)
    if provider != "custom" and not api_key:
        raise LlmPolishError("LLM API 密钥未配置。")
    model = _optional_text(config.model)
    if require_model and not model:
        raise LlmPolishError("LLM 模型未配置。")
    timeout = float(config.timeout_seconds or DEFAULT_LLM_TIMEOUT_SECONDS)
    if timeout <= 0:
        raise LlmPolishError("LLM timeout seconds 必须是大于 0 的数字。")
    return LlmPolishConfig(
        enabled=config.enabled,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout,
        chunk_chars=config.chunk_chars,
    )


def _polish_chunk(
    chunk: str, *, config: LlmPolishConfig, source_name: str, task_type: str
) -> str:
    url = _build_openai_compatible_url(config.base_url or "", "chat/completions")
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": _polish_system_prompt(task_type),
            },
            {
                "role": "user",
                "content": _polish_user_prompt(
                    chunk, source_name=source_name, task_type=task_type
                ),
            },
        ],
        "temperature": 0.2,
    }
    response = _request_json("POST", url, payload, config)
    return _extract_chat_content(response)


def _polish_system_prompt(task_type: str) -> str:
    if task_type == "whisperx":
        return (
            "你是严谨的 ASR 转写纠错编辑。你的任务是识别并修正语音识别过程中"
            "可能产生的错词、断句、标点、重复口癖和专有名词错误。保持原意、事实、"
            "数字、引用、段落顺序和说话人标签，不新增信息，不总结，不压缩内容，不翻译。"
            "不确定时保留原文。只输出纠错后的正文。"
        )
    return (
        "你是严谨的文档校对编辑。你的任务是修正 OCR/PDF 提取文本中明显的错字、"
        "断行、标点和结构问题。保持原意、事实、数字、引用、段落顺序和既有 Markdown 结构，"
        "不新增信息，不总结，不压缩内容，不翻译。不确定时保留原文。只输出校对后的正文。"
    )


def _polish_user_prompt(chunk: str, *, source_name: str, task_type: str) -> str:
    if task_type == "whisperx":
        intro = f"下面是来自 {source_name} 的原始转写文本，已从 SRT 中删除序号行和时间行。"
        action = "请进行 ASR 纠错，不要总结或改写成摘要。"
        requirements = (
            "1. 只修正明显由识别错误导致的问题，例如同音错词、错误断句、标点、重复口癖、专有名词。\n"
            "2. 保留原文语言、信息密度、语义顺序和说话人标签。\n"
            "3. 不新增事实，不删除要点，不翻译，不输出标题、摘要、要点列表，除非原文已有。\n"
            "4. 如果无法判断是否错误，保留原句。"
        )
    else:
        intro = f"下面是来自 {source_name} 的原始文档提取文本。"
        action = "请进行校对纠错，不要总结或改写成摘要。"
        requirements = (
            "1. 只修正明显的 OCR/PDF 提取错误、断行、标点、空白和 Markdown 结构问题。\n"
            "2. 保留原文语言、信息密度、语义顺序、标题层级、表格和列表结构。\n"
            "3. 不新增事实，不删除要点，不翻译，不输出摘要或额外说明。\n"
            "4. 如果无法判断是否错误，保留原句。"
        )
    return f"{intro}\n{action}要求：\n{requirements}\n\n{chunk}"


def _request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    config: LlmPolishConfig,
) -> Mapping[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # noqa: S310 - operator-configured endpoint.
            request, timeout=config.timeout_seconds
        ) as response:
            status = getattr(response, "status", None) or response.getcode()
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise LlmPolishError(
            f"LLM 接口请求失败（HTTP {exc.code}）：{_extract_error_message(body)}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise LlmPolishError(f"LLM 接口连接失败：{reason}") from exc
    except TimeoutError as exc:
        raise LlmPolishError("LLM 接口请求超时。") from exc

    if status < 200 or status >= 300:
        raise LlmPolishError(
            f"LLM 接口请求失败（HTTP {status}）：{_extract_error_message(body)}"
        )
    try:
        decoded = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LlmPolishError("LLM 接口返回的不是合法 JSON。") from exc
    if not isinstance(decoded, Mapping):
        raise LlmPolishError("LLM 接口返回必须是 JSON object。")
    return decoded


def _extract_model_ids(payload: Mapping[str, Any]) -> list[str]:
    raw_models = payload.get("data")
    if raw_models is None:
        raw_models = payload.get("models")
    models: list[str] = []
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, str):
                model_id = item.strip()
            elif isinstance(item, Mapping):
                model_id = str(
                    item.get("id") or item.get("model") or item.get("name") or ""
                ).strip()
            else:
                model_id = ""
            if model_id and model_id not in models:
                models.append(model_id)
    return models


def _extract_chat_content(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmPolishError("LLM 接口返回缺少 choices。")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LlmPolishError("LLM 接口返回 choices 格式不正确。")
    message = first.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    text = first.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise LlmPolishError("LLM 接口返回缺少润色文本。")


def _extract_error_message(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return "empty response body"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, Mapping):
        error = data.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return text


def _normalize_openai_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise LlmPolishError("LLM 接口地址未配置。")
    for suffix in ("/chat/completions", "/models"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _build_openai_compatible_url(base_url: str, endpoint: str) -> str:
    normalized = _normalize_openai_base_url(base_url)
    return f"{normalized}/{endpoint.strip('/')}"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(char in text for char in ("\x00", "\n", "\r")):
        raise LlmPolishError("LLM 配置值必须是单行文本。")
    return text


def _split_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[str] = []
    current = ""
    for part in paragraphs:
        if not part:
            continue
        if len(current) + len(part) <= max_chars:
            current += part
            continue
        if current.strip():
            chunks.append(current.strip())
        if len(part) <= max_chars:
            current = part
            continue
        for start in range(0, len(part), max_chars):
            piece = part[start : start + max_chars].strip()
            if piece:
                chunks.append(piece)
        current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _select_polish_source(output_root: Path, *, task_type: str) -> Path | None:
    if not output_root.exists():
        return None
    candidates = [path for path in output_root.rglob("*") if _is_polishable_file(path)]
    if not candidates:
        return None

    def rank(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        suffix = path.suffix.lower()
        if task_type == "pdf":
            if name.endswith("_clear.md"):
                return (0, path.as_posix())
            if suffix in {".md", ".markdown"}:
                return (1, path.as_posix())
            if suffix == ".txt":
                return (2, path.as_posix())
            return (9, path.as_posix())
        if name == "result.txt":
            return (0, path.as_posix())
        if suffix == ".txt":
            return (1, path.as_posix())
        if suffix in {".md", ".markdown"}:
            return (2, path.as_posix())
        return (9, path.as_posix())

    return sorted(candidates, key=rank)[0]


def _is_polishable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    if name == "llm_polished.md" or name.endswith("_llm.md"):
        return False
    if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
        return False
    return path.stat().st_size > 0


def _polished_output_path(source_path: Path, *, task_type: str) -> Path:
    if task_type == "pdf":
        stem = source_path.stem
        if stem.endswith("_clear"):
            stem = stem[: -len("_clear")]
        return source_path.with_name(f"{stem}_llm.md")
    return source_path.with_name("llm_polished.md")
