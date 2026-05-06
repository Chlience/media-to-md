from __future__ import annotations

import asyncio
from io import BytesIO

import pytest

from app.jobs import JobRunnerDispatcher, JobService, build_job_runner
from app.models import JobOptions
from app.opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner
from app.storage import JobStorage
from app.whisperx_runner import JobStorageWhisperXRunner


class Recorder:
    def __init__(self):
        self.started: list[str] = []

    async def start_job(self, job_id: str) -> None:
        self.started.append(job_id)


class NoEntrypoint:
    pass


def test_build_job_runner_dispatcher_contains_whisperx_and_pdf(tmp_path):
    class Settings:
        whisperx_model_dir = None
        whisperx_model = "small"
        nltk_data_dir = None
        whisperx_args = ()

    dispatcher = build_job_runner(JobStorage(tmp_path), Settings())

    assert isinstance(dispatcher, JobRunnerDispatcher)
    assert isinstance(dispatcher.runners["whisperx"], JobStorageWhisperXRunner)
    assert isinstance(dispatcher.runners["pdf"], JobStorageOpenDataLoaderPdfRunner)


def test_dispatcher_routes_by_manifest_task_type(tmp_path):
    storage = JobStorage(tmp_path)
    whisperx = Recorder()
    pdf = Recorder()
    dispatcher = JobRunnerDispatcher(storage, {"whisperx": whisperx, "pdf": pdf})
    whisper_job = storage.create_job(BytesIO(b"audio"), "a.wav", JobOptions())
    pdf_job = storage.create_job(BytesIO(b"%PDF"), "a.pdf", JobOptions(task_type="pdf"))

    asyncio.run(dispatcher.start_job(whisper_job.job_id))
    asyncio.run(dispatcher.start_job(pdf_job.job_id))

    assert whisperx.started == [whisper_job.job_id]
    assert pdf.started == [pdf_job.job_id]


def test_job_service_raises_if_runner_has_no_entrypoint(tmp_path):
    storage = JobStorage(tmp_path)
    service = JobService(storage, runner=NoEntrypoint())
    manifest = storage.create_job(BytesIO(b"audio"), "a.wav", JobOptions())

    with pytest.raises(RuntimeError, match="no start_job/enqueue/start"):
        asyncio.run(service.start_job(manifest.job_id))
