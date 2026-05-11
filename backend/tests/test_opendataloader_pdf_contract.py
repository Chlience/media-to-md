from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import Artifact, JobManifest, JobStatus, PdfJobOptions


def _admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "secret-pass"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class RecordingDispatcher:
    def __init__(self, app_ref: Any):
        self.app_ref = app_ref
        self.started: list[str] = []

    async def start_job(self, job_id: str) -> None:
        self.started.append(job_id)
        storage = self.app_ref.state.storage
        manifest = storage.read_manifest(job_id)
        storage.update_manifest(job_id, status=JobStatus.running)
        storage.append_log(job_id, f"started {manifest.options.task_type} job")
        output = storage.job_dir(job_id) / "output"
        markdown = output / "result.md"
        text = output / "result.txt"
        markdown.write_text("# Parsed PDF\n", encoding="utf-8")
        text.write_text("Parsed PDF\n", encoding="utf-8")
        storage.update_manifest(
            job_id,
            status=JobStatus.succeeded,
            artifacts=[
                Artifact(
                    name=markdown.name,
                    format="md",
                    path=f"output/{markdown.name}",
                    size_bytes=markdown.stat().st_size,
                ),
                Artifact(
                    name=text.name,
                    format="txt",
                    path=f"output/{text.name}",
                    size_bytes=text.stat().st_size,
                ),
            ],
        )


def _client(tmp_path: Path):
    settings = Settings(
        data_root=tmp_path,
        whisperx_model="small",
        whisperx_model_dir=str(tmp_path / "models"),
        admin_username="admin",
        admin_password="secret-pass",
    )
    app = create_app(settings=settings)
    runner = RecordingDispatcher(app)
    app.state.job_service.runner = runner
    return TestClient(app), runner, app


def _whisperx_manifest_payload() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "job_id": "whisperx-job",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "input_filename": "sample.wav",
        "input_size_bytes": 3,
        "input_duration_seconds": None,
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


def _upload_pdf(
    client: TestClient, markdown_cleanup_strength: str | None = None
) -> str:
    data = {"task_type": "pdf"}
    if markdown_cleanup_strength is not None:
        data["markdown_cleanup_strength"] = markdown_cleanup_strength
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.pdf", b"%PDF-1.7\n", "application/pdf")},
        data=data,
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def test_manifest_deserializes_current_whisperx_options():
    manifest = JobManifest.model_validate(_whisperx_manifest_payload())

    assert manifest.options.task_type == "whisperx"
    assert manifest.options.model == "small"
    assert manifest.options.output_formats == ["srt", "txt"]


def test_upload_without_task_type_defaults_to_whisperx_options(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"model": "small", "language": "auto", "diarize": "false"},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["task_type"] == "whisperx"
    assert status["task_type"] == "whisperx"


def test_pdf_upload_creates_discriminated_pdf_options(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    job_id = _upload_pdf(client)
    status = client.get(f"/api/jobs/{job_id}/status").json()

    assert status["task_type"] == "pdf"
    assert status["input_filename"] == "sample.pdf"
    assert status["options"]["task_type"] == "pdf"
    assert status["options"]["format"] in {"markdown,text", "md,txt"}
    assert status["options"]["image_output"] == "off"
    assert status["options"]["markdown_cleanup_strength"] == "balanced"
    assert "output_formats" not in status["options"]
    assert "model" not in status["options"]


def test_pdf_options_reject_output_formats_alias():
    with pytest.raises(ValidationError):
        PdfJobOptions(**{"output_formats": ["md", "txt"]})


def test_pdf_upload_defaults_markdown_cleanup_strength_to_balanced(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    job_id = _upload_pdf(client)
    status = client.get(f"/api/jobs/{job_id}/status").json()

    assert status["options"]["markdown_cleanup_strength"] == "balanced"


def test_pdf_upload_rejects_output_formats_alias(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"task_type": "pdf", "output_formats": "markdown,text"},
    )

    assert response.status_code == 400
    assert "output_formats" in response.text


def test_pdf_upload_normalizes_markdown_cleanup_strength(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    job_id = _upload_pdf(client, "  Conservative  ")
    status = client.get(f"/api/jobs/{job_id}/status").json()

    assert status["options"]["markdown_cleanup_strength"] == "conservative"


def test_pdf_upload_rejects_invalid_markdown_cleanup_strength(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"task_type": "pdf", "markdown_cleanup_strength": "maximum"},
    )

    assert response.status_code == 400
    assert "markdown_cleanup_strength" in response.json()["detail"]


def test_whisperx_upload_ignores_markdown_cleanup_strength(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "auto",
            "diarize": "false",
            "markdown_cleanup_strength": "maximum",
        },
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["task_type"] == "whisperx"
    assert "markdown_cleanup_strength" not in status["options"]


def test_pdf_upload_reuses_jobs_lifecycle(tmp_path: Path):
    client, runner, _ = _client(tmp_path)
    job_id = _upload_pdf(client)

    start = client.post(f"/api/jobs/{job_id}/start")
    assert start.status_code == 202, start.text
    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}/status").json()
        if status["status"] == "succeeded":
            break

    results = client.get(f"/api/jobs/{job_id}/results")
    events = client.get(f"/api/jobs/{job_id}/events", headers=_admin_headers(client))

    assert runner.started == [job_id]
    assert results.status_code == 200
    assert {artifact["format"] for artifact in results.json()["artifacts"]} == {
        "md",
        "txt",
    }
    assert events.status_code == 200
    assert any("pdf" in event["message"] for event in events.json()["events"])


