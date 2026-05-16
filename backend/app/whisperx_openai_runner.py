"""OpenAI-compatible WhisperX runner for Media-to-MD jobs.

This runner lets the backend submit media to a WhisperX service exposing
OpenAI's ``/v1/audio/transcriptions`` multipart shape, then stores the
SRT response and derives plain text from it for the UI.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .llm_polish import (
    LlmPolishConfig,
    llm_config_from_settings,
    polish_job_outputs,
)
from .runtime_progress import (
    append_progress_event,
    phase_from_openai_progress,
    runtime_phase,
)
from .srt_text import derive_plain_text_from_srt_outputs, write_plain_text_from_srt
from .whisperx_runner import (
    LogCallback,
    WhisperXErrorKind,
    WhisperXOptions,
    WhisperXRunResult,
    WhisperXRunnerConfig,
    WhisperXRunnerError,
    options_from_job_options,
    validate_options,
)

ProgressCallback = Callable[[Mapping[str, Any]], Awaitable[None] | None]

_OPENAI_CONFIG_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "batch_size",
        "chunk_size",
        "no_align",
        "min_speakers",
        "max_speakers",
        "speaker_embeddings",
    }
)

_AUDIO_UPLOAD_CONTENT_TYPES: Mapping[str, str] = {
    ".aac": "audio/aac",
    ".adts": "audio/aac",
    ".aif": "audio/aiff",
    ".aifc": "audio/aiff",
    ".aiff": "audio/aiff",
    ".amr": "audio/amr",
    ".ape": "audio/ape",
    ".au": "audio/basic",
    ".caf": "audio/x-caf",
    ".flac": "audio/flac",
    ".m2a": "audio/mpeg",
    ".m3a": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mka": "audio/x-matroska",
    ".mp2": "audio/mpeg",
    ".mp2a": "audio/mpeg",
    ".mp3": "audio/mpeg",
    ".mp4a": "audio/mp4",
    ".mpa": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".ra": "audio/x-pn-realaudio",
    ".snd": "audio/basic",
    ".spx": "audio/ogg",
    ".wav": "audio/wav",
    ".weba": "audio/webm",
    ".wma": "audio/x-ms-wma",
}


@dataclass(frozen=True)
class OpenAIWhisperXRunnerConfig:
    """Runtime configuration for the OpenAI-compatible WhisperX HTTP client."""

    base_url: str | None
    api_key: str | None = None
    default_model: str = "small"
    timeout_seconds: float = 3600.0
    progress_poll_interval_seconds: float = 2.0
    transcode_to_mp3: bool = True
    mp3_bitrate: str = "64k"
    config_fields: Mapping[str, Any] = field(default_factory=dict)
    llm_config: LlmPolishConfig = field(default_factory=LlmPolishConfig)


@dataclass(frozen=True)
class OpenAIWhisperXRunRequest:
    input_path: Path
    output_dir: Path
    log_path: Path
    options: WhisperXOptions
    request_id: str | None = None
    input_content_type: str | None = None


@dataclass(frozen=True)
class OpenAIWhisperXRunResult(WhisperXRunResult):
    endpoint: str = ""
    response_text: str = ""


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


def build_openai_transcriptions_url(base_url: str) -> str:
    """Build the audio transcriptions URL from an OpenAI-compatible base URL.

    Accepts ``http://host:port``, ``http://host:port/v1`` or a fully-qualified
    ``.../audio/transcriptions`` endpoint.
    """

    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "WHISPERX_OPENAI_BASE_URL must not be empty when WHISPERX_BACKEND=openai.",
        )
    if normalized.endswith("/audio/transcriptions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/audio/transcriptions"
    return f"{normalized}/v1/audio/transcriptions"


def build_openai_service_root_url(base_url: str) -> str:
    """Build the service root URL from supported OpenAI-compatible URL forms."""

    endpoint = build_openai_transcriptions_url(base_url)
    marker = "/v1/audio/transcriptions"
    if endpoint.endswith(marker):
        return endpoint[: -len(marker)]
    return endpoint.rsplit("/audio/transcriptions", 1)[0]


def build_openai_health_url(base_url: str) -> str:
    return f"{build_openai_service_root_url(base_url)}/health"


def normalize_openai_models_base_url(base_url: str) -> str:
    """Normalize the configured OpenAI Base URL before appending ``/models``."""

    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "OpenAI Base URL must not be empty when requesting models.",
        )
    for suffix in ("/audio/transcriptions", "/models"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def build_openai_models_url(base_url: str) -> str:
    return f"{normalize_openai_models_base_url(base_url)}/models"


def build_openai_runtime_progress_url(base_url: str, request_id: str) -> str:
    encoded = urllib.parse.quote(request_id, safe="")
    return f"{build_openai_service_root_url(base_url)}/runtime/progress/{encoded}"


def build_openai_runtime_progress_url_from_template(
    base_url: str, template: str, request_id: str
) -> str:
    encoded = urllib.parse.quote(request_id, safe="")
    rendered = template.replace("{request_id}", encoded)
    if rendered.startswith(("http://", "https://")):
        return rendered
    root = build_openai_service_root_url(base_url)
    return f"{root}/{rendered.lstrip('/')}"


def _stringify_form_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _openai_config_fields(config_fields: Mapping[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for name in sorted(config_fields):
        normalized = str(name).strip().removeprefix("--").replace("-", "_")
        if normalized not in _OPENAI_CONFIG_FIELD_NAMES:
            continue
        value = _stringify_form_value(config_fields[name])
        if value is not None:
            fields.append((normalized, value))
    return fields


def build_openai_form_fields(
    options: WhisperXOptions, config: OpenAIWhisperXRunnerConfig
) -> list[tuple[str, str]]:
    """Build multipart fields for the OpenAI-compatible WhisperX endpoint."""

    normalized = validate_options(
        options,
        WhisperXRunnerConfig(model_dir=None, default_model=config.default_model),
    )
    fields: list[tuple[str, str]] = [
        ("model", normalized.model),
        ("response_format", "srt"),
    ]
    fields.extend(_openai_config_fields(config.config_fields))
    if normalized.language is not None:
        fields.append(("language", normalized.language))
    if normalized.diarize:
        fields.append(("diarize", "true"))
        if normalized.min_speakers is not None:
            fields.append(("min_speakers", str(normalized.min_speakers)))
        if normalized.max_speakers is not None:
            fields.append(("max_speakers", str(normalized.max_speakers)))
    return _dedupe_form_fields(fields)


def _dedupe_form_fields(fields: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep the last configured scalar field while preserving repeated arrays."""

    scalar_positions: dict[str, int] = {}
    result: list[tuple[str, str]] = []
    for name, value in fields:
        previous = scalar_positions.get(name)
        if previous is None:
            scalar_positions[name] = len(result)
            result.append((name, value))
        else:
            result[previous] = (name, value)
    return result


