from __future__ import annotations

import dataclasses
import json
from io import BytesIO
from datetime import datetime, timezone

import pytest


from conftest import import_or_skip

REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "job_id",
    "status",
    "created_at",
    "updated_at",
    "input_filename",
    "input_size_bytes",
    "input_duration_seconds",
    "options",
    "error",
    "artifacts",
    "log_path",
}


def _asdict(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _example_manifest(job_id="job-contract"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "job_id": job_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "input_filename": "sample.wav",
        "input_size_bytes": 1234,
        "input_duration_seconds": 12.5,
        "options": {
            "task_type": "whisperx",
            "model": "small",
            "language": "auto",
            "diarize": True,
            "model_dir": None,
            "model_cache_only": False,
            "output_formats": ["srt", "txt"],
        },
        "error": None,
        "artifacts": [],
        "log_path": "logs/job.log",
    }


def test_manifest_create_update_read_preserves_required_contract(
    tmp_path, configured_env
):
    storage = import_or_skip("app.storage")
    models = import_or_skip("app.models")
    job_storage = storage.JobStorage(tmp_path)
    manifest = job_storage.create_job(
        BytesIO(b"audio"), "sample.wav", models.JobOptions(model="small")
    )
    loaded = _asdict(job_storage.read_manifest(manifest.job_id))

    assert REQUIRED_MANIFEST_FIELDS <= set(loaded)
    assert loaded["schema_version"] == 1
    assert loaded["job_id"] == manifest.job_id
    assert loaded["status"] == "queued"
    assert loaded["log_path"] == "logs/job.log"

    before = loaded["updated_at"]
    updated = _asdict(
        job_storage.update_manifest(manifest.job_id, status=models.JobStatus.running)
    )

    assert updated["status"] == "running"
    assert updated["updated_at"] >= before
    json.loads((tmp_path / "jobs" / manifest.job_id / "manifest.json").read_text())


def test_stale_running_jobs_reconcile_to_failed(tmp_path, configured_env):
    storage = import_or_skip("app.storage")
    models = import_or_skip("app.models")
    job_storage = storage.JobStorage(tmp_path / "data")
    manifest = job_storage.create_job(
        BytesIO(b"audio"), "sample.wav", models.JobOptions()
    )
    job_storage.update_manifest(manifest.job_id, status=models.JobStatus.running)

    changed = job_storage.reconcile_stale_running()
    loaded = _asdict(job_storage.read_manifest(manifest.job_id))

    assert changed == [manifest.job_id]
    assert loaded["status"] == "failed"
    assert loaded["error"]
    assert (
        "restart" in loaded["error"].lower() or "interrupted" in loaded["error"].lower()
    )


def test_job_manifest_options_are_discriminated_by_task_type(
    configured_env,
):
    models = import_or_skip("app.models")
    whisperx_payload = _example_manifest()

    whisperx_manifest = models.JobManifest.model_validate(whisperx_payload)
    assert isinstance(whisperx_manifest.options, models.WhisperXJobOptions)
    assert whisperx_manifest.options.task_type == "whisperx"

    pdf_payload = _example_manifest(job_id="pdf-contract")
    pdf_payload["input_filename"] = "sample.pdf"
    pdf_payload["options"] = {
        "task_type": "pdf",
        "format": ["markdown", "text"],
        "image_output": "off",
        "threads": 2,
    }

    pdf_manifest = models.JobManifest.model_validate(pdf_payload)
    assert isinstance(pdf_manifest.options, models.PdfJobOptions)
    assert pdf_manifest.options.task_type == "pdf"
    assert pdf_manifest.options.image_output == "off"
    assert pdf_manifest.options.markdown_cleanup_strength == "balanced"

    external = _example_manifest(job_id="external-image-pdf")
    external["options"] = {"task_type": "pdf", "image_output": "external"}
    external_manifest = models.JobManifest.model_validate(external)
    assert external_manifest.options.image_output == "external"


def test_pdf_job_options_defaults_cleanup_strength_balanced(configured_env):
    models = import_or_skip("app.models")

    options = models.PdfJobOptions()

    assert options.markdown_cleanup_strength == "balanced"


def test_pdf_job_options_accepts_all_cleanup_strength_values(configured_env):
    models = import_or_skip("app.models")

    for strength in ("off", "conservative", "balanced", "aggressive"):
        options = models.PdfJobOptions(
            task_type="pdf",
            markdown_cleanup_strength=strength,
        )
        assert options.markdown_cleanup_strength == strength


def test_pdf_job_options_rejects_invalid_cleanup_strength(configured_env):
    models = import_or_skip("app.models")

    with pytest.raises(ValueError):
        models.PdfJobOptions(task_type="pdf", markdown_cleanup_strength="invalid")


def test_pdf_manifest_defaults_cleanup_strength_balanced(configured_env):
    models = import_or_skip("app.models")

    payload = _example_manifest(job_id="pdf-defaults")
    payload["input_filename"] = "sample.pdf"
    payload["options"] = {
        "task_type": "pdf",
        "format": ["markdown", "text"],
        "image_output": "off",
        "threads": 2,
    }

    manifest = models.JobManifest.model_validate(payload)
    assert isinstance(manifest.options, models.PdfJobOptions)
    assert manifest.options.task_type == "pdf"
    assert manifest.options.markdown_cleanup_strength == "balanced"
