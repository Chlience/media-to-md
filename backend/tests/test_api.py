from __future__ import annotations

import asyncio
import io
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import JobRunnerDispatcher
from app.main import create_app
from app.models import Artifact, JobOptions, JobStatus
from app.opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner
from app.whisperx_openai_runner import JobStorageOpenAIWhisperXRunner
from app.whisperx_runner import JobStorageWhisperXRunner


class FakeRunner:
    def __init__(self, app_ref):
        self.app_ref = app_ref
        self.started: list[str] = []

    async def start_job(self, job_id: str) -> None:
        self.started.append(job_id)
        storage = self.app_ref.state.storage
        storage.update_manifest(job_id, status=JobStatus.running)
        storage.append_log(job_id, "fake runner started")
        manifest = storage.read_manifest(job_id)
        public_formats = set(manifest.options.output_formats)
        output = storage.job_dir(job_id) / "output"
        artifacts = []
        for fmt in ["txt", "srt", "vtt", "json"]:
            path = output / f"result.{fmt}"
            path.write_text(f"dummy {fmt}", encoding="utf-8")
            if fmt not in public_formats:
                continue
            artifacts.append(
                Artifact(
                    name=path.name,
                    format=fmt,
                    path=f"output/{path.name}",
                    size_bytes=path.stat().st_size,
                )
            )
        storage.update_manifest(job_id, status=JobStatus.succeeded, artifacts=artifacts)


def make_client(tmp_path: Path):
    settings = Settings(
        data_root=tmp_path,
        whisperx_model="/models/faster-whisper-large-v2",
        whisperx_model_dir="/models",
        model_cache_only=True,
        nltk_data_dir="/models/nltk_data",
        admin_username="admin",
        admin_password="secret-pass",
    )
    app = create_app(settings=settings)
    runner = FakeRunner(app)
    app.state.job_service.runner = runner
    return TestClient(app), runner, app