def _runtime_request_id(value: str | None) -> str:
    source = value.strip() if value else uuid.uuid4().hex
    sanitized = "".join(ch if ch.isalnum() or ch in "._:-" else "-" for ch in source)
    sanitized = sanitized.strip(".:-_")
    return (sanitized or uuid.uuid4().hex)[:128]


def _escape_header_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', r"\"")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _normalize_content_type(content_type: str | None) -> str | None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return normalized or None


def _guess_upload_content_type(
    path: Path, content_type: str | None = None
) -> str:
    normalized = _normalize_content_type(content_type)
    if normalized and normalized != "application/octet-stream":
        return normalized
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed:
        return guessed
    return _AUDIO_UPLOAD_CONTENT_TYPES.get(
        path.suffix.lower(), "application/octet-stream"
    )


def _is_audio_upload_path(path: Path, content_type: str | None = None) -> bool:
    normalized = _normalize_content_type(content_type)
    if normalized and normalized.startswith("audio/"):
        return True
    suffix = path.suffix.lower()
    if suffix in _AUDIO_UPLOAD_CONTENT_TYPES:
        return True
    return _guess_upload_content_type(path, normalized).lower().startswith("audio/")


def encode_multipart_form_data(
    fields: Sequence[tuple[str, str]], file_field: tuple[str, str, bytes, str]
) -> tuple[bytes, str]:
    """Encode a small multipart/form-data body using only the stdlib."""

    boundary = f"----media-to-md-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{_escape_header_value(name)}"\r\n\r\n'.encode(
                "utf-8"
            )
        )
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    field_name, filename, content, content_type = file_field
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{_escape_header_value(field_name)}"; '
            f'filename="{_escape_header_value(filename)}"\r\n'
        ).encode("utf-8")
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(content)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _extract_error_message(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return "empty response body"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return text


def extract_openai_model_ids(payload: bytes) -> list[str]:
    """Extract model ids from OpenAI-compatible ``/models`` payloads."""

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    raw_models: Any
    if isinstance(data, Mapping):
        raw_models = data.get("data")
        if raw_models is None:
            raw_models = data.get("models")
    else:
        raw_models = data
    if not isinstance(raw_models, list):
        return []
    models: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, Mapping) else item
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        return int(getcode())
    return 200


