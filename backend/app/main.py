from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.routes import router
from .auth import AdminAuthService
from .config import Settings, get_settings, upload_limit_bytes_for_task_type
from .jobs import JobService, build_job_runner
from .storage import JobStorage

UPLOAD_PREFLIGHT_PATH = "/api/jobs/upload"
MULTIPART_CONTENT_LENGTH_OVERHEAD_BYTES = 1024 * 1024


async def _validation_error_as_bad_request(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = "Invalid request value"
    errors = exc.errors()
    if errors:
        detail = errors[0].get("msg") or detail
    return JSONResponse(status_code=400, content={"detail": detail})


def _parse_positive_int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value.strip())
    except (AttributeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _upload_too_large_response(detail: str) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": detail})


def create_app(settings: Settings | None = None, runner=None) -> FastAPI:
    settings = settings or get_settings()
    storage = JobStorage(settings.data_root)
    storage.reconcile_stale_running()

    app = FastAPI(title="Media-to-MD API")
    app.state.settings = settings
    app.state.storage = storage
    app.state.auth_service = AdminAuthService.from_settings(settings)
    app.state.job_service = JobService(
        storage,
        runner=runner or build_job_runner(storage, settings),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(RequestValidationError, _validation_error_as_bad_request)

    @app.middleware("http")
    async def reject_oversized_uploads_from_headers(request: Request, call_next):
        if (
            request.method.upper() == "POST"
            and request.url.path == UPLOAD_PREFLIGHT_PATH
        ):
            current_settings: Settings = request.app.state.settings
            task_type = (
                request.headers.get("x-media-to-md-task-type") or "whisperx"
            ).strip().lower()
            if task_type in {"whisperx", "pdf"}:
                declared_file_size = _parse_positive_int_header(
                    request.headers.get("x-media-to-md-file-size")
                )
                limit_bytes = upload_limit_bytes_for_task_type(
                    current_settings, task_type
                )
                if declared_file_size is not None and declared_file_size > limit_bytes:
                    return _upload_too_large_response(
                        "uploaded file exceeds configured limit: "
                        f"max {limit_bytes} bytes, declared {declared_file_size} bytes"
                    )

            content_length = _parse_positive_int_header(
                request.headers.get("content-length")
            )
            if content_length is not None:
                max_limit_bytes = max(
                    current_settings.max_whisperx_upload_bytes,
                    current_settings.max_pdf_upload_bytes,
                )
                if (
                    content_length
                    > max_limit_bytes + MULTIPART_CONTENT_LENGTH_OVERHEAD_BYTES
                ):
                    return _upload_too_large_response(
                        "request body exceeds configured upload limits"
                    )

        return await call_next(request)

    app.include_router(router)
    return app


app = create_app()