def upload(client: TestClient) -> str:
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"model": "small", "language": "auto", "diarize": "false"},
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def admin_headers(
    client: TestClient, username: str = "admin", password: str = "secret-pass"
) -> dict[str, str]:
    response = client.post(
        "/api/admin/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_status_config_reconstruct_from_filesystem(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)

    assert client.get("/api/config").status_code == 401
    assert client.get("/api/admin/config").status_code == 401
    assert client.get("/api/admin/config", headers=headers).json() == {
        "api_base_url": None,
        "whisperx_model": "/models/faster-whisper-large-v2",
        "whisperx_model_dir": "/models",
        "whisperx_backend": "cli",
        "whisperx_openai_base_url": None,
        "whisperx_openai_api_key_configured": False,
        "whisperx_openai_timeout_seconds": 3600.0,
        "model_cache_only": True,
        "nltk_data_dir": "/models/nltk_data",
        "whisperx_args": [],
        "whisperx_args_config": {},
        "opendataloader_pdf_args": [],
        "opendataloader_pdf_args_config": {"format": "markdown,text", "image_output": "off"},
    }
    job_id = upload(client)

    status = client.get(f"/api/jobs/{job_id}/status").json()
    assert status["status"] == "queued"
    assert status["input_filename"] == "sample.wav"
    assert status["input_size_bytes"] == 3
    assert "input_duration_seconds" in status
    assert status["options"]["model"] == "small"
    assert status["options"]["model_dir"] == "/models"
    assert status["options"]["output_formats"] == ["txt", "srt", "vtt"]
    assert set(status) >= {
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
        "log",
    }

    # API reads disk state, not process-local runner memory.
    app.state.job_service.runner.started.clear()
    assert client.get(f"/api/jobs/{job_id}/results").json()["artifacts"] == []


def test_admin_lists_all_jobs_without_logs_by_default(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    first_job = upload(client)
    second_job = upload(client)
    app.state.storage.update_manifest(first_job, status=JobStatus.running)
    app.state.storage.append_log(first_job, "runner log")

    response = client.get("/api/jobs", headers=headers)

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    by_id = {job["job_id"]: job for job in jobs}
    assert set(by_id) == {first_job, second_job}
    assert by_id[first_job]["status"] == "running"
    assert by_id[second_job]["status"] == "queued"
    assert by_id[first_job]["input_filename"] == "sample.wav"
    assert by_id[first_job]["input_size_bytes"] == 3
    assert "input_duration_seconds" in by_id[first_job]
    assert by_id[first_job]["log"] is None
    assert by_id[first_job]["options"]["model_dir"] == "/models"


def test_admin_can_include_logs_when_requested(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)
    app.state.storage.append_log(job_id, "visible admin log")

    response = client.get("/api/jobs?include_log=true", headers=headers)

    assert response.status_code == 200
    [job] = response.json()["jobs"]
    assert job["job_id"] == job_id
    assert "visible admin log" in job["log"]


def test_public_status_never_includes_log_content(tmp_path):
    client, _, app = make_client(tmp_path)
    job_id = upload(client)
    app.state.storage.append_log(job_id, "private runner detail")

    default_response = client.get(f"/api/jobs/{job_id}/status")
    requested_response = client.get(f"/api/jobs/{job_id}/status?include_log=true")

    assert default_response.status_code == 200
    assert requested_response.status_code == 200
    assert default_response.json()["log"] is None
    assert requested_response.json()["log"] is None
    assert "private runner detail" not in default_response.text
    assert "private runner detail" not in requested_response.text


def test_public_status_exposes_safe_whisperx_runtime_phase(tmp_path):
    client, _, app = make_client(tmp_path)
    job_id = upload(client)
    app.state.storage.update_manifest(job_id, status=JobStatus.running)
    app.state.storage.append_log(
        job_id,
        "2026-05-06 16:56:06 - whisperx.transcribe - INFO - Performing transcription...",
    )

    response = client.get(f"/api/jobs/{job_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_phase"] == {
        "code": "transcription",
        "label": "语音转文字",
        "detail": "正在把语音片段转写为文本。",
    }
    assert payload["log"] is None
    assert "Performing transcription" not in response.text


def test_job_logs_are_admin_only_with_raw_download(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)
    app.state.storage.append_log(job_id, "visible admin log")

    unauthorized_inline = client.get(f"/api/jobs/{job_id}/logs")
    unauthorized_download = client.get(f"/api/jobs/{job_id}/logs/download")
    inline = client.get(f"/api/jobs/{job_id}/logs", headers=headers)
    download = client.get(f"/api/jobs/{job_id}/logs/download", headers=headers)

    assert unauthorized_inline.status_code == 401
    assert unauthorized_download.status_code == 401
    assert inline.status_code == 200
    assert inline.json() == {"job_id": job_id, "log": "visible admin log\n"}
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/plain")
    assert download.text == "visible admin log\n"
    assert 'filename="job.log"' in download.headers["content-disposition"]


def test_admin_can_view_job_execution_events(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)
    app.state.storage.update_manifest(job_id, status=JobStatus.running)
    app.state.storage.append_log(job_id, "visible admin event")
    app.state.storage.update_manifest(job_id, status=JobStatus.failed, error="boom")

    unauthorized = client.get(f"/api/jobs/{job_id}/events")
    response = client.get(f"/api/jobs/{job_id}/events", headers=headers)

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    events = response.json()["events"]
    assert response.json()["job_id"] == job_id
    assert [event["type"] for event in events] == [
        "created",
        "status",
        "log",
        "status",
        "error",
    ]
    assert any(event["message"] == "visible admin event" for event in events)
    assert events[-1]["message"] == "boom"


def test_admin_can_delete_job_and_related_files(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)
    job_dir = app.state.storage.job_dir(job_id)
    (job_dir / "output" / "result.txt").write_text("ok", encoding="utf-8")

    unauthorized = client.delete(f"/api/jobs/{job_id}")
    response = client.delete(f"/api/jobs/{job_id}", headers=headers)

    assert unauthorized.status_code == 401
    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": job_id, "deleted": True}
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}/status").status_code == 404
    assert all(
        job["job_id"] != job_id
        for job in client.get("/api/jobs", headers=headers).json()["jobs"]
    )


def test_admin_delete_running_job_is_rejected_without_removing_files(tmp_path):
    client, _, app = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)
    app.state.storage.update_manifest(job_id, status=JobStatus.running)
    job_dir = app.state.storage.job_dir(job_id)

    response = client.delete(f"/api/jobs/{job_id}", headers=headers)

    assert response.status_code == 409
    assert "Running jobs cannot be deleted" in response.text
    assert job_dir.exists()