def fetch_openai_model_ids(
    base_url: str,
    *,
    api_key: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Fetch model ids from an OpenAI-compatible WhisperX service."""

    models_url = build_openai_models_url(base_url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = urllib.request.Request(models_url, headers=headers, method="GET")
    with urllib.request.urlopen(  # noqa: S310 - configured local/internal endpoint.
        http_request,
        timeout=min(max(float(timeout_seconds), 1.0), 10.0),
    ) as response:
        status = _response_status(response)
        body = response.read()
    if status < 200 or status >= 300:
        raise WhisperXRunnerError(
            WhisperXErrorKind.PROCESS,
            f"OpenAI-compatible /models request failed with HTTP {status}: {_extract_error_message(body)}",
            status,
        )
    return extract_openai_model_ids(body)


def write_openai_response_artifacts(srt_content: str, output_dir: Path) -> None:
    """Write Media-to-MD standard artifacts from an OpenAI SRT response."""

    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "result.srt"
    srt_path.write_text(
        srt_content.rstrip() + ("\n" if srt_content else ""),
        encoding="utf-8",
    )
    write_plain_text_from_srt(srt_path, output_dir / "result.txt")


class OpenAIWhisperXRunner:
    """Async wrapper around a blocking stdlib HTTP multipart request."""

    def __init__(self, config: OpenAIWhisperXRunnerConfig):
        self.config = config

    async def run(
        self,
        request: OpenAIWhisperXRunRequest,
        on_log: LogCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> OpenAIWhisperXRunResult:
        if not self.config.base_url:
            raise WhisperXRunnerError(
                WhisperXErrorKind.VALIDATION,
                "WHISPERX_BACKEND=openai requires whisperx_openai_base_url or WHISPERX_OPENAI_BASE_URL.",
            )
        endpoint = build_openai_transcriptions_url(self.config.base_url)
        fields = build_openai_form_fields(request.options, self.config)
        await self._log(request, on_log, f"POST {endpoint}")
        await self._log(
            request, on_log, f"OpenAI-compatible fields: {_safe_field_summary(fields)}"
        )
        request_id = _runtime_request_id(request.request_id)
        progress = (
            await asyncio.to_thread(
                self._detect_runtime_progress, self.config.base_url, request_id
            )
            if on_log is not None or on_progress is not None
            else None
        )
        extra_headers: dict[str, str] = {}
        if progress is not None:
            header_name = progress.get("header") or "X-Request-ID"
            extra_headers[header_name] = request_id
            await self._log(request, on_log, "WhisperX runtime progress enabled.")
        elif on_progress is not None:
            await _maybe_await(
                on_progress(
                    {
                        "stage": "remote_processing",
                        "stagePercent": None,
                        "message": "OpenAI 兼容服务未提供运行时阶段进度。",
                        "done": False,
                    }
                )
            )

        request.output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="openai-upload.", dir=request.output_dir.parent
        ) as upload_tmp:
            upload_path = await self._prepare_upload_path(
                request, Path(upload_tmp), on_log, on_progress
            )
            upload_content_type = (
                request.input_content_type
                if upload_path == request.input_path
                else None
            )
            post_task = asyncio.create_task(
                asyncio.to_thread(
                    self._post_transcription,
                    endpoint,
                    fields,
                    upload_path,
                    extra_headers,
                    upload_content_type,
                )
            )
            progress_task = (
                asyncio.create_task(
                    self._poll_runtime_progress_until_done(
                        request,
                        on_log,
                        on_progress,
                        progress["url"],
                        post_task,
                    )
                )
                if progress is not None
                else None
            )
            try:
                srt_content = await post_task
            finally:
                if progress_task is not None:
                    await progress_task
        write_openai_response_artifacts(srt_content, request.output_dir)
        await self._log(
            request,
            on_log,
            "OpenAI-compatible response received and artifacts written.",
        )
        return OpenAIWhisperXRunResult(
            argv=("POST", endpoint),
            returncode=0,
            log_path=request.log_path,
            endpoint=endpoint,
            response_text=srt_content,
        )

    async def _prepare_upload_path(
        self,
        request: OpenAIWhisperXRunRequest,
        temp_dir: Path,
        on_log: LogCallback | None,
        on_progress: ProgressCallback | None,
    ) -> Path:
        if not self.config.transcode_to_mp3:
            return request.input_path
        if _is_audio_upload_path(request.input_path, request.input_content_type):
            await self._log(
                request,
                on_log,
                (
                    "Skipping MP3 conversion for audio input before "
                    f"OpenAI-compatible upload: {request.input_path.name}."
                ),
            )
            return request.input_path
        target_path = temp_dir / "remote-upload.mp3"
        if on_progress is not None:
            await _maybe_await(
                on_progress(
                    {
                        "stage": "prepare",
                        "stageKind": "prepare",
                        "stageLabel": "转换为 MP3",
                        "stageDetail": "正在提取音频并压缩为 MP3，以降低远端上传体积。",
                        "stagePercent": None,
                        "message": "正在转换为 MP3。",
                    }
                )
            )
        source_size = request.input_path.stat().st_size
        await self._log(
            request,
            on_log,
            (
                "Converting media to MP3 before OpenAI-compatible upload: "
                f"{request.input_path.name} ({source_size} bytes) -> "
                f"{target_path.name} ({self.config.mp3_bitrate})."
            ),
        )
        await self._transcode_to_mp3(request.input_path, target_path)
        target_size = target_path.stat().st_size
        await self._log(
            request,
            on_log,
            f"MP3 upload payload ready: {target_size} bytes.",
        )
        return target_path

    async def _transcode_to_mp3(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-map_metadata",
            "-1",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            self.config.mp3_bitrate,
            str(output_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                "OpenAI MP3 conversion requires ffmpeg, but ffmpeg was not found.",
            ) from exc
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            message = "OpenAI MP3 conversion failed."
            if detail:
                message = f"{message} {detail}"
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                message,
                process.returncode,
            )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                "OpenAI MP3 conversion produced an empty file.",
            )

    async def _log(
        self,
        request: OpenAIWhisperXRunRequest,
        on_log: LogCallback | None,
        line: str,
    ) -> None:
        request.log_path.parent.mkdir(parents=True, exist_ok=True)
        with request.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(line.rstrip() + "\n")
        if on_log is not None:
            await _maybe_await(on_log(line))

    def _detect_runtime_progress(
        self, base_url: str, request_id: str
    ) -> dict[str, str] | None:
        """Detect whisperx-openai-server's non-OpenAI runtime progress sidecar."""

        health_url = build_openai_health_url(base_url)
        headers = {"Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        http_request = urllib.request.Request(health_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local/internal endpoint.
                http_request, timeout=min(max(float(self.config.timeout_seconds), 1.0), 2.0)
            ) as response:
                status = _response_status(response)
                if status < 200 or status >= 300:
                    return None
                body = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, Mapping) or payload.get("runtime_progress") is not True:
            return None
        protocol = payload.get("runtime_progress_protocol")
        protocol_payload = protocol if isinstance(protocol, Mapping) else {}
        header = (
            protocol_payload.get("request_id_header")
            or protocol_payload.get("runtime_progress_header")
            or payload.get("runtime_progress_header")
        )
        if not isinstance(header, str) or not header.strip():
            header = "X-Request-ID"
        endpoint_template = (
            protocol_payload.get("snapshot_endpoint")
            or protocol_payload.get("runtime_progress_endpoint")
            or payload.get("runtime_progress_endpoint")
        )
        if isinstance(endpoint_template, str) and "{request_id}" in endpoint_template:
            progress_url = build_openai_runtime_progress_url_from_template(
                base_url, endpoint_template, request_id
            )
        else:
            progress_url = build_openai_runtime_progress_url(base_url, request_id)
        return {
            "header": header.strip(),
            "url": progress_url,
        }

    async def _poll_runtime_progress_until_done(
        self,
        request: OpenAIWhisperXRunRequest,
        on_log: LogCallback | None,
        on_progress: ProgressCallback | None,
        progress_url: str,
        post_task: asyncio.Task[str],
    ) -> None:
        last_logged: Mapping[str, Any] | None = None
        while True:
            progress = await asyncio.to_thread(self._get_runtime_progress, progress_url)
            if progress is not None and _should_log_runtime_progress(progress, last_logged):
                await self._log(request, on_log, _format_runtime_progress_line(progress))
                if on_progress is not None:
                    await _maybe_await(on_progress(progress))
                last_logged = progress
            if post_task.done() or (progress is not None and bool(progress.get("done"))):
                return
            await asyncio.wait(
                {post_task},
                timeout=max(float(self.config.progress_poll_interval_seconds), 0.1),
            )

    def _get_runtime_progress(self, progress_url: str) -> Mapping[str, Any] | None:
        headers = {"Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        http_request = urllib.request.Request(progress_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local/internal endpoint.
                http_request, timeout=min(max(float(self.config.timeout_seconds), 1.0), 10.0)
            ) as response:
                status = _response_status(response)
                body = response.read()
        except urllib.error.HTTPError as exc:
            exc.read()
            return None
        except (urllib.error.URLError, TimeoutError):
            return None
        if status < 200 or status >= 300:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, Mapping) else None

    def _post_transcription(
        self,
        endpoint: str,
        fields: Sequence[tuple[str, str]],
        input_path: Path,
        extra_headers: Mapping[str, str] | None = None,
        input_content_type: str | None = None,
    ) -> str:
        content = input_path.read_bytes()
        content_type = _guess_upload_content_type(input_path, input_content_type)
        body, multipart_content_type = encode_multipart_form_data(
            fields, ("file", input_path.name, content, content_type)
        )
        headers = {
            "Accept": "text/plain, application/x-subrip, application/json;q=0.5",
            "Content-Type": multipart_content_type,
        }
        if extra_headers:
            headers.update(extra_headers)
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        http_request = urllib.request.Request(
            endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local/internal endpoint.
                http_request, timeout=self.config.timeout_seconds
            ) as response:
                status = _response_status(response)
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            message = _extract_error_message(exc.read())
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                f"WhisperX OpenAI API request failed with HTTP {exc.code}: {message}",
                exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                f"WhisperX OpenAI API request failed: {reason}",
            ) from exc
        except TimeoutError as exc:
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                "WhisperX OpenAI API request timed out.",
            ) from exc

        if status < 200 or status >= 300:
            raise WhisperXRunnerError(
                WhisperXErrorKind.PROCESS,
                f"WhisperX OpenAI API request failed with HTTP {status}: {_extract_error_message(response_body)}",
                status,
            )
        return response_body.decode("utf-8", errors="replace")


