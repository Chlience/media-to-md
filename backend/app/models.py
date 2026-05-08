from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


SCHEMA_VERSION = 1
ARTIFACT_FORMATS = {
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
DEFAULT_OUTPUT_FORMATS = ["txt", "srt", "vtt"]
DEFAULT_PDF_FORMATS = ["markdown", "text"]
MARKDOWN_CLEANUP_STRENGTHS = {"off", "conservative", "balanced", "aggressive"}
MarkdownCleanupStrength = Literal["off", "conservative", "balanced", "aggressive"]


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class WhisperXJobOptions(BaseModel):
    task_type: Literal["whisperx"] = "whisperx"
    model: str = Field(default="small", min_length=1, max_length=4096)
    language: str | None = Field(default="auto", max_length=32)
    diarize: bool = False
    min_speakers: int | None = Field(default=None, ge=1)
    max_speakers: int | None = Field(default=None, ge=1)
    model_dir: str | None = None
    model_cache_only: bool = False
    output_formats: list[Literal["txt", "srt", "vtt", "json", "md", "markdown"]] = (
        Field(default_factory=lambda: list(DEFAULT_OUTPUT_FORMATS))
    )

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value.lower() == "auto":
            return "auto"
        if any(part in value for part in ("/", "\\", "..")):
            raise ValueError("language must be a code, 'auto', or null")
        return value

    @model_validator(mode="after")
    def validate_speaker_range(self):
        if (
            self.min_speakers is not None
            and self.max_speakers is not None
            and self.min_speakers > self.max_speakers
        ):
            raise ValueError("min_speakers must be <= max_speakers")
        return self

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char in value for char in ("\x00", "\n", "\r")):
            raise ValueError(
                "model must be a model name or backend-configured local path"
            )
        return value

    @field_validator("output_formats")
    @classmethod
    def unique_allowed_formats(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one output format is required")
        seen: list[str] = []
        for fmt in value:
            if fmt not in ARTIFACT_FORMATS:
                raise ValueError(f"unsupported artifact format: {fmt}")
            if fmt not in seen:
                seen.append(fmt)
        return seen


class PdfJobOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: Literal["pdf"] = "pdf"
    format: list[
        Literal[
            "json",
            "text",
            "txt",
            "html",
            "pdf",
            "markdown",
            "md",
            "markdown-with-html",
            "markdown-with-images",
            "tagged-pdf",
        ]
    ] = Field(default_factory=lambda: list(DEFAULT_PDF_FORMATS))
    pages: str | None = Field(default=None, max_length=256)
    table_method: Literal["default", "cluster"] = "default"
    reading_order: Literal["off", "xycut"] = "xycut"
    image_output: Literal["off", "embedded", "external"] = "off"
    image_format: Literal["png", "jpeg"] = "png"
    threads: int = Field(default=1, ge=1)
    markdown_cleanup_strength: MarkdownCleanupStrength = "balanced"

    @field_validator("format")
    @classmethod
    def unique_allowed_formats(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one PDF output format is required")
        seen: list[str] = []
        for fmt in value:
            if fmt not in seen:
                seen.append(fmt)
        return seen

    @field_validator("format", mode="before")
    @classmethod
    def normalize_format(cls, value: Any) -> list[str]:
        if value is None:
            return list(DEFAULT_PDF_FORMATS)
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
        elif isinstance(value, list):
            parts = [str(part).strip() for part in value]
        else:
            raise ValueError("format must be a comma-separated string or list")
        normalized = []
        for part in parts:
            if not part:
                continue
            normalized.append({"md": "markdown", "txt": "text"}.get(part, part))
        return normalized

    @field_serializer("format")
    def serialize_format(self, value: list[str]) -> str:
        return ",".join(value)

    @field_validator("image_output", mode="before")
    @classmethod
    def normalize_image_output(cls, value: Any) -> str:
        if value in (None, "off"):
            return "off"
        text = str(value).strip().lower()
        if text in {"off", "embedded", "external"}:
            return text
        raise ValueError("image_output must be off, embedded, or external")

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if any(char in text for char in ("\x00", "\n", "\r", "/", "\\")):
            raise ValueError("pages must be a single-line page range")
        return text

    @field_validator("markdown_cleanup_strength", mode="before")
    @classmethod
    def normalize_markdown_cleanup_strength(cls, value: Any) -> Any:
        if value is None:
            return "balanced"
        text = str(value).strip().lower()
        if not text:
            return "balanced"
        if text not in {"off", "conservative", "balanced", "aggressive"}:
            raise ValueError(
                "markdown_cleanup_strength must be off, conservative, balanced, or aggressive"
            )
        return text


DiscriminatedJobOptions = Annotated[
    WhisperXJobOptions | PdfJobOptions, Field(discriminator="task_type")
]


def JobOptions(**data: Any) -> WhisperXJobOptions | PdfJobOptions:
    """Construct current job options for tests and runner call sites."""

    if data.get("task_type") == "pdf":
        return PdfJobOptions(**data)
    return WhisperXJobOptions(**data)


class Artifact(BaseModel):
    name: str
    format: Literal[
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
    ]
    path: str
    size_bytes: int = Field(ge=0)

    @field_validator("name", "path")
    @classmethod
    def reject_unsafe_paths(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.split("/") or "\\" in value:
            raise ValueError("artifact paths must be relative and stay within output")
        return value


class JobManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    input_filename: str
    input_size_bytes: int | None = Field(default=None, ge=0)
    input_duration_seconds: float | None = Field(default=None, ge=0)
    options: DiscriminatedJobOptions
    error: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    log_path: str


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus


class JobDeleted(BaseModel):
    job_id: str
    deleted: bool = True


class RuntimePhase(BaseModel):
    code: str
    label: str
    detail: str


class JobStatusResponse(BaseModel):
    job_id: str
    task_type: Literal["whisperx", "pdf"]
    status: JobStatus
    created_at: str
    updated_at: str
    input_filename: str
    input_size_bytes: int | None = Field(default=None, ge=0)
    input_duration_seconds: float | None = Field(default=None, ge=0)
    options: DiscriminatedJobOptions
    error: str | None
    artifacts: list[Artifact]
    log_path: str
    log: str | None = None
    runtime_phase: RuntimePhase | None = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]


class JobEvent(BaseModel):
    timestamp: str
    type: Literal["created", "status", "log", "artifact", "error", "system"]
    message: str
    status: JobStatus | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class JobEventsResponse(BaseModel):
    job_id: str
    events: list[JobEvent]


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=4096)


class AdminAccountUpdateRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=4096)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=4096)


