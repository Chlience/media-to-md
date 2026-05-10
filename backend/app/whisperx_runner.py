"""Controlled WhisperX runner primitives for the local web frontend backend.

The runner lane owns subprocess safety and the direct WhisperX CLI invocation.
Backend API/storage code should call ``build_whisperx_argv`` or
``WhisperXRunner.run`` rather than constructing WhisperX commands directly.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable, Mapping

WHISPERX_COMMAND = "whisperx"
REQUIRED_OUTPUT_FORMATS: tuple[str, ...] = ("txt", "srt", "vtt", "json")
ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large-v3-turbo",
    }
)
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class WhisperXErrorKind(StrEnum):
    """Stable high-level error buckets for API/user-visible failures."""

    MODEL_CACHE = "model_cache"
    DIARIZATION = "diarization"
    PROCESS = "process"
    VALIDATION = "validation"


class WhisperXRunnerError(RuntimeError):
    """Raised when WhisperX cannot run or exits unsuccessfully."""

    def __init__(
        self, kind: WhisperXErrorKind, message: str, returncode: int | None = None
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.returncode = returncode


@dataclass(frozen=True)
class WhisperXOptions:
    """Validated command options accepted from the API layer."""

    model: str = "small"
    language: str | None = None
    diarize: bool = False
    min_speakers: int | None = None
    max_speakers: int | None = None
    model_cache_only: bool = False
    output_formats: tuple[str, ...] = REQUIRED_OUTPUT_FORMATS
    extra_args: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WhisperXRunnerConfig:
    """Runtime configuration supplied by backend config/env."""

    model_dir: Path | None
    default_model: str = "small"
    nltk_data_dir: Path | None = None
    command: str = WHISPERX_COMMAND
    allowed_models: tuple[str, ...] = field(default_factory=tuple)
    config_args: tuple[str, ...] = field(default_factory=tuple)
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WhisperXRunRequest:
    input_path: Path
    output_dir: Path
    log_path: Path
    options: WhisperXOptions


@dataclass(frozen=True)
class WhisperXRunResult:
    argv: tuple[str, ...]
    returncode: int
    log_path: Path


LogCallback = Callable[[str], Awaitable[None] | None]


def _safe_model_value(value: str) -> bool:
    return bool(value.strip()) and not any(
        char in value for char in ("\x00", "\n", "\r")
    )


def validate_options(
    options: WhisperXOptions, config: WhisperXRunnerConfig | None = None
) -> WhisperXOptions:
    """Return normalized options or raise a validation error."""

    model = options.model.strip()
    extra_allowed = set(config.allowed_models if config is not None else ())
    if config is not None:
        extra_allowed.add(config.default_model)
    if not _safe_model_value(model) or (
        model not in ALLOWED_MODELS and model not in extra_allowed
    ):
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            f"Unsupported WhisperX model '{options.model}'.",
        )

    language = options.language
    if language in ("", "auto"):
        language = None
    if language is not None and not _LANGUAGE_RE.fullmatch(language):
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            f"Unsupported WhisperX language value '{options.language}'. Use 'auto' or an ISO-like code.",
        )

    invalid_formats = set(options.output_formats) - set(REQUIRED_OUTPUT_FORMATS)
    if invalid_formats:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            f"Unsupported output format(s): {', '.join(sorted(invalid_formats))}.",
        )

    if options.extra_args:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "Raw extra WhisperX arguments are disabled for subprocess safety.",
        )

    try:
        min_speakers = (
            int(options.min_speakers) if options.min_speakers is not None else None
        )
        max_speakers = (
            int(options.max_speakers) if options.max_speakers is not None else None
        )
    except (TypeError, ValueError) as exc:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "WhisperX speaker counts must be integers.",
        ) from exc
    if min_speakers is not None and min_speakers < 1:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "WhisperX min_speakers must be >= 1.",
        )
    if max_speakers is not None and max_speakers < 1:
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "WhisperX max_speakers must be >= 1.",
        )
    if (
        min_speakers is not None
        and max_speakers is not None
        and min_speakers > max_speakers
    ):
        raise WhisperXRunnerError(
            WhisperXErrorKind.VALIDATION,
            "WhisperX min_speakers must be <= max_speakers.",
        )

    return WhisperXOptions(
        model=model,
        language=language,
        diarize=bool(options.diarize),
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        model_cache_only=bool(options.model_cache_only),
        output_formats=tuple(options.output_formats),
        extra_args=(),
    )


def build_runner_env(config: WhisperXRunnerConfig) -> dict[str, str]:
    """Build subprocess env with model/cache paths when configured."""

    env = os.environ.copy()
    env.update(config.env)
    if config.model_dir is not None:
        env["WHISPERX_MODEL_DIR"] = str(config.model_dir)
    if config.nltk_data_dir is not None:
        env["NLTK_DATA"] = str(config.nltk_data_dir)
    elif config.model_dir is not None:
        env.setdefault("NLTK_DATA", str(config.model_dir / "nltk_data"))
    return env


def build_whisperx_argv(
    input_path: Path,
    output_dir: Path,
    options: WhisperXOptions,
    config: WhisperXRunnerConfig,
) -> list[str]:
    """Build the direct WhisperX argv list.

    Returns a list suitable for ``asyncio.create_subprocess_exec(*argv)``.
    It intentionally never returns a shell string and never requires shell execution.
    """

    normalized = validate_options(options, config)
    argv = [
        config.command,
        str(input_path),
        "--model",
        normalized.model,
        "--output_dir",
        str(output_dir),
        "--output_format",
        "all",
    ]
    if normalized.language is not None:
        argv.extend(["--language", normalized.language])
    if normalized.diarize:
        argv.append("--diarize")
    if config.model_dir is not None:
        argv.extend(["--model_dir", str(config.model_dir)])
    if normalized.model_cache_only:
        argv.extend(["--model_cache_only", "True"])
    argv.extend(config.config_args)
    if normalized.diarize:
        if normalized.min_speakers is not None:
            argv.extend(["--min_speakers", str(normalized.min_speakers)])
        if normalized.max_speakers is not None:
            argv.extend(["--max_speakers", str(normalized.max_speakers)])
    return argv


def map_whisperx_error(
    output: str, returncode: int | None = None
) -> WhisperXRunnerError:
    """Map raw WhisperX output to readable API error buckets."""

    text = output.lower()
    if any(
        token in text
        for token in (
            "model_cache_only",
            "cache",
            "model_dir",
            "no such file",
            "not found",
        )
    ):
        return WhisperXRunnerError(
            WhisperXErrorKind.MODEL_CACHE,
            "WhisperX model/cache error. Check WHISPERX_MODEL_DIR, local model files, and model_cache_only settings.",
            returncode,
        )
    if any(
        token in text
        for token in ("diariz", "hf_token", "hugging face", "pyannote", "terms")
    ):
        return WhisperXRunnerError(
            WhisperXErrorKind.DIARIZATION,
            "WhisperX diarization error. Check local diarization cache, Hugging Face token, and model terms access.",
            returncode,
        )
    return WhisperXRunnerError(
        WhisperXErrorKind.PROCESS,
        f"WhisperX subprocess failed with exit code {returncode}.",
        returncode,
    )


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


class WhisperXRunner:
    """Small controlled async subprocess runner for WhisperX jobs."""

    def __init__(self, config: WhisperXRunnerConfig):
        self.config = config

    async def run(
        self, request: WhisperXRunRequest, on_log: LogCallback | None = None
    ) -> WhisperXRunResult:
        argv = build_whisperx_argv(
            request.input_path, request.output_dir, request.options, self.config
        )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.log_path.parent.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=build_runner_env(self.config),
        )

        lines: list[str] = []
        with request.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"$ {' '.join(argv)}\n")
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                lines.append(line)
                log_file.write(line)
                log_file.flush()
                if on_log is not None:
                    await _maybe_await(on_log(line))

        returncode = await process.wait()
        if returncode != 0:
            raise map_whisperx_error("".join(lines), returncode)
        return WhisperXRunResult(tuple(argv), returncode, request.log_path)


def options_from_job_options(job_options) -> WhisperXOptions:
    """Convert backend manifest/API JobOptions into runner options.

    The backend owns validation of the public request model; the runner still
    normalizes and rejects unsafe values before command construction.
    """

    language = getattr(job_options, "language", None)
    output_formats = tuple(
        getattr(job_options, "output_formats", REQUIRED_OUTPUT_FORMATS)
    )
    return WhisperXOptions(
        model=getattr(job_options, "model", "small"),
        language=language,
        diarize=bool(getattr(job_options, "diarize", False)),
        min_speakers=getattr(job_options, "min_speakers", None),
        max_speakers=getattr(job_options, "max_speakers", None),
        model_cache_only=bool(getattr(job_options, "model_cache_only", False)),
        output_formats=output_formats,
    )


class JobStorageWhisperXRunner(WhisperXRunner):
    """JobService-compatible runner that persists through JobStorage.

    ``app.jobs.JobService`` looks for ``start_job(job_id)`` (or enqueue/start
    fallbacks).  This adapter keeps storage/manifest mutation in one place while
    reusing the safe argv-only subprocess runner above.
    """

    def __init__(self, storage, config: WhisperXRunnerConfig):
        super().__init__(config)
        self.storage = storage

    @classmethod
    def from_settings(cls, storage, settings) -> "JobStorageWhisperXRunner":
        model_dir = getattr(settings, "whisperx_model_dir", None)
        nltk_data_dir = getattr(settings, "nltk_data_dir", None)
        config_args = tuple(getattr(settings, "whisperx_cli_args", ()))
        if not config_args:
            config_args = tuple(getattr(settings, "whisperx_args", ()))
        default_model = (
            getattr(settings, "whisperx_model", "small")
            if getattr(settings, "whisperx_backend", "cli") == "cli"
            else getattr(settings, "whisperx_cli_model", None)
            or getattr(settings, "whisperx_model", "small")
        )
        return cls(
            storage,
            WhisperXRunnerConfig(
                model_dir=Path(model_dir) if model_dir else None,
                default_model=default_model,
                nltk_data_dir=Path(nltk_data_dir) if nltk_data_dir else None,
                config_args=config_args,
            ),
        )

    async def start_job(self, job_id: str) -> None:
        from .models import JobStatus

        manifest = self.storage.update_manifest(
            job_id, status=JobStatus.running, error=None, artifacts=[]
        )
        request = WhisperXRunRequest(
            input_path=self.storage.resolve_job_relative(
                job_id, f"input/{manifest.input_filename}"
            ),
            output_dir=self.storage.job_dir(job_id) / "output",
            log_path=self.storage.resolve_job_relative(job_id, manifest.log_path),
            options=options_from_job_options(manifest.options),
        )

        async def record_log_event(line: str) -> None:
            clean = line.strip()
            if clean:
                self.storage.append_event(
                    job_id, "log", clean, status=JobStatus.running
                )

        try:
            self.storage.append_event(
                job_id, "system", "开始执行 WhisperX 子进程。", status=JobStatus.running
            )
            await self.run(request, on_log=record_log_event)
        except WhisperXRunnerError as exc:
            self.storage.append_log(job_id, exc.message)
            self.storage.update_manifest(
                job_id, status=JobStatus.failed, error=exc.message
            )
            return
        except (
            Exception
        ) as exc:  # pragma: no cover - defensive background-task boundary
            message = f"WhisperX runner failed unexpectedly: {exc}"
            self.storage.append_log(job_id, message)
            self.storage.update_manifest(job_id, status=JobStatus.failed, error=message)
            return

        public_formats = set(request.options.output_formats)
        artifacts = [
            artifact
            for artifact in self.storage.discover_output_artifacts(job_id)
            if artifact.format in public_formats
        ]
        self.storage.update_manifest(
            job_id, status=JobStatus.succeeded, error=None, artifacts=artifacts
        )

    async def enqueue(self, job_id: str) -> None:
        await self.start_job(job_id)

    async def start(self, job_id: str) -> None:
        await self.start_job(job_id)