class JobStorageOpenAIWhisperXRunner(OpenAIWhisperXRunner):
    """JobService-compatible OpenAI runner that persists artifacts in JobStorage."""

    def __init__(self, storage, config: OpenAIWhisperXRunnerConfig):
        super().__init__(config)
        self.storage = storage

    @classmethod
    def from_settings(cls, storage, settings) -> "JobStorageOpenAIWhisperXRunner":
        config_fields = dict(getattr(settings, "whisperx_openai_args_config", {}))
        if not config_fields:
            config_fields = dict(getattr(settings, "whisperx_args_config", {}))
        default_model = (
            getattr(settings, "whisperx_model", "small")
            if getattr(settings, "whisperx_backend", "cli") == "openai"
            else getattr(settings, "whisperx_openai_model", None)
            or getattr(settings, "whisperx_model", "small")
        )
        return cls(
            storage,
            OpenAIWhisperXRunnerConfig(
                base_url=getattr(settings, "whisperx_openai_base_url", None),
                api_key=getattr(settings, "whisperx_openai_api_key", None),
                default_model=default_model,
                timeout_seconds=float(
                    getattr(settings, "whisperx_openai_timeout_seconds", 3600.0)
                ),
                transcode_to_mp3=bool(
                    getattr(settings, "whisperx_openai_transcode_to_mp3", True)
                ),
                mp3_bitrate=getattr(settings, "whisperx_openai_mp3_bitrate", "64k"),
                config_fields=config_fields,
                llm_config=llm_config_from_settings(settings, task_type="whisperx"),
            ),
        )

    async def start_job(self, job_id: str) -> None:
        from .models import JobStatus

        manifest = self.storage.update_manifest(
            job_id, status=JobStatus.running, error=None, artifacts=[]
        )
        request = OpenAIWhisperXRunRequest(
            input_path=self.storage.resolve_job_relative(
                job_id, f"input/{manifest.input_filename}"
            ),
            output_dir=self.storage.job_dir(job_id) / "output",
            log_path=self.storage.resolve_job_relative(job_id, manifest.log_path),
            options=options_from_job_options(manifest.options),
            request_id=job_id,
            input_content_type=manifest.input_content_type,
        )

        async def record_log_event(line: str) -> None:
            clean = line.strip()
            if clean:
                self.storage.append_event(
                    job_id, "log", clean, status=JobStatus.running
                )

        try:
            self.storage.append_event(
                job_id,
                "system",
                "开始调用 WhisperX OpenAI 兼容服务。",
                status=JobStatus.running,
            )

            async def record_progress_event(progress: Mapping[str, Any]) -> None:
                append_progress_event(
                    self.storage,
                    job_id,
                    phase_from_openai_progress(progress, manifest.options),
                    JobStatus.running,
                )

            append_progress_event(
                self.storage,
                job_id,
                runtime_phase("starting", manifest.options, source="openai"),
                JobStatus.running,
            )
            await self.run(
                request, on_log=record_log_event, on_progress=record_progress_event
            )
            derive_plain_text_from_srt_outputs(request.output_dir)
        except WhisperXRunnerError as exc:
            append_progress_event(
                self.storage,
                job_id,
                runtime_phase(
                    "failed", manifest.options, detail=exc.message, source="openai"
                ),
                JobStatus.failed,
            )
            self.storage.append_log(job_id, exc.message)
            self.storage.update_manifest(
                job_id, status=JobStatus.failed, error=exc.message
            )
            return
        except (
            Exception
        ) as exc:  # pragma: no cover - defensive background-task boundary
            message = f"WhisperX OpenAI runner failed unexpectedly: {exc}"
            append_progress_event(
                self.storage,
                job_id,
                runtime_phase(
                    "failed", manifest.options, detail=message, source="openai"
                ),
                JobStatus.failed,
            )
            self.storage.append_log(job_id, message)
            self.storage.update_manifest(job_id, status=JobStatus.failed, error=message)
            return

        append_progress_event(
            self.storage,
            job_id,
            runtime_phase("finalize", manifest.options, source="openai"),
            JobStatus.running,
        )
        if getattr(manifest.options, "llm_polish", False):
            self.storage.append_event(
                job_id,
                "system",
                "开始执行 LLM 润色。",
                status=JobStatus.running,
            )
            append_progress_event(
                self.storage,
                job_id,
                runtime_phase("llm_polish", manifest.options, source="llm"),
                JobStatus.running,
            )
            await self._run_llm_polish(job_id, task_type="whisperx")
        public_formats = set(request.options.output_formats)
        if getattr(manifest.options, "llm_polish", False):
            public_formats.add("markdown_llm")
        artifacts = [
            artifact
            for artifact in self.storage.discover_output_artifacts(job_id)
            if artifact.format in public_formats
        ]
        self.storage.update_manifest(
            job_id, status=JobStatus.succeeded, error=None, artifacts=artifacts
        )
        append_progress_event(
            self.storage,
            job_id,
            runtime_phase(
                "succeeded", manifest.options, source="openai", stage_percent=100.0
            ),
            JobStatus.succeeded,
        )

    async def enqueue(self, job_id: str) -> None:
        await self.start_job(job_id)

    async def start(self, job_id: str) -> None:
        await self.start_job(job_id)

    async def _run_llm_polish(self, job_id: str, *, task_type: str) -> None:
        from .models import JobStatus

        try:
            result = await asyncio.to_thread(
                polish_job_outputs,
                self.storage,
                job_id,
                task_type=task_type,
                config=self.config.llm_config,
            )
        except Exception as exc:
            message = f"LLM 润色失败：{exc}"
            self.storage.append_log(job_id, message)
            self.storage.append_event(job_id, "error", message, status=JobStatus.running)
            return
        if result.skipped_reason:
            self.storage.append_event(
                job_id,
                "system",
                result.skipped_reason,
                status=JobStatus.running,
            )
            return
        self.storage.append_event(
            job_id,
            "system",
            "已生成 LLM 润色版 Markdown。",
            status=JobStatus.running,
            data={
                "source": result.source_path.name if result.source_path else None,
                "files_created": [path.name for path in result.created_paths],
            },
        )


