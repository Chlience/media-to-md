from __future__ import annotations

from io import BytesIO

import pytest

from app import storage as storage_module
from app.models import Artifact, JobOptions, JobStatus
from app.storage import InputTooLargeError, JobStorage, StorageError


def test_create_job_writes_canonical_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "probe_media_duration_seconds", lambda _: 12.5)
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(
        BytesIO(b"audio"),
        "../My Audio.wav",
        JobOptions(model="base", language="auto"),
        content_type="audio/WAV; charset=binary",
    )

    assert manifest.schema_version == 1
    assert manifest.job_id
    assert manifest.status == JobStatus.queued
    assert manifest.input_filename == "My_Audio.wav"
    assert manifest.input_content_type == "audio/wav"
    assert manifest.input_size_bytes == 5
    assert manifest.input_duration_seconds == 12.5
    assert manifest.options.model == "base"
    assert manifest.log_path == "logs/job.log"
    assert (tmp_path / "jobs" / manifest.job_id / "manifest.json").is_file()
    assert (
        tmp_path / "jobs" / manifest.job_id / "input" / "My_Audio.wav"
    ).read_bytes() == b"audio"

    reconstructed = storage.read_manifest(manifest.job_id)
    assert reconstructed.job_id == manifest.job_id
    assert reconstructed.input_content_type == "audio/wav"
    assert reconstructed.input_size_bytes == 5
    assert reconstructed.input_duration_seconds == 12.5
    assert reconstructed.artifacts == []


def test_create_job_keeps_upload_when_duration_probe_is_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(storage_module, "probe_media_duration_seconds", lambda _: None)
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"abc"), "sample.mp4", JobOptions())

    assert manifest.input_size_bytes == 3
    assert manifest.input_duration_seconds is None
    event = storage.read_events(manifest.job_id)[0]
    assert event.data["input_size_bytes"] == 3
    assert event.data["input_duration_seconds"] is None


def test_create_job_rejects_input_over_configured_limit_and_removes_partial_job(tmp_path):
    storage = JobStorage(tmp_path)

    with pytest.raises(InputTooLargeError, match="configured limit"):
        storage.create_job(
            BytesIO(b"abcdef"),
            "too-large.wav",
            JobOptions(),
            max_input_size_bytes=3,
        )

    assert list((tmp_path / "jobs").iterdir()) == []


def test_manifest_update_is_valid_json_and_changes_updated_at(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    updated = storage.update_manifest(manifest.job_id, status=JobStatus.running)

    assert updated.status == JobStatus.running
    assert updated.updated_at >= manifest.updated_at
    assert storage.read_manifest(manifest.job_id).status == JobStatus.running


def test_job_events_track_creation_status_logs_and_artifacts(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    storage.update_manifest(manifest.job_id, status=JobStatus.running)
    storage.append_log(manifest.job_id, "runner started")
    storage.update_manifest(
        manifest.job_id,
        status=JobStatus.succeeded,
        artifacts=[
            Artifact(
                name="result.txt",
                format="txt",
                path="output/result.txt",
                size_bytes=2,
            )
        ],
    )

    events = storage.read_events(manifest.job_id)

    assert [event.type for event in events] == [
        "created",
        "status",
        "log",
        "status",
        "artifact",
    ]
    assert events[0].status == JobStatus.queued
    assert events[-1].data["artifact_count"] == 1
    assert any("runner started" in event.message for event in events)


def test_reconcile_stale_running_marks_failed(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    storage.update_manifest(manifest.job_id, status=JobStatus.running)

    changed = storage.reconcile_stale_running()

    assert changed == [manifest.job_id]
    reconciled = storage.read_manifest(manifest.job_id)
    assert reconciled.status == JobStatus.failed
    assert "backend restarted" in (reconciled.error or "")


def test_delete_job_removes_manifest_inputs_outputs_and_logs(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    job_dir = storage.job_dir(manifest.job_id)
    (job_dir / "output" / "result.txt").write_text("ok", encoding="utf-8")
    (job_dir / "logs" / "events.jsonl").write_text("{}", encoding="utf-8")

    deleted = storage.delete_job(manifest.job_id)

    assert deleted.job_id == manifest.job_id
    assert not job_dir.exists()
    with pytest.raises(StorageError, match="job not found"):
        storage.read_manifest(manifest.job_id)


def test_delete_job_rejects_running_task_by_default(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    storage.update_manifest(manifest.job_id, status=JobStatus.running)

    with pytest.raises(StorageError, match="running job cannot be deleted"):
        storage.delete_job(manifest.job_id)

    assert storage.job_dir(manifest.job_id).exists()


def test_download_allowlist_rejects_logs_and_unlisted_files(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"x"), "a.wav", JobOptions())
    job_dir = storage.job_dir(manifest.job_id)
    (job_dir / "output" / "a.txt").write_text("ok", encoding="utf-8")
    (job_dir / "logs" / "job.log").write_text("secret", encoding="utf-8")

    try:
        storage.artifact_file(manifest.job_id, "a.txt")
        assert False, "unlisted output must not be downloadable"
    except Exception as exc:
        assert "not listed" in str(exc)

    updated = storage.write_manifest(
        manifest.model_copy(
            update={
                "artifacts": [
                    Artifact(
                        name="a.txt", format="txt", path="output/a.txt", size_bytes=2
                    )
                ]
            }
        )
    )
    artifact, path = storage.artifact_file(updated.job_id, "a.txt")
    assert artifact.name == "a.txt"
    assert path.read_text(encoding="utf-8") == "ok"

    for bad in ["../a.txt", "/tmp/a.txt", "job.log", "manifest.json"]:
        try:
            storage.artifact_file(manifest.job_id, bad)
            assert False, f"{bad} should be rejected"
        except Exception:
            pass


def test_markdown_artifacts_are_discovered_and_manifest_downloadable(tmp_path):
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(BytesIO(b"pdf"), "sample.pdf", JobOptions())
    output = storage.job_dir(manifest.job_id) / "output"
    (output / "result.md").write_text("# title", encoding="utf-8")
    (output / "result_clear.md").write_text("# clean new title", encoding="utf-8")
    (output / "result.markdown").write_text("# title", encoding="utf-8")
    (output / "result.txt").write_text("title", encoding="utf-8")
    (output / "image.png").write_bytes(b"allowed image artifact")

    artifacts = storage.discover_output_artifacts(manifest.job_id)

    assert {artifact.name for artifact in artifacts} == {
        "image.png",
        "result.markdown",
        "result_clear.md",
        "result.md",
        "result.txt",
    }
    assert {artifact.format for artifact in artifacts} == {
        "markdown",
        "markdown_clear",
        "md",
        "png",
        "txt",
    }

    updated = storage.write_manifest(manifest.model_copy(update={"artifacts": artifacts}))
    artifact, path = storage.artifact_file(updated.job_id, "result.md")
    assert artifact.format == "md"
    assert path.read_text(encoding="utf-8") == "# title"
