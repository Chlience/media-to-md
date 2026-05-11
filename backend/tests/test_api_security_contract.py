from __future__ import annotations

import io
import json
import pathlib
import time
import zipfile
from typing import Any

import pytest

from conftest import import_or_skip

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


ALLOWED_FORMATS = {"srt", "txt"}


class FakeRunner:
    def __init__(self, app_ref: Any):
        self.app_ref = app_ref

    async def start_job(self, job_id: str) -> None:
        models = import_or_skip("app.models")
        storage = self.app_ref.state.storage
        storage.update_manifest(job_id, status=models.JobStatus.running)
        storage.append_log(job_id, "fake runner started")
        manifest = storage.read_manifest(job_id)
        public_formats = set(manifest.options.output_formats)
        output = storage.job_dir(job_id) / "output"
        artifacts = []
        for fmt in sorted(ALLOWED_FORMATS):
            path = output / f"result.{fmt}"
            path.write_text(f"dummy {fmt}", encoding="utf-8")
            if fmt not in public_formats:
                continue
            artifacts.append(
                models.Artifact(
                    name=path.name,
                    format=fmt,
                    path=f"output/{path.name}",
                    size_bytes=path.stat().st_size,
                )
            )
        storage.update_manifest(
            job_id, status=models.JobStatus.succeeded, artifacts=artifacts
        )


def _client(configured_env):
    main = import_or_skip("app.main")
    config = import_or_skip("app.config")
    settings = config.Settings(
        data_root=configured_env,
        whisperx_model_dir=str(configured_env / "models"),
    )
    app = main.create_app(settings=settings)
    app.state.job_service.runner = FakeRunner(app)
    return TestClient(app)


def _upload(client: TestClient):
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"fake audio", "audio/wav")},
        data={"model": "small", "language": "auto", "diarize": "false"},
    )
    assert response.status_code in {200, 201, 202}, response.text
    payload = response.json()
    return payload.get("job_id") or payload.get("id")


def _get(client: TestClient, *paths: str):
    last = None
    for path in paths:
        last = client.get(path)
        if last.status_code != 404:
            return last
    assert last is not None
    return last


def _post(client: TestClient, *paths: str):
    last = None
    for path in paths:
        last = client.post(path)
        if last.status_code != 404:
            return last
    assert last is not None
    return last


def test_upload_creates_manifest_and_status_reconstructs_from_filesystem(
    configured_env,
):
    client = _client(configured_env)
    job_id = _upload(client)
    assert job_id

    manifest_path = pathlib.Path(configured_env) / "jobs" / job_id / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert {
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
    } <= set(manifest)

    status = _get(client, f"/api/jobs/{job_id}/status")
    assert status.status_code == 200
    assert status.json()["status"] in {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }


def test_fake_runner_flow_results_downloads_and_log_allowlist(configured_env):
    client = _client(configured_env)
    job_id = _upload(client)
    start = _post(client, f"/api/jobs/{job_id}/start")
    assert start.status_code in {200, 202, 204}, start.text

    final = None
    for _ in range(50):
        status = _get(client, f"/api/jobs/{job_id}/status")
        assert status.status_code == 200
        final = status.json()
        if final["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert final is not None
    assert final["status"] == "succeeded", final

    results = _get(client, f"/api/jobs/{job_id}/results")
    assert results.status_code == 200
    artifacts = results.json().get("artifacts", results.json())
    assert artifacts
    assert {artifact["format"] for artifact in artifacts} <= ALLOWED_FORMATS

    first = artifacts[0]
    name = first.get("name") or pathlib.Path(first["path"]).name
    download = _get(
        client,
        f"/api/jobs/{job_id}/download/{name}",
    )
    assert download.status_code == 200

    log_download = _get(
        client,
        f"/api/jobs/{job_id}/download/job.log",
    )
    assert log_download.status_code in {400, 403, 404}

    zip_download = _get(client, f"/api/jobs/{job_id}/artifacts.zip")
    assert zip_download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_download.content)) as archive:
        names = set(archive.namelist())
        assert names == {artifact["path"].removeprefix("output/") for artifact in artifacts}
        assert "job.log" not in names
        assert "manifest.json" not in names


def test_download_rejects_traversal_absolute_cross_job_and_unlisted_files(
    configured_env,
):
    client = _client(configured_env)
    job_id = _upload(client)
    bad_names = [
        "../manifest.json",
        "..%2Fmanifest.json",
        "/etc/passwd",
        "input/sample.wav",
        "logs/job.log",
        "manifest.json",
        "not-in-manifest.txt",
    ]
    for name in bad_names:
        response = _get(
            client,
            f"/api/jobs/{job_id}/download/{name}",
        )
        assert response.status_code in {400, 403, 404, 422}, (
            name,
            response.status_code,
            response.text,
        )