def test_pdf_status_results_events_use_existing_routes(tmp_path: Path):
    client, _, _ = _client(tmp_path)
    headers = _admin_headers(client)
    job_id = _upload_pdf(client)

    status = client.get(f"/api/jobs/{job_id}/status")
    results = client.get(f"/api/jobs/{job_id}/results")
    events = client.get(f"/api/jobs/{job_id}/events", headers=headers)

    assert status.status_code == 200
    assert results.status_code == 200
    assert events.status_code == 200
    assert status.json()["task_type"] == "pdf"
    assert results.json()["task_type"] == "pdf"
    assert events.json()["job_id"] == job_id


def test_pdf_image_output_defaults_off(tmp_path: Path):
    client, _, _ = _client(tmp_path)
    headers = _admin_headers(client)

    config = client.get("/api/admin/config", headers=headers)
    job_id = _upload_pdf(client)
    status = client.get(f"/api/jobs/{job_id}/status")

    assert config.status_code == 200
    assert config.json()["opendataloader_pdf_args_config"]["image_output"] == "off"
    assert status.json()["options"]["image_output"] == "off"


def test_admin_jobs_include_task_type(tmp_path: Path):
    client, _, _ = _client(tmp_path)
    headers = _admin_headers(client)
    job_id = _upload_pdf(client)

    response = client.get("/api/jobs", headers=headers)

    assert response.status_code == 200
    by_id = {job["job_id"]: job for job in response.json()["jobs"]}
    assert by_id[job_id]["task_type"] == "pdf"
    assert by_id[job_id]["options"]["task_type"] == "pdf"


@pytest.mark.parametrize(
    "invalid_key, invalid_value",
    [
        ("ocr", True),
        ("content_safety_off", True),
        ("content-safety-off", True),
        ("output_dir", "/tmp/opendl-output"),
        ("to_stdout", True),
        ("image_dir", "images"),
        ("hybrid_url", "http://127.0.0.1:5002"),
    ],
)
def test_pdf_config_rejects_unsupported_or_invalid_cli_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_key: str, invalid_value: Any
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_root": "data",
                "whisperx_model": "small",
                "admin_username": "admin",
                "admin_password": "secret-pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", str(config_path))
    client = TestClient(create_app())
    headers = _admin_headers(client)

    response = client.put(
        "/api/admin/config",
        headers=headers,
        json={
            "whisperx_model": "small",
            "model_cache_only": False,
            "whisperx_args": {},
            "opendataloader_pdf_args": {invalid_key: invalid_value},
        },
    )

    assert response.status_code == 400, response.text
    assert invalid_key in response.text or invalid_key.replace("-", "_") in response.text


