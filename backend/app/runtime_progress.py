"""Runtime progress normalization for media transcription jobs.

The backend exposes one progress shape to the UI regardless of whether a
WhisperX job is driven by the local CLI or by an OpenAI-compatible service.
Runners report source-specific signals; this module converts them into the
canonical ``RuntimePhase`` model used by status responses and admin events.
"""

from __future__ import annotations

from typing import Any, Mapping

from .models import JobManifest, JobStatus, RuntimePhase, WhisperXJobOptions

WHISPERX_PROCESS = "whisperx"

_PHASE_LABELS: dict[str, tuple[str, str]] = {
    "queued": ("等待启动", "任务已创建，等待后端启动转写。"),
    "starting": ("启动转写任务", "后端已接收任务，正在启动本地 CLI 或 OpenAI 兼容调用。"),
    "prepare": ("准备音频与模型", "正在准备音频、模型、缓存和运行参数。"),
    "remote_processing": ("远端处理中", "OpenAI 兼容服务正在处理；当前服务未提供运行时阶段进度。"),
    "transcribe": ("语音转文字", "正在把音频内容转写为文本。"),
    "align": ("时间戳对齐", "正在对齐词级/片段级时间戳并整理字幕。"),
    "diarize": ("说话人分离", "正在为片段和词级结果分配说话人标签。"),
    "finalize": ("整理输出文件", "转写已完成，正在写入并收集可下载产物。"),
    "succeeded": ("已完成", "任务已成功完成，可下载输出文件。"),
    "failed": ("失败", "任务失败，请进入管理员页面查看错误详情和日志。"),
    "cancelled": ("已取消", "任务已取消。"),
}

_WHISPERX_STAGE_ALIASES: dict[str, str] = {
    "received": "starting",
    "load_model": "prepare",
    "decode": "prepare",
    "model": "prepare",
    "vad": "prepare",
    "transcription": "transcribe",
    "aligning": "align",
    "alignment": "align",
    "diarization": "diarize",
    "complete": "finalize",
}


def normalize_whisperx_stage(stage: str | None) -> str:
    code = str(stage or "").strip().lower().replace("-", "_")
    if not code:
        return "starting"
    return _WHISPERX_STAGE_ALIASES.get(code, code)


def runtime_phase(
    code: str,
    options: WhisperXJobOptions,
    *,
    detail: str | None = None,
    source: str | None = None,
    stage_percent: float | None = None,
    updated_at: str | None = None,
) -> RuntimePhase:
    normalized = normalize_whisperx_stage(code)
    if normalized not in _PHASE_LABELS:
        normalized = "remote_processing" if source == "openai" else "starting"
    label, default_detail = _PHASE_LABELS[normalized]
    stage_percent = _clamp_stage_percent(stage_percent)
    return RuntimePhase(
        process=WHISPERX_PROCESS,
        code=normalized,
        label=label,
        detail=(detail or "").strip() or default_detail,
        stage_percent=stage_percent,
        source=source,
        updated_at=updated_at,
    )


def phase_from_openai_progress(
    progress: Mapping[str, Any],
    options: WhisperXJobOptions,
) -> RuntimePhase:
    stage = (
        _string_or_none(progress.get("stageKind"))
        or _string_or_none(progress.get("stage_kind"))
        or _string_or_none(progress.get("stage"))
        or _string_or_none(progress.get("status"))
        or "remote_processing"
    )
    status = _string_or_none(progress.get("status"))
    if progress.get("error") or status == "failed":
        stage = "failed"
    label = _string_or_none(progress.get("stageLabel")) or _string_or_none(
        progress.get("stage_label")
    )
    detail = (
        _string_or_none(progress.get("stageDetail"))
        or _string_or_none(progress.get("stage_detail"))
        or _string_or_none(progress.get("message"))
    )
    if label:
        return _remote_labeled_runtime_phase(
            stage,
            label,
            options,
            detail=detail,
            stage_percent=_progress_stage_percent(progress),
            updated_at=_progress_updated_at(progress),
        )
    return runtime_phase(
        stage,
        options,
        detail=detail,
        source="openai",
        stage_percent=_progress_stage_percent(progress),
        updated_at=_progress_updated_at(progress),
    )


def phase_from_cli_log(line: str, options: WhisperXJobOptions) -> RuntimePhase | None:
    text = line.strip()
    if not text:
        return None
    lower = text.lower()
    if lower.startswith("$ "):
        return runtime_phase("starting", options, source="cli")
    if "performing diarization" in lower:
        return runtime_phase("diarize", options, detail=text, source="cli")
    if "performing alignment" in lower:
        return runtime_phase("align", options, detail=text, source="cli")
    if (
        "transcript: [" in lower
        or "detected language:" in lower
        or "performing transcription" in lower
    ):
        return runtime_phase("transcribe", options, detail=text, source="cli")
    if (
        "performing voice activity detection" in lower
        or "compute type" in lower
        or "no language specified" in lower
    ):
        return runtime_phase("prepare", options, detail=text, source="cli")
    return None


