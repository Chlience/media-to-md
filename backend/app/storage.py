from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from .models import (
    Artifact,
    JobEvent,
    JobManifest,
    DiscriminatedJobOptions,
    JobStatus,
    SCHEMA_VERSION,
)

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "upload").name.strip().replace(" ", "_")
    name = _SAFE_CHARS.sub("_", name).strip("._")
    return name or "upload"


def probe_media_duration_seconds(
    path: Path, timeout_seconds: float = 10
) -> float | None:
    """Return audio/video duration via ffprobe, or None when probing is unavailable."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    duration_lines = result.stdout.strip().splitlines()
    if not duration_lines:
        return None
    try:
        duration = float(duration_lines[0])
    except ValueError:
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


class StorageError(RuntimeError):
    pass


class JobStorage:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()
        self.jobs_root = self.data_root / "jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        if not job_id or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
            raise StorageError("invalid job id")
        path = (self.jobs_root / job_id).resolve()
        if not self._is_relative_to(path, self.jobs_root):
            raise StorageError("job path escapes jobs root")
        return path

    def manifest_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "manifest.json"

    def events_path(self, job_id: str) -> Path:
        return self.resolve_job_relative(job_id, "logs/events.jsonl")

    def create_job(
        self, fileobj: BinaryIO, filename: str, options: DiscriminatedJobOptions
    ) -> JobManifest:
        job_id = uuid.uuid4().hex
        job_dir = self.job_dir(job_id)
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        logs_dir = job_dir / "logs"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        logs_dir.mkdir()

        stored_name = sanitize_filename(filename)
        input_path = input_dir / stored_name
        with input_path.open("wb") as dst:
            shutil.copyfileobj(fileobj, dst)
        input_size_bytes = input_path.stat().st_size
        input_duration_seconds = probe_media_duration_seconds(input_path)
        log_rel = "logs/job.log"
        (job_dir / log_rel).touch()
        now = utc_now()
        manifest = JobManifest(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            status=JobStatus.queued,
            created_at=now,
            updated_at=now,
            input_filename=stored_name,
            input_size_bytes=input_size_bytes,
            input_duration_seconds=input_duration_seconds,
            options=options,
            error=None,
            artifacts=[],
            log_path=log_rel,
        )
        self.write_manifest(manifest)
        self.append_event(
            job_id,
            "created",
            f"任务已创建，输入文件：{stored_name}",
            status=JobStatus.queued,
            data={
                "input_filename": stored_name,
                "input_size_bytes": input_size_bytes,
                "input_duration_seconds": input_duration_seconds,
            },
        )
        return manifest

    def read_manifest(self, job_id: str) -> JobManifest:
        path = self.manifest_path(job_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StorageError("job not found") from exc
        except json.JSONDecodeError as exc:
            raise StorageError("job manifest is invalid JSON") from exc
        return JobManifest.model_validate(data)

    def list_manifests(self) -> list[JobManifest]:
        manifests: list[JobManifest] = []
        for manifest_path in self.jobs_root.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifests.append(JobManifest.model_validate(data))
            except Exception:
                # A single corrupt/incomplete job directory should not make the admin
                # overview unusable. Per-job status still reports validation errors via
                # read_manifest when the job id is known.
                continue
        return sorted(
            manifests, key=lambda item: (item.created_at, item.job_id), reverse=True
        )

    def delete_job(self, job_id: str, *, allow_running: bool = False) -> JobManifest:
        manifest = self.read_manifest(job_id)
        if manifest.status == JobStatus.running and not allow_running:
            raise StorageError("running job cannot be deleted")
        job_dir = self.job_dir(job_id)
        if not self._is_relative_to(job_dir, self.jobs_root):
            raise StorageError("job path escapes jobs root")
        try:
            shutil.rmtree(job_dir)
        except FileNotFoundError as exc:
            raise StorageError("job not found") from exc
        return manifest

    def write_manifest(self, manifest: JobManifest) -> JobManifest:
        updated = manifest.model_copy(update={"updated_at": utc_now()})
        job_dir = self.job_dir(updated.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        path = self.manifest_path(updated.job_id)
        payload = updated.model_dump(mode="json")
        fd, tmp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=job_dir)
        try:
            with open(fd, "w", encoding="utf-8") as tmp:
                json.dump(payload, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
                tmp.flush()
            Path(tmp_name).replace(path)
        finally:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()
        return updated

    def update_manifest(self, job_id: str, **changes) -> JobManifest:
        manifest = self.read_manifest(job_id)
        updated = self.write_manifest(manifest.model_copy(update=changes))
        self._append_manifest_change_events(manifest, updated)
        return updated

    def append_log(self, job_id: str, text: str) -> None:
        manifest = self.read_manifest(job_id)
        log_path = self.resolve_job_relative(job_id, manifest.log_path)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(text)
            if text and not text.endswith("\n"):
                fh.write("\n")
        for line in text.splitlines() or ([text] if text else []):
            line = line.strip()
            if line:
                self.append_event(job_id, "log", line, status=manifest.status)

    def read_log(self, job_id: str, max_bytes: int | None = 65536) -> str:
        log_path = self.log_file(job_id)
        if not log_path.exists():
            return ""
        if max_bytes is None:
            return log_path.read_text(encoding="utf-8", errors="replace")
        with log_path.open("rb") as fh:
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        return data.decode("utf-8", errors="replace")

    def log_file(self, job_id: str) -> Path:
        manifest = self.read_manifest(job_id)
        return self.resolve_job_relative(job_id, manifest.log_path)

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        *,
        status: JobStatus | None = None,
        data: dict | None = None,
    ) -> JobEvent:
        event = JobEvent(
            timestamp=utc_now(),
            type=event_type,
            message=message,
            status=status,
            data=data or {},
        )
        path = self.events_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json())
            fh.write("\n")
        return event

    def read_events(self, job_id: str, max_events: int = 500) -> list[JobEvent]:
        path = self.events_path(job_id)
        events: list[JobEvent] = []
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(JobEvent.model_validate_json(line))
                    except Exception:
                        continue
        return events[-max(1, max_events) :]

    def resolve_job_relative(self, job_id: str, relative_path: str) -> Path:
        if relative_path.startswith(("/", "\\")) or "\\" in relative_path:
            raise StorageError("path must be relative")
        candidate = (self.job_dir(job_id) / relative_path).resolve()
        if not self._is_relative_to(candidate, self.job_dir(job_id)):
            raise StorageError("path escapes job directory")
        return candidate

    def artifact_file(self, job_id: str, artifact_name: str) -> tuple[Artifact, Path]:
        if Path(artifact_name).name != artifact_name or artifact_name in {
            "manifest.json",
            "job.log",
        }:
            raise StorageError("artifact name is not allowed")
        manifest = self.read_manifest(job_id)
        for artifact in manifest.artifacts:
            if artifact.name == artifact_name:
                path = self.resolve_job_relative(job_id, artifact.path)
                output_root = (self.job_dir(job_id) / "output").resolve()
                if not self._is_relative_to(path, output_root):
                    raise StorageError("artifact path is outside output directory")
                if not path.is_file():
                    raise StorageError("artifact file not found")
                return artifact, path
        raise StorageError("artifact is not listed for this job")

    def discover_output_artifacts(self, job_id: str) -> list[Artifact]:
        output_root = self.job_dir(job_id) / "output"
        artifacts: list[Artifact] = []
        allowed_formats = {
            "txt",
            "text",
            "srt",
            "vtt",
            "json",
            "md",
            "markdown",
            "markdown_clear",
            "html",
            "pdf",
            "png",
            "jpeg",
            "jpg",
        }
        for path in sorted(output_root.rglob("*")):
            if not path.is_file():
                continue
            name = path.name.lower()
            fmt = (
                "markdown_clear"
                if name.endswith("_clear.md")
                else path.suffix.lstrip(".").lower()
            )
            if fmt not in allowed_formats:
                continue
            relative_path = path.relative_to(self.job_dir(job_id)).as_posix()
            artifacts.append(
                Artifact(
                    name=path.name,
                    format=fmt,
                    path=relative_path,
                    size_bytes=path.stat().st_size,
                )
            )
        return artifacts

    def reconcile_stale_running(self) -> list[str]:
        changed: list[str] = []
        for manifest_path in self.jobs_root.glob("*/manifest.json"):
            try:
                manifest = JobManifest.model_validate(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
            if manifest.status == JobStatus.running:
                updated = manifest.model_copy(
                    update={
                        "status": JobStatus.failed,
                        "error": "Job was interrupted because the backend restarted while it was running.",
                    }
                )
                self.write_manifest(updated)
                self.append_event(
                    manifest.job_id,
                    "error",
                    "后端重启时发现任务仍处于运行中，已标记为失败。",
                    status=JobStatus.failed,
                    data={
                        "old_status": manifest.status,
                        "new_status": JobStatus.failed,
                    },
                )
                changed.append(manifest.job_id)
        return changed

    def _append_manifest_change_events(
        self, before: JobManifest, after: JobManifest
    ) -> None:
        if before.status != after.status:
            self.append_event(
                after.job_id,
                "status",
                f"状态从 {before.status.value} 变更为 {after.status.value}",
                status=after.status,
                data={
                    "old_status": before.status.value,
                    "new_status": after.status.value,
                },
            )
        if after.error and after.error != before.error:
            self.append_event(after.job_id, "error", after.error, status=after.status)
        if len(after.artifacts) > len(before.artifacts):
            self.append_event(
                after.job_id,
                "artifact",
                f"发现 {len(after.artifacts)} 个输出文件。",
                status=after.status,
                data={"artifact_count": len(after.artifacts)},
            )

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
