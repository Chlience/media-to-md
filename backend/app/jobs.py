from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Protocol

from .models import DiscriminatedJobOptions, JobManifest, JobStatus
from .storage import JobStorage


class RunnerProtocol(Protocol):
    def start_job(self, job_id: str) -> Any: ...


class NoopRunner:
    """Safe default until the WhisperX runner lane wires real execution."""

    def __init__(self, storage: JobStorage):
        self.storage = storage

    async def start_job(self, job_id: str) -> None:
        self.storage.update_manifest(
            job_id,
            status=JobStatus.failed,
            error="No WhisperX runner is configured for this backend process.",
        )
        self.storage.append_log(
            job_id, "No WhisperX runner is configured for this backend process."
        )


class JobService:
    def __init__(self, storage: JobStorage, runner: Any | None = None):
        self.storage = storage
        self.runner = runner or NoopRunner(storage)

    def create_job(
        self, fileobj, filename: str, options: DiscriminatedJobOptions
    ) -> JobManifest:
        return self.storage.create_job(fileobj, filename, options)

    async def start_job(self, job_id: str) -> None:
        self.storage.read_manifest(job_id)
        starter = self._resolve_runner_starter()
        result = starter(job_id)
        if inspect.isawaitable(result):
            await result

    def _resolve_runner_starter(self) -> Callable[[str], Any]:
        for name in ("start_job", "enqueue", "start"):
            starter = getattr(self.runner, name, None)
            if callable(starter):
                return starter
        raise RuntimeError("configured runner has no start_job/enqueue/start method")


class JobRunnerDispatcher:
    """Dispatch JobService starts to the runner matching each job manifest type."""

    def __init__(self, storage: JobStorage, runners: dict[str, Any]):
        self.storage = storage
        self.runners = runners

    async def start_job(self, job_id: str) -> None:
        manifest = self.storage.read_manifest(job_id)
        task_type = getattr(manifest.options, "task_type", "whisperx")
        runner = self.runners.get(task_type)
        if runner is None:
            raise RuntimeError(f"no runner configured for task type '{task_type}'")
        result = self._resolve_runner_starter(runner)(job_id)
        if inspect.isawaitable(result):
            await result

    def _resolve_runner_starter(self, runner: Any) -> Callable[[str], Any]:
        for name in ("start_job", "enqueue", "start"):
            starter = getattr(runner, name, None)
            if callable(starter):
                return starter
        raise RuntimeError("configured runner has no start_job/enqueue/start method")


def build_job_runner(storage: JobStorage, settings) -> JobRunnerDispatcher:
    """Build the task-type dispatcher used by the API job service."""

    from .opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner
    from .whisperx_runner import JobStorageWhisperXRunner

    return JobRunnerDispatcher(
        storage,
        {
            "whisperx": JobStorageWhisperXRunner.from_settings(storage, settings),
            "pdf": JobStorageOpenDataLoaderPdfRunner.from_settings(storage, settings),
        },
    )