def test_pdf_config_accepts_retained_cli_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_root": "data",
                "whisperx_model": "small",
                "admin_username": "admin",
                "admin_password": "secret-pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", str(config_path))
    client = TestClient(create_app())
    headers = _admin_headers(client)

    response = client.put(
        "/api/admin/config",
        headers=headers,
        json={
            "whisperx_model": "small",
            "model_cache_only": False,
            "whisperx_args": {},
            "opendataloader_pdf_args": {
                "format": "json,text,html,pdf,markdown,markdown-with-html,markdown-with-images,tagged-pdf",
                "pages": "1-3",
                "table_method": "cluster",
                "reading_order": "xycut",
                "image_output": "external",
                "image_format": "jpeg",
                "threads": 2,
                "hybrid": "docling-fast",
                "hybrid_mode": "auto",
                "hybrid_timeout": 30000,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    config = payload["opendataloader_pdf_args_config"]
    assert config["format"].startswith("json,text,html")
    assert config["image_output"] == "external"
    assert config["image_format"] == "jpeg"
    assert config["pages"] == "1-3"
    assert config["threads"] == "2"
    assert config["hybrid"] == "docling-fast"
    assert config["hybrid_timeout"] == "30000"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["opendataloader_pdf_args"]["image_output"] == "external"
    assert saved["opendataloader_pdf_args"]["hybrid"] == "docling-fast"
    assert "output_dir" not in saved["opendataloader_pdf_args"]

def test_admin_config_rebuilds_dispatcher_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_root": "data",
                "whisperx_model": "small",
                "admin_username": "admin",
                "admin_password": "secret-pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", str(config_path))
    client = TestClient(create_app())
    headers = _admin_headers(client)
    before_runner = client.app.state.job_service.runner

    response = client.put(
        "/api/admin/config",
        headers=headers,
        json={
            "whisperx_model": "small",
            "model_cache_only": False,
            "whisperx_args": {},
            "opendataloader_pdf_args": {"threads": 2},
        },
    )

    assert response.status_code == 200, response.text
    after_runner = client.app.state.job_service.runner
    assert after_runner is not before_runner
    assert after_runner.__class__.__name__ in {
        "JobRunnerDispatcher",
        "DispatchingJobRunner",
        "TaskTypeJobRunner",
    }


def test_markdown_txt_artifacts_are_manifest_downloadable(tmp_path: Path):
    client, _, app = _client(tmp_path)
    manifest = app.state.storage.create_job(
        BytesIO(b"%PDF-1.7\n"),
        "sample.pdf",
        app.state.storage.read_manifest(_upload_pdf(client)).options,
    )
    output = app.state.storage.job_dir(manifest.job_id) / "output"
    markdown = output / "result.md"
    text = output / "result.txt"
    markdown.write_text("# markdown", encoding="utf-8")
    text.write_text("plain text", encoding="utf-8")
    app.state.storage.update_manifest(
        manifest.job_id,
        status=JobStatus.succeeded,
        artifacts=[
            Artifact(
                name="result.md",
                format="md",
                path="output/result.md",
                size_bytes=markdown.stat().st_size,
            ),
            Artifact(
                name="result.txt",
                format="txt",
                path="output/result.txt",
                size_bytes=text.stat().st_size,
            ),
        ],
    )

    assert client.get(f"/api/jobs/{manifest.job_id}/download/result.md").text == "# markdown"
    assert client.get(f"/api/jobs/{manifest.job_id}/download/result.txt").text == "plain text"


def test_download_rejects_unlisted_markdown_file(tmp_path: Path):
    client, _, app = _client(tmp_path)
    job_id = _upload_pdf(client)
    output = app.state.storage.job_dir(job_id) / "output"
    (output / "unlisted.md").write_text("not in manifest", encoding="utf-8")

    response = client.get(f"/api/jobs/{job_id}/download/unlisted.md")

    assert response.status_code in {400, 403, 404}


def test_nested_artifact_paths_cannot_escape_job_output(tmp_path: Path):
    client, _, app = _client(tmp_path)
    job_id = _upload_pdf(client)
    outside = app.state.storage.job_dir(job_id) / "outside.md"
    outside.write_text("escape", encoding="utf-8")

    with pytest.raises(ValueError):
        Artifact(
            name="outside.md",
            format="md",
            path="output/../outside.md",
            size_bytes=outside.stat().st_size,
        )


def test_external_images_not_enabled_by_default(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    job_id = _upload_pdf(client)
    status = client.get(f"/api/jobs/{job_id}/status").json()

    assert status["options"]["image_output"] == "off"