def phase_from_progress_event(
    event_data: Mapping[str, Any],
    options: WhisperXJobOptions,
) -> RuntimePhase | None:
    code = _string_or_none(event_data.get("code"))
    if not code:
        return None
    return runtime_phase(
        code,
        options,
        detail=_string_or_none(event_data.get("detail")),
        source=_string_or_none(event_data.get("source")),
        stage_percent=_progress_stage_percent(event_data),
        updated_at=_string_or_none(event_data.get("updated_at")),
    )


def append_progress_event(storage, job_id: str, phase: RuntimePhase, status: JobStatus) -> None:
    """Persist a progress event unless it duplicates the latest progress state."""

    last = latest_progress_phase(storage, job_id)
    if (
        last is not None
        and last.code == phase.code
        and last.stage_percent == phase.stage_percent
        and last.detail == phase.detail
    ):
        return
    storage.append_event(
        job_id,
        "progress",
        _progress_message(phase),
        status=status,
        data=phase.model_dump(mode="json"),
    )


def latest_progress_phase(storage, job_id: str) -> RuntimePhase | None:
    try:
        manifest = storage.read_manifest(job_id)
    except Exception:
        return None
    if manifest.options.task_type != "whisperx":
        return None
    for event in reversed(storage.read_events(job_id, 2000)):
        if event.type != "progress":
            continue
        phase = phase_from_progress_event(event.data, manifest.options)
        if phase is not None:
            return phase.model_copy(update={"updated_at": event.timestamp})
    return None


def whisperx_runtime_phase(
    manifest: JobManifest, storage
) -> RuntimePhase | None:
    if manifest.options.task_type != "whisperx":
        return None
    if manifest.status == JobStatus.queued:
        return runtime_phase("queued", manifest.options, source="system")
    if manifest.status == JobStatus.succeeded:
        return runtime_phase(
            "succeeded", manifest.options, source="system", stage_percent=100.0
        )
    if manifest.status == JobStatus.failed:
        return runtime_phase("failed", manifest.options, source="system")
    if manifest.status == JobStatus.cancelled:
        return runtime_phase("cancelled", manifest.options, source="system")

    latest = latest_progress_phase(storage, manifest.job_id)
    if latest is not None:
        return latest

    log_phase = _phase_from_legacy_log(manifest, storage)
    if log_phase is not None:
        return log_phase
    return runtime_phase("starting", manifest.options, source="system")


def _phase_from_legacy_log(manifest: JobManifest, storage) -> RuntimePhase | None:
    log = storage.read_log(manifest.job_id).lower()
    if "performing diarization" in log:
        return runtime_phase("diarize", manifest.options, source="cli")
    if "performing alignment" in log:
        return runtime_phase("align", manifest.options, source="cli")
    if (
        "transcript: [" in log
        or "detected language:" in log
        or "performing transcription" in log
    ):
        return runtime_phase("transcribe", manifest.options, source="cli")
    if (
        "performing voice activity detection" in log
        or "compute type" in log
        or "no language specified" in log
    ):
        return runtime_phase("prepare", manifest.options, source="cli")
    if log.strip():
        return runtime_phase("starting", manifest.options, source="cli")
    return None


def _progress_message(phase: RuntimePhase) -> str:
    percent = (
        f"阶段 {phase.stage_percent:.1f}%"
        if phase.stage_percent is not None
        else "进行中"
    )
    return f"{phase.label} · {percent}"


def _progress_stage_percent(data: Mapping[str, Any]) -> float | None:
    raw = data.get("stagePercent")
    if raw is None:
        raw = data.get("stage_percent")
    return _clamp_stage_percent(raw)


def _progress_updated_at(data: Mapping[str, Any]) -> str | None:
    return _string_or_none(data.get("updatedAt")) or _string_or_none(data.get("updated_at"))


def _remote_labeled_runtime_phase(
    code: str,
    label: str,
    options: WhisperXJobOptions,
    *,
    detail: str | None = None,
    stage_percent: float | None = None,
    updated_at: str | None = None,
) -> RuntimePhase:
    normalized = normalize_whisperx_stage(code)
    if normalized in _PHASE_LABELS:
        code = normalized
    else:
        code = normalized or "remote_processing"
    return RuntimePhase(
        process=WHISPERX_PROCESS,
        code=code,
        label=label,
        detail=(detail or "").strip() or label,
        stage_percent=_clamp_stage_percent(stage_percent),
        source="openai",
        updated_at=updated_at,
    )


def _clamp_stage_percent(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        number = 0.0
    if number > 100:
        number = 100.0
    return round(number, 2)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