def _safe_field_summary(fields: Sequence[tuple[str, str]]) -> str:
    return json.dumps(
        {name: value for name, value in fields}, ensure_ascii=False, sort_keys=True
    )


def _runtime_progress_stage_percent(progress: Mapping[str, Any]) -> float | None:
    raw = progress.get("stagePercent")
    if raw is None:
        raw = progress.get("stage_percent")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _format_runtime_progress_line(progress: Mapping[str, Any]) -> str:
    stage = str(progress.get("stage") or "processing")
    message = str(progress.get("message") or "").strip()
    stage_percent = _runtime_progress_stage_percent(progress)
    if stage_percent is None:
        prefix = f"WhisperX 进度: {stage}"
    else:
        prefix = f"WhisperX 阶段进度: {stage_percent:.1f}% · {stage}"
    return f"{prefix} · {message}" if message else prefix


def _should_log_runtime_progress(
    progress: Mapping[str, Any], last_logged: Mapping[str, Any] | None
) -> bool:
    if last_logged is None:
        return True
    if progress.get("done") or progress.get("error"):
        return True
    if progress.get("stage") != last_logged.get("stage"):
        return True
    current_stage_percent = _runtime_progress_stage_percent(progress)
    previous_stage_percent = _runtime_progress_stage_percent(last_logged)
    if current_stage_percent is None or previous_stage_percent is None:
        return False
    return current_stage_percent - previous_stage_percent >= 5.0
