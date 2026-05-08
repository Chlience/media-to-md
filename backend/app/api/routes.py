from __future__ import annotations

import asyncio
import io
from typing import Annotated
import zipfile

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response

from ..auth import AdminAuthService, AuthError
from ..config import (
    Settings,
    get_settings,
    normalize_opendataloader_pdf_args,
    normalize_opendataloader_pdf_args_config,
    normalize_whisperx_args,
    write_backend_config_update,
)
from ..jobs import JobRunnerDispatcher, JobService, build_job_runner
from ..models import (
    AdminAccountResponse,
    AdminAccountUpdateRequest,
    AdminLoginRequest,
    AdminTokenResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    DEFAULT_OUTPUT_FORMATS,
    JobCreated,
    JobDeleted,
    JobEventsResponse,
    JobListResponse,
    JobManifest,
    JobOptions,
    JobStatus,
    MARKDOWN_CLEANUP_STRENGTHS,
    PdfJobOptions,
    JobResultsResponse,
    JobStatusResponse,
    RuntimePhase,
)
from ..storage import JobStorage, StorageError
from ..whisperx_runner import ALLOWED_MODELS, JobStorageWhisperXRunner

router = APIRouter(prefix="/api")


def get_storage(request: Request) -> JobStorage:
    return request.app.state.storage


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


def get_auth_service(request: Request) -> AdminAuthService:
    return request.app.state.auth_service


def _storage_error(exc: StorageError) -> HTTPException:
    detail = str(exc)
    status = 404 if "not found" in detail else 400
    return HTTPException(status_code=status, detail=detail)


def _auth_error(exc: AuthError) -> HTTPException:
    detail = str(exc)
    if "not configured" in detail:
        return HTTPException(status_code=503, detail=detail)
    if "incorrect" in detail or "invalid" in detail or "expired" in detail:
        return HTTPException(status_code=401, detail=detail)
    return HTTPException(status_code=400, detail=detail)


def _session_response(session) -> AdminTokenResponse:
    return AdminTokenResponse(
        access_token=session.token,
        username=session.username,
        expires_at=session.expires_at,
    )


def require_admin(
    auth: Annotated[AdminAuthService, Depends(get_auth_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="admin bearer token is required")
    try:
        return auth.verify_token(authorization.split(" ", 1)[1].strip())
    except AuthError as exc:
        raise _auth_error(exc) from exc


_WHISPERX_PHASE_LABELS: dict[str, tuple[str, str]] = {
    "queued": ("等待启动", "任务已创建，等待后端启动转写。"),
    "starting": ("启动转写进程", "后端已接收任务，正在启动 WhisperX。"),
    "model": ("加载模型与参数", "WhisperX 正在初始化模型、设备和语言设置。"),
    "vad": ("语音活动检测", "正在识别音频中的有效语音片段。"),
    "transcription": ("语音转文字", "正在把语音片段转写为文本。"),
    "alignment": ("时间戳对齐", "正在对齐词级/片段级时间戳并整理字幕。"),
    "diarization": ("说话人分离", "正在为片段和词级结果分配说话人标签。"),
    "finalizing": ("整理输出文件", "转写已完成，正在写入并收集可下载产物。"),
    "succeeded": ("已完成", "任务已成功完成，可下载输出文件。"),
    "failed": ("失败", "任务失败，请进入管理员页面查看错误详情和日志。"),
    "cancelled": ("已取消", "任务已取消。"),
}


def _phase(code: str) -> RuntimePhase:
    label, detail = _WHISPERX_PHASE_LABELS[code]
    return RuntimePhase(code=code, label=label, detail=detail)


def _whisperx_runtime_phase(
    manifest: JobManifest, storage: JobStorage
) -> RuntimePhase | None:
    if manifest.options.task_type != "whisperx":
        return None
    if manifest.status == JobStatus.queued:
        return _phase("queued")
    if manifest.status == JobStatus.succeeded:
        return _phase("succeeded")
    if manifest.status == JobStatus.failed:
        return _phase("failed")
    if manifest.status == JobStatus.cancelled:
        return _phase("cancelled")

    log = storage.read_log(manifest.job_id).lower()
    if "performing diarization" in log:
        return _phase("diarization")
    if "performing alignment" in log:
        return _phase("alignment")
    if (
        "transcript: [" in log
        or "detected language:" in log
        or "performing transcription" in log
    ):
        return _phase("transcription")
    if "performing voice activity detection" in log:
        return _phase("vad")
    if "compute type" in log or "no language specified" in log:
        return _phase("model")
    if log.strip():
        return _phase("starting")
    return _phase("starting")


def _job_status_response(
    manifest: JobManifest, storage: JobStorage, *, include_log: bool
) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=manifest.job_id,
        task_type=manifest.options.task_type,
        status=manifest.status,
        created_at=manifest.created_at,
        updated_at=manifest.updated_at,
        input_filename=manifest.input_filename,
        input_size_bytes=manifest.input_size_bytes,
        input_duration_seconds=manifest.input_duration_seconds,
        options=manifest.options,
        error=manifest.error,
        artifacts=manifest.artifacts,
        log_path=manifest.log_path,
        log=storage.read_log(manifest.job_id) if include_log else None,
        runtime_phase=_whisperx_runtime_phase(manifest, storage),
    )


def _normalize_whisperx_output_formats(value: str | None) -> list[str]:
    if value is None:
        return list(DEFAULT_OUTPUT_FORMATS)
    parts = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not parts:
        return list(DEFAULT_OUTPUT_FORMATS)
    allowed = {"txt", "srt", "vtt", "json"}
    invalid = sorted(set(parts) - allowed)
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"output_formats contains unsupported WhisperX format(s): {', '.join(invalid)}.",
        )
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return seen


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config", response_model=ConfigResponse)
def read_config(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _: Annotated[str, Depends(require_admin)],
) -> ConfigResponse:
    return _config_response(settings)


