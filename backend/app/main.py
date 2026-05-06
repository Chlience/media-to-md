from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.routes import router
from .auth import AdminAuthService
from .config import Settings, get_settings
from .jobs import JobService, build_job_runner
from .storage import JobStorage


async def _validation_error_as_bad_request(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = "Invalid request value"
    errors = exc.errors()
    if errors:
        detail = errors[0].get("msg") or detail
    return JSONResponse(status_code=400, content={"detail": detail})


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
    app.include_router(router)
    return app


app = create_app()