class AdminAccountResponse(BaseModel):
    username: str
    updated_at: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    username: str
    expires_at: int


class JobResultsResponse(BaseModel):
    job_id: str
    task_type: Literal["whisperx", "pdf"]
    status: JobStatus
    input_filename: str | None = None
    input_size_bytes: int | None = Field(default=None, ge=0)
    input_duration_seconds: float | None = Field(default=None, ge=0)
    artifacts: list[Artifact]


class ConfigResponse(BaseModel):
    api_base_url: str | None = None
    whisperx_model: str
    whisperx_model_dir: str | None
    model_cache_only: bool
    nltk_data_dir: str | None = None
    whisperx_args: list[str] = Field(default_factory=list)
    whisperx_args_config: dict[str, Any] = Field(default_factory=dict)
    opendataloader_pdf_args: list[str] = Field(default_factory=list)
    opendataloader_pdf_args_config: dict[str, Any] = Field(default_factory=dict)


class ConfigUpdateRequest(BaseModel):
    api_base_url: str | None = Field(default=None, max_length=4096)
    whisperx_model: str = Field(min_length=1, max_length=4096)
    whisperx_model_dir: str | None = Field(default=None, max_length=4096)
    model_cache_only: bool = False
    nltk_data_dir: str | None = Field(default=None, max_length=4096)
    whisperx_args: dict[str, Any] = Field(default_factory=dict)
    opendataloader_pdf_args: dict[str, Any] = Field(default_factory=dict)

    @field_validator("whisperx_model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("whisperx_model must not be empty")
        if any(char in text for char in ("\x00", "\n", "\r")):
            raise ValueError("config values must be single-line text")
        return text

    @field_validator("api_base_url", "whisperx_model_dir", "nltk_data_dir")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if any(char in text for char in ("\x00", "\n", "\r")):
            raise ValueError("config values must be single-line text")
        return text


class ErrorResponse(BaseModel):
    detail: str | dict[str, Any]