@router.get("/admin/config", response_model=ConfigResponse)
def read_admin_config(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _: Annotated[str, Depends(require_admin)],
) -> ConfigResponse:
    return _config_response(settings)


def _config_response(settings: Settings) -> ConfigResponse:
    opendataloader_pdf_argv = list(settings.opendataloader_pdf_args)
    opendataloader_pdf_config = dict(settings.opendataloader_pdf_args_config)
    if not opendataloader_pdf_config:
        opendataloader_pdf_config = normalize_opendataloader_pdf_args_config({})
    return ConfigResponse(
        api_base_url=settings.api_base_url,
        whisperx_model=settings.whisperx_model,
        whisperx_model_dir=settings.whisperx_model_dir,
        model_cache_only=settings.model_cache_only,
        nltk_data_dir=settings.nltk_data_dir,
        whisperx_args=list(settings.whisperx_args),
        whisperx_args_config=dict(settings.whisperx_args_config),
        opendataloader_pdf_args=opendataloader_pdf_argv,
        opendataloader_pdf_args_config=opendataloader_pdf_config,
    )


@router.put("/admin/config", response_model=ConfigResponse)
def update_config(
    update: ConfigUpdateRequest,
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> ConfigResponse:
    try:
        normalize_whisperx_args(update.whisperx_args)
        normalize_opendataloader_pdf_args(update.opendataloader_pdf_args)
        normalized_pdf_args_config = normalize_opendataloader_pdf_args_config(
            update.opendataloader_pdf_args
        )
        write_backend_config_update(
            {
                "whisperx_model": update.whisperx_model,
                "api_base_url": update.api_base_url,
                "whisperx_model_dir": update.whisperx_model_dir,
                "model_cache_only": update.model_cache_only,
                "nltk_data_dir": update.nltk_data_dir,
                "whisperx_args": update.whisperx_args,
                "opendataloader_pdf_args": normalized_pdf_args_config,
            }
        )
        settings = get_settings()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.app.state.settings = settings
    if isinstance(
        request.app.state.job_service.runner,
        (JobStorageWhisperXRunner, JobRunnerDispatcher),
    ):
        request.app.state.job_service.runner = build_job_runner(
            request.app.state.storage, settings
        )
    return _config_response(settings)


@router.post("/admin/login", response_model=AdminTokenResponse)
def admin_login(
    request: AdminLoginRequest,
    auth: Annotated[AdminAuthService, Depends(get_auth_service)],
) -> AdminTokenResponse:
    try:
        account = auth.read_account()
        if request.username != account.username or not auth.verify_password(
            request.password
        ):
            raise AuthError("invalid admin username or password")
        return _session_response(auth.issue_token(account.username))
    except AuthError as exc:
        raise _auth_error(exc) from exc


@router.get("/admin/account", response_model=AdminAccountResponse)
def admin_account(
    _: Annotated[str, Depends(require_admin)],
    auth: Annotated[AdminAuthService, Depends(get_auth_service)],
) -> AdminAccountResponse:
    try:
        account = auth.read_account()
        return AdminAccountResponse(
            username=account.username, updated_at=account.updated_at
        )
    except AuthError as exc:
        raise _auth_error(exc) from exc


@router.put("/admin/account", response_model=AdminTokenResponse)
def update_admin_account(
    request: AdminAccountUpdateRequest,
    _: Annotated[str, Depends(require_admin)],
    auth: Annotated[AdminAuthService, Depends(get_auth_service)],
) -> AdminTokenResponse:
    try:
        return _session_response(
            auth.update_account(
                current_password=request.current_password,
                username=request.username,
                new_password=request.new_password,
            )
        )
    except AuthError as exc:
        raise _auth_error(exc) from exc


@router.post("/jobs/upload", response_model=JobCreated, status_code=201)
async def upload_job(
    service: Annotated[JobService, Depends(get_job_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    file: UploadFile = File(...),
    model: str | None = Form(None),
    language: str | None = Form("auto"),
    diarize: bool = Form(False),
    min_speakers: int | None = Form(None),
    max_speakers: int | None = Form(None),
    model_cache_only: bool | None = Form(None),
    output_formats: str | None = Form(None),
    task_type: str = Form("whisperx"),
    markdown_cleanup_strength: str | None = Form(None),
) -> JobCreated:
    task_type = task_type.strip().lower()
    if task_type not in {"whisperx", "pdf"}:
        raise HTTPException(
            status_code=400, detail="task_type must be 'whisperx' or 'pdf'."
        )
    if task_type == "pdf":
        if output_formats is not None:
            raise HTTPException(
                status_code=400,
                detail="output_formats is only supported for WhisperX tasks.",
            )
        cleanup_strength = (
            markdown_cleanup_strength or ""
        ).strip().lower() or "balanced"
        if cleanup_strength not in MARKDOWN_CLEANUP_STRENGTHS:
            raise HTTPException(
                status_code=400,
                detail="markdown_cleanup_strength must be one of: off, conservative, balanced, aggressive.",
            )
        options = PdfJobOptions(markdown_cleanup_strength=cleanup_strength)
        manifest = service.create_job(file.file, file.filename or "upload", options)
        return JobCreated(job_id=manifest.job_id, status=manifest.status)

    selected_model = (model or "").strip() or settings.whisperx_model
    if (
        selected_model not in ALLOWED_MODELS
        and selected_model != settings.whisperx_model
    ):
        raise HTTPException(
            status_code=400,
            detail="Model must be a known WhisperX model or the backend-configured local model path.",
        )
    try:
        options = JobOptions(
            task_type="whisperx",
            model=selected_model,
            language=language,
            diarize=diarize,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            model_dir=settings.whisperx_model_dir,
            model_cache_only=settings.model_cache_only
            if model_cache_only is None
            else model_cache_only,
            output_formats=_normalize_whisperx_output_formats(output_formats),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manifest = service.create_job(file.file, file.filename or "upload", options)
    return JobCreated(job_id=manifest.job_id, status=manifest.status)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    storage: Annotated[JobStorage, Depends(get_storage)],
    _: Annotated[str, Depends(require_admin)],
    include_log: bool = False,
) -> JobListResponse:
    return JobListResponse(
        jobs=[
            _job_status_response(manifest, storage, include_log=include_log)
            for manifest in storage.list_manifests()
        ]
    )


@router.post("/jobs/{job_id}/start", status_code=202)
async def start_job(
    job_id: str, service: Annotated[JobService, Depends(get_job_service)]
) -> dict[str, str]:
    try:
        service.storage.read_manifest(job_id)
        # The runner owns execution; API schedules it and returns without blocking the request path.
        asyncio.create_task(service.start_job(job_id))
    except StorageError as exc:
        raise _storage_error(exc) from exc
    return {"job_id": job_id, "status": "accepted"}


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def job_status(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
    include_log: bool = False,
) -> JobStatusResponse:
    try:
        manifest = storage.read_manifest(job_id)
        return _job_status_response(manifest, storage, include_log=False)
    except StorageError as exc:
        raise _storage_error(exc) from exc


@router.get("/jobs/{job_id}/logs")
def job_logs(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, str]:
    try:
        return {"job_id": job_id, "log": storage.read_log(job_id)}
    except StorageError as exc:
        raise _storage_error(exc) from exc


@router.get("/jobs/{job_id}/logs/download")
def download_job_log(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
    _: Annotated[str, Depends(require_admin)],
) -> FileResponse:
    try:
        log_path = storage.log_file(job_id)
        if not log_path.is_file():
            raise HTTPException(status_code=404, detail="log file not found")
        return FileResponse(
            log_path,
            media_type="text/plain; charset=utf-8",
            filename="job.log",
        )
    except StorageError as exc:
        raise _storage_error(exc) from exc


@router.get("/jobs/{job_id}/events", response_model=JobEventsResponse)
def job_events(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
    _: Annotated[str, Depends(require_admin)],
    limit: int = 500,
) -> JobEventsResponse:
    try:
        bounded_limit = min(max(limit, 1), 2000)
        return JobEventsResponse(
            job_id=job_id, events=storage.read_events(job_id, bounded_limit)
        )
    except StorageError as exc:
        raise _storage_error(exc) from exc


@router.delete("/jobs/{job_id}", response_model=JobDeleted)
def delete_job(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
    _: Annotated[str, Depends(require_admin)],
) -> JobDeleted:
    try:
        deleted = storage.delete_job(job_id)
        return JobDeleted(job_id=deleted.job_id)
    except StorageError as exc:
        if "running job cannot be deleted" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="Running jobs cannot be deleted. Wait until the task finishes before deleting its files.",
            ) from exc
        raise _storage_error(exc) from exc


@router.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
def job_results(
    job_id: str, storage: Annotated[JobStorage, Depends(get_storage)]
) -> JobResultsResponse:
    try:
        manifest = storage.read_manifest(job_id)
        return JobResultsResponse(
            job_id=manifest.job_id,
            task_type=manifest.options.task_type,
            status=manifest.status,
            input_filename=manifest.input_filename,
            input_size_bytes=manifest.input_size_bytes,
            input_duration_seconds=manifest.input_duration_seconds,
            artifacts=manifest.artifacts,
        )
    except StorageError as exc:
        raise _storage_error(exc) from exc


def _artifact_zip_arcname(artifact_path: str) -> str:
    arcname = artifact_path.removeprefix("output/")
    if not arcname or arcname.startswith(("/", "\\")) or "\\" in arcname:
        raise StorageError("artifact path is not allowed")
    if ".." in arcname.split("/"):
        raise StorageError("artifact path escapes output directory")
    return arcname


@router.get("/jobs/{job_id}/artifacts.zip")
def download_artifacts_zip(
    job_id: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
) -> Response:
    try:
        manifest = storage.read_manifest(job_id)
        if not manifest.artifacts:
            raise HTTPException(status_code=404, detail="no artifacts available")

        output_root = (storage.job_dir(job_id) / "output").resolve()
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact in manifest.artifacts:
                path = storage.resolve_job_relative(job_id, artifact.path)
                try:
                    path.resolve().relative_to(output_root)
                except ValueError as exc:
                    raise StorageError("artifact path is outside output directory") from exc
                if not path.is_file():
                    raise StorageError("artifact file not found")
                archive.write(path, _artifact_zip_arcname(artifact.path))

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{manifest.job_id}-artifacts.zip"'
            },
        )
    except StorageError as exc:
        raise _storage_error(exc) from exc


@router.get("/jobs/{job_id}/download/{artifact_name}")
def download_artifact(
    job_id: str,
    artifact_name: str,
    storage: Annotated[JobStorage, Depends(get_storage)],
) -> FileResponse:
    try:
        artifact, path = storage.artifact_file(job_id, artifact_name)
        return FileResponse(path, filename=artifact.name)
    except StorageError as exc:
        raise _storage_error(exc) from exc
