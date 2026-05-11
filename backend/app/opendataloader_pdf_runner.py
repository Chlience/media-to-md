"""Controlled OpenDataLoader PDF runner primitives.

PDF jobs are executed with an argv-only direct ``opendataloader-pdf`` invocation so
the API never constructs shell strings for user uploads.  This module
intentionally mirrors the WhisperX runner adapter shape used by ``JobService``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from .llm_polish import (
    LlmPolishConfig,
    llm_config_from_settings,
    polish_job_outputs,
)
from .opendataloader_pdf_postprocess import (
    postprocess_opendataloader_markdown_outputs,
)

OPENDATALOADER_PDF_COMMAND = "opendataloader-pdf"
PDF_OUTPUT_FORMATS = "markdown,text"
PDF_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset(
    {"json", "txt", "html", "pdf", "md", "markdown", "png", "jpeg", "jpg"}
)
REMOVED_MANAGED_ARG_FLAGS: frozenset[str] = frozenset(
    {
        "-o",
        "--output-dir",
        "--output_dir",
        "--to-stdout",
        "--content-safety-off",
        "--password",
        "--image-dir",
        "--hybrid-url",
        "--sanitize",
        "--keep-line-breaks",
        "--replace-invalid-chars",
        "--use-struct-tree",
        "--markdown-page-separator",
        "--text-page-separator",
        "--html-page-separator",
        "--include-header-footer",
        "--detect-strikethrough",
        "--hybrid-fallback",
        "--hybrid-hancom-ai-regionlist-strategy",
        "--hybrid-hancom-ai-ocr-strategy",
        "--hybrid-hancom-ai-image-cache",
    }
)


class OpenDataLoaderPdfErrorKind(StrEnum):
    JAVA = "java"
    OPENDATALOADER = "opendataloader"
    PROCESS = "process"


class OpenDataLoaderPdfRunnerError(RuntimeError):
    def __init__(
        self,
        kind: OpenDataLoaderPdfErrorKind,
        message: str,
        returncode: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.returncode = returncode


@dataclass(frozen=True)
class OpenDataLoaderPdfRunnerConfig:
    command: str = OPENDATALOADER_PDF_COMMAND
    extra_args: tuple[str, ...] = field(
        default_factory=lambda: ("-f", PDF_OUTPUT_FORMATS, "--image-output", "off")
    )
    env: Mapping[str, str] = field(default_factory=dict)
    llm_config: LlmPolishConfig = field(default_factory=LlmPolishConfig)


@dataclass(frozen=True)
class OpenDataLoaderPdfRunRequest:
    input_path: Path
    output_dir: Path
    log_path: Path


@dataclass(frozen=True)
class OpenDataLoaderPdfRunResult:
    argv: tuple[str, ...]
    returncode: int
    log_path: Path


LogCallback = Callable[[str], Awaitable[None] | None]


def build_opendataloader_pdf_argv(
    input_path: Path,
    output_dir: Path,
    config: OpenDataLoaderPdfRunnerConfig | None = None,
) -> list[str]:
    """Build the direct OpenDataLoader PDF argv list; never a shell string."""

    config = config or OpenDataLoaderPdfRunnerConfig()
    extra_args = tuple(config.extra_args)
    _reject_removed_managed_args(extra_args)
    extra_args = _ensure_json_format_for_markdown_postprocess(extra_args)
    argv = [config.command, str(input_path)]
    argv.extend(["-o", str(output_dir)])
    argv.extend(extra_args)
    return argv


def _reject_removed_managed_args(extra_args: tuple[str, ...]) -> None:
    for arg in extra_args:
        flag = arg.split("=", 1)[0]
        if flag in REMOVED_MANAGED_ARG_FLAGS:
            raise ValueError(
                f"OpenDataLoader PDF option '{flag}' is not supported by the managed backend runner"
            )


def _ensure_json_format_for_markdown_postprocess(
    extra_args: tuple[str, ...],
) -> tuple[str, ...]:
    """Add JSON output when Markdown is requested into the managed job output.

    The image-text filter needs OpenDataLoader's coordinate-rich JSON.  This is
    intentionally argv-local so the persisted admin config remains exactly what
    the operator chose.
    """

    rewritten = list(extra_args)
    for index, arg in enumerate(rewritten):
        if arg in {"-f", "--format"} and index + 1 < len(rewritten):
            rewritten[index + 1] = _format_csv_with_json_if_markdown(
                rewritten[index + 1]
            )
            return tuple(rewritten)
        if arg.startswith("--format="):
            rewritten[index] = "--format=" + _format_csv_with_json_if_markdown(
                arg.split("=", 1)[1]
            )
            return tuple(rewritten)
    return extra_args


def _format_csv_with_json_if_markdown(value: str) -> str:
    formats = [item.strip() for item in value.split(",") if item.strip()]
    normalized = {item.lower() for item in formats}
    wants_markdown = bool(
        normalized & {"markdown", "md", "markdown-with-html", "markdown-with-images"}
    )
    if not wants_markdown or "json" in normalized:
        return value
    return ",".join(["json", *formats])


def readable_pdf_runtime_error(exc: BaseException) -> str:
    """Return an operator-facing PDF runtime error message."""

    text = str(exc)
    if _looks_like_missing_java(text):
        return (
            "OpenDataLoader PDF requires Java. Install a JRE/JDK and ensure "
            "the java executable is on PATH."
        )
    if isinstance(exc, FileNotFoundError) or _looks_like_missing_opendataloader(text):
        return (
            "OpenDataLoader PDF failed to start. Ensure the opendataloader-pdf "
            "executable is installed and on PATH."
        )
    return f"OpenDataLoader PDF subprocess failed: {text}"


format_pdf_runtime_error = readable_pdf_runtime_error


def build_runner_env(config: OpenDataLoaderPdfRunnerConfig) -> dict[str, str]:
    env = os.environ.copy()
    env.update(config.env)
    return env


def _looks_like_missing_java(output: str) -> bool:
    text = output.lower()
    missing_markers = (
        "java: command not found",
        "java executable missing",
        "java executable not found",
        "no java executable",
        "could not find java",
        "unable to locate a java runtime",
        "no java runtime present",
        "cannot find java",
        "jre not found",
        "jdk not found",
    )
    return any(marker in text for marker in missing_markers)


def _looks_like_missing_opendataloader(output: str) -> bool:
    text = output.lower()
    missing_markers = (
        "no module named",
        "opendataloader-pdf: command not found",
        "opendataloader: command not found",
        "open data loader: command not found",
    )
    return any(marker in text for marker in missing_markers)


def _compact_process_output(output: str, limit: int = 1200) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def map_opendataloader_pdf_error(
    output: str, returncode: int | None = None
) -> OpenDataLoaderPdfRunnerError:
    if _looks_like_missing_java(output):
        return OpenDataLoaderPdfRunnerError(
            OpenDataLoaderPdfErrorKind.JAVA,
            "OpenDataLoader PDF requires Java. Install a JRE/JDK and ensure the java executable is on PATH.",
            returncode,
        )
    if _looks_like_missing_opendataloader(output):
        return OpenDataLoaderPdfRunnerError(
            OpenDataLoaderPdfErrorKind.OPENDATALOADER,
            "OpenDataLoader PDF failed to start. Ensure the opendataloader-pdf executable is installed and on PATH.",
            returncode,
        )
    details = _compact_process_output(output)
    suffix = f" Details: {details}" if details else ""
    return OpenDataLoaderPdfRunnerError(
        OpenDataLoaderPdfErrorKind.PROCESS,
        f"OpenDataLoader PDF subprocess failed with exit code {returncode}.{suffix}",
        returncode,
    )


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


class OpenDataLoaderPdfRunner:
    def __init__(self, config: OpenDataLoaderPdfRunnerConfig | None = None):
        self.config = config or OpenDataLoaderPdfRunnerConfig()

    async def run(
        self, request: OpenDataLoaderPdfRunRequest, on_log: LogCallback | None = None
    ) -> OpenDataLoaderPdfRunResult:
        argv = build_opendataloader_pdf_argv(
            request.input_path, request.output_dir, self.config
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
            raise map_opendataloader_pdf_error("".join(lines), returncode)
        return OpenDataLoaderPdfRunResult(tuple(argv), returncode, request.log_path)


class JobStorageOpenDataLoaderPdfRunner(OpenDataLoaderPdfRunner):
    def __init__(self, storage, config: OpenDataLoaderPdfRunnerConfig | None = None):
        super().__init__(config)
        self.storage = storage

    @classmethod
    def from_settings(cls, storage, settings) -> "JobStorageOpenDataLoaderPdfRunner":
        return cls(
            storage,
            OpenDataLoaderPdfRunnerConfig(
                extra_args=tuple(
                    getattr(
                        settings,
                        "opendataloader_pdf_args",
                        ("-f", PDF_OUTPUT_FORMATS, "--image-output", "off"),
                    )
                ),
                llm_config=llm_config_from_settings(settings, task_type="pdf"),
            ),
        )

    async def start_job(self, job_id: str) -> None:
        from .models import JobStatus

        manifest = self.storage.update_manifest(
            job_id, status=JobStatus.running, error=None, artifacts=[]
        )
        request = OpenDataLoaderPdfRunRequest(
            input_path=self.storage.resolve_job_relative(
                job_id, f"input/{manifest.input_filename}"
            ),
            output_dir=self.storage.job_dir(job_id) / "output",
            log_path=self.storage.resolve_job_relative(job_id, manifest.log_path),
        )

        async def record_log_event(line: str) -> None:
            clean = line.strip()
            if clean:
                self.storage.append_event(job_id, "log", clean, status=JobStatus.running)

        try:
            self.storage.append_event(
                job_id,
                "system",
                "开始执行 OpenDataLoader PDF 子进程。",
                status=JobStatus.running,
            )
            await self.run(request, on_log=record_log_event)
            cleanup_strength = getattr(
                manifest.options, "markdown_cleanup_strength", "balanced"
            )
            if cleanup_strength == "off":
                self.storage.append_event(
                    job_id,
                    "system",
                    "已关闭 markdown_clear 清洗版生成。",
                    status=JobStatus.running,
                )
            else:
                postprocess_result = postprocess_opendataloader_markdown_outputs(
                    request.output_dir,
                    cleanup_strength=cleanup_strength,
                )
                if postprocess_result.changed:
                    self.storage.append_event(
                        job_id,
                        "system",
                        (
                            "已根据 OpenDataLoader JSON 坐标生成 markdown_clear 清洗版。"
                        ),
                        status=JobStatus.running,
                        data={
                            "files_created": postprocess_result.files_created,
                            "filtered_text_count": postprocess_result.filtered_text_count,
                        },
                    )
            if getattr(manifest.options, "llm_polish", False):
                await self._run_llm_polish(job_id, task_type="pdf")
        except OpenDataLoaderPdfRunnerError as exc:
            self.storage.append_log(job_id, exc.message)
            self.storage.update_manifest(
                job_id, status=JobStatus.failed, error=exc.message
            )
            return
        except Exception as exc:  # pragma: no cover - defensive background boundary
            message = f"OpenDataLoader PDF runner failed unexpectedly: {exc}"
            self.storage.append_log(job_id, message)
            self.storage.update_manifest(job_id, status=JobStatus.failed, error=message)
            return

        artifacts = self.storage.discover_output_artifacts(job_id)
        self.storage.update_manifest(
            job_id, status=JobStatus.succeeded, error=None, artifacts=artifacts
        )

    async def enqueue(self, job_id: str) -> None:
        await self.start_job(job_id)

    async def start(self, job_id: str) -> None:
        await self.start_job(job_id)

    async def _run_llm_polish(self, job_id: str, *, task_type: str) -> None:
        from .models import JobStatus

        self.storage.append_event(
            job_id,
            "system",
            "开始执行 LLM 润色。",
            status=JobStatus.running,
        )
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