def test_admin_job_list_requires_login(tmp_path):
    client, _, _ = make_client(tmp_path)
    upload(client)

    assert client.get("/api/jobs").status_code == 401
    bad_login = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "wrong-pass"},
    )
    assert bad_login.status_code == 401


def test_admin_account_can_be_read_and_updated(tmp_path):
    client, _, _ = make_client(tmp_path)
    headers = admin_headers(client)

    account = client.get("/api/admin/account", headers=headers)
    assert account.status_code == 200
    assert account.json()["username"] == "admin"

    updated = client.put(
        "/api/admin/account",
        headers=headers,
        json={
            "current_password": "secret-pass",
            "username": "owner",
            "new_password": "new-secret-pass",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["username"] == "owner"

    old_login = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "secret-pass"},
    )
    assert old_login.status_code == 401
    new_headers = admin_headers(client, username="owner", password="new-secret-pass")
    assert client.get("/api/jobs", headers=new_headers).status_code == 200


def test_admin_can_update_backend_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    data_root = tmp_path / "data"
    config_path.write_text(
        """
{
  "data_root": "data",
  "whisperx_model": "small",
  "whisperx_model_dir": "models",
  "nltk_data_dir": "models/nltk_data",
  "model_cache_only": false,
  "whisperx_args": {
    "batch_size": 8
  },
  "admin_username": "admin",
  "admin_password": "secret-pass"
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("WHISPERX_DATA_ROOT", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL_DIR", raising=False)
    monkeypatch.delenv("WHISPERX_NLTK_DATA_DIR", raising=False)
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL_CACHE_ONLY", raising=False)
    monkeypatch.delenv("WHISPERX_ARGS_JSON", raising=False)
    monkeypatch.delenv("WHISPERX_BACKEND", raising=False)
    monkeypatch.delenv("WHISPERX_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("WHISPERX_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WHISPERX_OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_PASSWORD", raising=False)
    client = TestClient(create_app())
    headers = admin_headers(client)

    response = client.put(
        "/api/admin/config",
        headers=headers,
        json={
            "whisperx_model": "/models/faster-whisper-large-v2",
            "api_base_url": "http://localhost:8000/api",
            "whisperx_model_dir": "/models",
            "whisperx_backend": "openai",
            "whisperx_openai_base_url": "http://localhost:9000/v1",
            "whisperx_openai_api_key": "test-key",
            "whisperx_openai_timeout_seconds": 180,
            "nltk_data_dir": "/models/nltk",
            "model_cache_only": True,
            "whisperx_args": {
                "batch_size": 12,
                "compute_type": "int8",
                "diarize_model": "/models/pyannote",
                "min_speakers": 1,
                "max_speakers": 4,
                "speaker_embeddings": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "api_base_url": "http://localhost:8000/api",
        "whisperx_model": "/models/faster-whisper-large-v2",
        "whisperx_model_dir": "/models",
        "whisperx_backend": "openai",
        "whisperx_openai_base_url": "http://localhost:9000/v1",
        "whisperx_openai_api_key_configured": True,
        "whisperx_openai_timeout_seconds": 180.0,
        "model_cache_only": True,
        "nltk_data_dir": "/models/nltk",
        "whisperx_args": [
            "--batch_size",
            "12",
            "--compute_type",
            "int8",
            "--diarize_model",
            "/models/pyannote",
            "--min_speakers",
            "1",
            "--max_speakers",
            "4",
            "--speaker_embeddings",
        ],
        "whisperx_args_config": {
            "batch_size": 12,
            "compute_type": "int8",
            "diarize_model": "/models/pyannote",
            "min_speakers": 1,
            "max_speakers": 4,
            "speaker_embeddings": True,
        },
        "opendataloader_pdf_args": [
            "--format",
            "markdown,text",
            "--image-output",
            "off",
        ],
        "opendataloader_pdf_args_config": {
            "format": "markdown,text",
            "image_output": "off",
        },
    }
    saved = config_path.read_text(encoding="utf-8")
    assert '"data_root": "data"' in saved
    assert '"admin_password": "secret-pass"' in saved
    assert '"api_base_url": "http://localhost:8000/api"' in saved
    assert '"batch_size": 12' in saved
    assert '"diarize_model": "/models/pyannote"' in saved
    assert '"whisperx_backend": "openai"' in saved
    assert '"whisperx_openai_api_key": "test-key"' in saved
    assert data_root.exists()

    upload_response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"language": "auto", "diarize": "false"},
    )
    assert upload_response.status_code == 201, upload_response.text
    job_id = upload_response.json()["job_id"]
    status = client.get(f"/api/jobs/{job_id}/status").json()
    assert status["options"]["model"] == "/models/faster-whisper-large-v2"
    assert status["options"]["model_dir"] == "/models"
    assert status["options"]["model_cache_only"] is True
    runner = client.app.state.job_service.runner
    assert isinstance(runner, JobRunnerDispatcher)
    whisperx_runner = runner.runners["whisperx"]
    assert isinstance(whisperx_runner, JobStorageOpenAIWhisperXRunner)
    assert whisperx_runner.config.default_model == "/models/faster-whisper-large-v2"
    assert whisperx_runner.config.base_url == "http://localhost:9000/v1"


def test_admin_config_update_requires_login(tmp_path):
    client, _, _ = make_client(tmp_path)

    assert client.get("/api/config").status_code == 401
    assert client.get("/api/admin/config").status_code == 401

    response = client.put(
        "/api/admin/config",
        json={
            "whisperx_model": "small",
            "model_cache_only": False,
            "whisperx_args": {},
        },
    )

    assert response.status_code == 401


def test_start_fake_runner_flow_results_and_downloads(tmp_path):
    client, runner, _ = make_client(tmp_path)
    headers = admin_headers(client)
    job_id = upload(client)

    response = client.post(f"/api/jobs/{job_id}/start")
    assert response.status_code == 202
    # TestClient event loop may not drain create_task immediately; allow it to run.
    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}/status").json()
        if status["status"] == "succeeded":
            break
        import time

        time.sleep(0.01)

    status = client.get(f"/api/jobs/{job_id}/status").json()
    assert status["status"] == "succeeded"
    assert status["log"] is None
    assert runner.started == [job_id]

    log_response = client.get(f"/api/jobs/{job_id}/logs", headers=headers)
    assert log_response.status_code == 200
    assert "fake runner started" in log_response.json()["log"]

    results = client.get(f"/api/jobs/{job_id}/results").json()
    assert results["input_filename"] == "sample.wav"
    assert results["input_size_bytes"] == 3
    assert "input_duration_seconds" in results
    assert {a["format"] for a in results["artifacts"]} == {"txt", "srt", "vtt"}
    dl = client.get(f"/api/jobs/{job_id}/download/result.txt")
    assert dl.status_code == 200
    assert dl.text == "dummy txt"
    assert client.get(f"/api/jobs/{job_id}/download/result.json").status_code == 400

    zip_response = client.get(f"/api/jobs/{job_id}/artifacts.zip")
    assert zip_response.status_code == 200
    assert zip_response.headers["content-type"].startswith("application/zip")
    assert (
        f'filename="{job_id}-artifacts.zip"'
        in zip_response.headers["content-disposition"]
    )
    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
        assert set(archive.namelist()) == {"result.txt", "result.srt", "result.vtt"}
        assert archive.read("result.txt") == b"dummy txt"
        assert "result.json" not in archive.namelist()

    events = client.get(f"/api/jobs/{job_id}/events", headers=headers).json()["events"]
    assert any(event["type"] == "created" for event in events)
    assert any(event["status"] == "running" for event in events)
    assert any("fake runner started" in event["message"] for event in events)
    assert any(event["status"] == "succeeded" for event in events)


def test_json_artifact_is_exposed_only_when_requested(tmp_path):
    client, runner, _ = make_client(tmp_path)
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "auto",
            "diarize": "false",
            "output_formats": "txt,json",
        },
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["job_id"]

    response = client.post(f"/api/jobs/{job_id}/start")
    assert response.status_code == 202
    for _ in range(20):
        status = client.get(f"/api/jobs/{job_id}/status").json()
        if status["status"] == "succeeded":
            break
        import time

        time.sleep(0.01)

    results = client.get(f"/api/jobs/{job_id}/results").json()

    assert runner.started == [job_id]
    assert {a["format"] for a in results["artifacts"]} == {"txt", "json"}
    assert client.get(f"/api/jobs/{job_id}/download/result.json").status_code == 200


def test_whisperx_upload_accepts_diarization_speaker_range(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "zh",
            "diarize": "true",
            "min_speakers": "1",
            "max_speakers": "4",
            "output_formats": "txt,srt,vtt,json",
        },
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["diarize"] is True
    assert status["options"]["min_speakers"] == 1
    assert status["options"]["max_speakers"] == 4
    assert status["options"]["output_formats"] == ["txt", "srt", "vtt", "json"]


def test_whisperx_upload_rejects_invalid_speaker_range(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "zh",
            "diarize": "true",
            "min_speakers": "3",
            "max_speakers": "2",
        },
    )

    assert response.status_code == 400
    assert "min_speakers" in response.text


def test_upload_rejects_invalid_whisperx_output_format(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "auto",
            "diarize": "false",
            "output_formats": "txt,log",
        },
    )

    assert response.status_code == 400
    assert "output_formats" in response.text


def test_start_unknown_job_is_rejected_synchronously(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post("/api/jobs/not-a-real-job/start")

    assert response.status_code == 404


def test_default_app_wires_real_job_runner_dispatcher(tmp_path):
    settings = Settings(
        data_root=tmp_path,
        whisperx_model_dir="/models",
    )
    app = create_app(settings=settings)

    runner = app.state.job_service.runner
    assert isinstance(runner, JobRunnerDispatcher)
    assert isinstance(runner.runners["whisperx"], JobStorageWhisperXRunner)
    assert isinstance(runner.runners["pdf"], JobStorageOpenDataLoaderPdfRunner)


def test_whisperx_job_runner_marks_success_and_discovers_artifacts(tmp_path):
    settings = Settings(
        data_root=tmp_path,
        whisperx_model_dir="/models",
    )
    app = create_app(settings=settings)
    dispatcher: JobRunnerDispatcher = app.state.job_service.runner
    runner: JobStorageWhisperXRunner = dispatcher.runners["whisperx"]
    storage = app.state.storage
    manifest = storage.create_job(
        BytesIO(b"audio"), "sample.wav", JobOptions(model="small", language="auto")
    )

    async def fake_run(request, on_log=None):
        assert (
            request.input_path
            == storage.job_dir(manifest.job_id) / "input" / "sample.wav"
        )
        assert request.output_dir == storage.job_dir(manifest.job_id) / "output"
        assert request.options.model == "small"
        (request.output_dir / "result.txt").write_text("ok", encoding="utf-8")
        (request.output_dir / "result.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nok\n", encoding="utf-8"
        )
        (request.output_dir / "ignored.log").write_text(
            "not downloadable", encoding="utf-8"
        )

    runner.run = fake_run

    asyncio.run(runner.start_job(manifest.job_id))

    updated = storage.read_manifest(manifest.job_id)
    assert updated.status == JobStatus.succeeded
    assert {artifact.format for artifact in updated.artifacts} == {"txt", "srt"}


def test_upload_accepts_task_type_pdf(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        data={"task_type": "pdf"},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["input_filename"] == "paper.pdf"
    assert status["options"]["task_type"] == "pdf"
    assert "output_formats" not in status["options"]


def test_upload_rejects_invalid_bool_value_with_route_level_400(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"model": "small", "language": "auto", "diarize": "not_bool"},
    )

    assert response.status_code == 400
    assert "bool" in response.text.lower() or "boolean" in response.text.lower()


def test_upload_rejects_unknown_task_type(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"task_type": "unknown"},
    )

    assert response.status_code == 400
    assert "task_type" in response.text


def test_pdf_upload_defaults_cleanup_strength_balanced(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        data={"task_type": "pdf"},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["markdown_cleanup_strength"] == "balanced"


def test_pdf_upload_normalizes_cleanup_strength_whitespace_lowercase(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        data={"task_type": "pdf", "markdown_cleanup_strength": "  Conservative "},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["markdown_cleanup_strength"] == "conservative"


def test_pdf_upload_rejects_invalid_cleanup_strength_400(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        data={"task_type": "pdf", "markdown_cleanup_strength": "invalid"},
    )

    assert response.status_code == 400
    assert "markdown_cleanup_strength" in response.text


def test_pdf_upload_records_cleanup_strength_in_manifest_options(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        data={"task_type": "pdf", "markdown_cleanup_strength": "aggressive"},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["markdown_cleanup_strength"] == "aggressive"


def test_whisperx_upload_omits_or_ignores_pdf_cleanup_strength(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={
            "model": "small",
            "language": "auto",
            "diarize": "false",
            "markdown_cleanup_strength": "off",
        },
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert "markdown_cleanup_strength" not in status["options"]
    assert status["options"]["task_type"] == "whisperx"


def test_upload_uses_backend_configured_model_when_model_is_omitted(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"language": "auto", "diarize": "false"},
    )

    assert response.status_code == 201, response.text
    status = client.get(f"/api/jobs/{response.json()['job_id']}/status").json()
    assert status["options"]["model"] == "/models/faster-whisper-large-v2"
    assert status["options"]["model_cache_only"] is True


def test_upload_rejects_unconfigured_local_model_path(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("sample.wav", b"abc", "audio/wav")},
        data={"model": "/tmp/other-model", "language": "auto", "diarize": "false"},
    )

    assert response.status_code == 400


def test_download_rejects_traversal_logs_manifest_and_unlisted(tmp_path):
    client, _, _ = make_client(tmp_path)
    job_id = upload(client)

    for path in [
        f"/api/jobs/{job_id}/download/manifest.json",
        f"/api/jobs/{job_id}/download/job.log",
        f"/api/jobs/{job_id}/download/nope.txt",
        f"/api/jobs/{job_id}/download/..%2Fmanifest.json",
    ]:
        response = client.get(path)
        assert response.status_code in {400, 404}, (
            path,
            response.status_code,
            response.text,
        )


def test_cors_allows_local_frontend_dynamic_localhost_ports(tmp_path):
    client, _, _ = make_client(tmp_path)
    origin = "http://localhost:54321"

    response = client.options(
        "/api/config",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
