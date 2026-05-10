from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_JSON_PATH = BACKEND_ROOT / "config.json"
WHISPERX_ARGS_ENV = "WHISPERX_ARGS_JSON"
OPENDATALOADER_PDF_ARGS_ENV = "OPENDATALOADER_PDF_ARGS_JSON"
WHISPERX_BACKENDS = {"cli", "openai"}

_CONFIG_ARG_SPECS: dict[str, dict[str, Any]] = {
    "batch_size": {"flag": "--batch_size", "type": "int", "min": 1},
    "device": {"flag": "--device", "type": "str", "choices": {"cpu", "cuda"}},
    "device_index": {"flag": "--device_index", "type": "int", "min": 0},
    "compute_type": {
        "flag": "--compute_type",
        "type": "str",
        "choices": {"default", "float16", "float32", "int8"},
    },
    "threads": {"flag": "--threads", "type": "int", "min": 0},
    "chunk_size": {"flag": "--chunk_size", "type": "int", "min": 1},
    "vad_method": {
        "flag": "--vad_method",
        "type": "str",
        "choices": {"pyannote", "silero"},
    },
    "vad_onset": {"flag": "--vad_onset", "type": "float", "min": 0},
    "vad_offset": {"flag": "--vad_offset", "type": "float", "min": 0},
    "align_model": {"flag": "--align_model", "type": "safe_str"},
    "diarize_model": {"flag": "--diarize_model", "type": "safe_str"},
    "min_speakers": {"flag": "--min_speakers", "type": "int", "min": 1},
    "max_speakers": {"flag": "--max_speakers", "type": "int", "min": 1},
    "speaker_embeddings": {"flag": "--speaker_embeddings", "type": "flag"},
    "no_align": {"flag": "--no_align", "type": "flag"},
}

_PDF_CONFIG_ARG_SPECS: dict[str, dict[str, Any]] = {
    "format": {
        "flag": "--format",
        "type": "csv_str",
        "choices": {
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
        },
        "default": ("markdown", "text"),
    },
    "pages": {"flag": "--pages", "type": "safe_str"},
    "threads": {"flag": "--threads", "type": "int", "min": 1, "default": 1},
    "image_output": {
        "flag": "--image-output",
        "type": "str",
        "choices": {"off", "embedded", "external"},
        "default": "off",
    },
    "image_format": {
        "flag": "--image-format",
        "type": "str",
        "choices": {"png", "jpeg"},
        "default": "png",
    },
    "table_method": {
        "flag": "--table-method",
        "type": "str",
        "choices": {"default", "cluster"},
        "default": "default",
    },
    "reading_order": {
        "flag": "--reading-order",
        "type": "str",
        "choices": {"off", "xycut"},
        "default": "xycut",
    },
    "hybrid": {
        "flag": "--hybrid",
        "type": "str",
        "choices": {"off", "docling-fast", "hancom-ai"},
        "skip_values": {"off"},
    },
    "hybrid_mode": {
        "flag": "--hybrid-mode",
        "type": "str",
        "choices": {"auto", "full"},
    },
    "hybrid_timeout": {"flag": "--hybrid-timeout", "type": "int", "min": 0},
}



@dataclass(frozen=True)
class Settings:
    data_root: Path
    whisperx_model_dir: str | None
    whisperx_model: str = "small"
    whisperx_backend: str = "cli"
    whisperx_openai_base_url: str | None = None
    whisperx_openai_api_key: str | None = None
    whisperx_openai_timeout_seconds: float = 3600.0
    api_base_url: str | None = None
    model_cache_only: bool = False
    nltk_data_dir: str | None = None
    whisperx_args: tuple[str, ...] = ()
    whisperx_args_config: dict[str, Any] = field(default_factory=dict)
    opendataloader_pdf_args: tuple[str, ...] = ()
    opendataloader_pdf_args_config: dict[str, Any] = field(default_factory=dict)
    admin_username: str | None = None
    admin_password: str | None = None

    @property
    def jobs_root(self) -> Path:
        return self.data_root / "jobs"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bool_config(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_whisperx_backend(value: Any) -> str:
    text = (str(value).strip().lower() if value is not None else "cli")
    if text in {"api", "openai_api", "openai-compatible", "openai_compatible"}:
        text = "openai"
    if text not in WHISPERX_BACKENDS:
        allowed = ", ".join(sorted(WHISPERX_BACKENDS))
        raise ValueError(f"whisperx_backend must be one of: {allowed}")
    return text


def _positive_float(value: Any, name: str, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if number <= 0:
        raise ValueError(f"{name} must be a positive number")
    return number


def _normalize_arg_name(name: str) -> str:
    return name.strip().removeprefix("--").replace("-", "_")


def _safe_arg_text(value: Any, name: str) -> str:
    text = str(value)
    if not text or any(char in text for char in ("\x00", "\n", "\r")):
        raise ValueError(f"whisperx_args.{name} must be a non-empty single-line value")
    return text


def _safe_pdf_arg_text(value: Any, name: str, *, allow_newline: bool = False) -> str:
    text = str(value)
    unsafe_chars = ("\x00",) if allow_newline else ("\x00", "\n", "\r")
    if not text or any(char in text for char in unsafe_chars):
        raise ValueError(
            f"opendataloader_pdf_args.{name} must be a non-empty safe text value"
        )
    return text



def _coerce_int(value: Any, name: str, minimum: int | None = None) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"whisperx_args.{name} must be an integer") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"whisperx_args.{name} must be >= {minimum}")
    return str(number)


def _coerce_float(value: Any, name: str, minimum: float | None = None) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"whisperx_args.{name} must be a number") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"whisperx_args.{name} must be >= {minimum:g}")
    return f"{number:g}"


def _coerce_bool_value(value: Any, name: str) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str) and value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "0",
        "false",
        "no",
        "off",
    }:
        return "True" if _bool_config(value) else "False"
    raise ValueError(f"whisperx_args.{name} must be a boolean")


def _coerce_pdf_bool_text(value: Any, name: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "0",
        "false",
        "no",
        "off",
    }:
        return "true" if _bool_config(value) else "false"
    raise ValueError(f"opendataloader_pdf_args.{name} must be a boolean")


def _coerce_csv_int(value: Any, name: str) -> str:
    if isinstance(value, list):
        parts = [_coerce_int(item, name) for item in value]
    else:
        parts = [part.strip() for part in str(value).split(",")]
        for part in parts:
            if part:
                _coerce_int(part, name)
    if not parts or any(part == "" for part in parts):
        raise ValueError(f"whisperx_args.{name} must be comma-separated integers")
    return ",".join(parts)


def _coerce_config_arg_value(name: str, value: Any, spec: dict[str, Any]) -> str | None:
    kind = spec["type"]
    if kind == "flag":
        if isinstance(value, bool):
            return None if value else ""
        if isinstance(value, str) and value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "0",
            "false",
            "no",
            "off",
        }:
            return None if _bool_config(value) else ""
        raise ValueError(f"whisperx_args.{name} must be a boolean")
    if kind == "bool_value":
        return _coerce_bool_value(value, name)
    if kind == "int":
        return _coerce_int(value, name, spec.get("min"))
    if kind == "float":
        return _coerce_float(value, name, spec.get("min"))
    if kind == "csv_int":
        return _coerce_csv_int(value, name)

    text = _safe_arg_text(value, name)
    choices = spec.get("choices")
    if choices is not None and text not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"whisperx_args.{name} must be one of: {allowed}")
    return text


def _coerce_pdf_config_arg_value(
    name: str, value: Any, spec: dict[str, Any]
) -> str | None:
    kind = spec["type"]
    if kind == "flag":
        if isinstance(value, bool):
            return None if value else ""
        if isinstance(value, str) and value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "0",
            "false",
            "no",
            "off",
        }:
            return None if _bool_config(value) else ""
        raise ValueError(f"opendataloader_pdf_args.{name} must be a boolean")
    if kind == "bool_text":
        return _coerce_pdf_bool_text(value, name)
    if kind == "int":
        number = _coerce_int(value, name, spec.get("min"))
        maximum = spec.get("max")
        if maximum is not None and int(number) > maximum:
            raise ValueError(f"opendataloader_pdf_args.{name} must be <= {maximum}")
        return number
    if kind == "csv_str":
        raw_parts = value if isinstance(value, list) else str(value).split(",")
        parts = [str(part).strip() for part in raw_parts]
        choices = spec["choices"]
        if not parts or any(not part for part in parts):
            raise ValueError(f"opendataloader_pdf_args.{name} must not be empty")
        for part in parts:
            if part not in choices:
                allowed = ", ".join(sorted(choices))
                raise ValueError(
                    f"opendataloader_pdf_args.{name} must contain only: {allowed}"
                )
        return ",".join(dict.fromkeys(parts))
    if kind == "safe_text":
        return _safe_pdf_arg_text(value, name, allow_newline=True)
    text = _safe_pdf_arg_text(value, name)
    choices = spec.get("choices")
    if choices is not None and text not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"opendataloader_pdf_args.{name} must be one of: {allowed}")
    if text in spec.get("skip_values", set()):
        return ""
    return text


def normalize_whisperx_args(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ValueError("whisperx_args must be a JSON object")

    argv: list[str] = []
    speaker_counts: dict[str, int] = {}
    for raw_name, raw_value in value.items():
        name = _normalize_arg_name(str(raw_name))
        spec = _CONFIG_ARG_SPECS.get(name)
        if spec is None:
            allowed = ", ".join(sorted(_CONFIG_ARG_SPECS))
            raise ValueError(
                f"Unsupported whisperx_args key '{raw_name}'. Allowed keys: {allowed}"
            )
        coerced = _coerce_config_arg_value(name, raw_value, spec)
        if coerced == "":
            continue
        if name in {"min_speakers", "max_speakers"}:
            speaker_counts[name] = int(coerced)
        argv.append(spec["flag"])
        if coerced is not None:
            argv.append(coerced)
    if (
        "min_speakers" in speaker_counts
        and "max_speakers" in speaker_counts
        and speaker_counts["min_speakers"] > speaker_counts["max_speakers"]
    ):
        raise ValueError("whisperx_args.min_speakers must be <= max_speakers")
    return tuple(argv)


def normalize_opendataloader_pdf_args(value: Any) -> tuple[str, ...]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("opendataloader_pdf_args must be a JSON object")

    normalized: dict[str, Any] = {}
    for raw_name, raw_value in value.items():
        name = _normalize_arg_name(str(raw_name))
        if name not in _PDF_CONFIG_ARG_SPECS:
            allowed = ", ".join(sorted(_PDF_CONFIG_ARG_SPECS))
            raise ValueError(
                f"Unsupported opendataloader_pdf_args key '{raw_name}'. "
                f"Allowed keys: {allowed}"
            )
        normalized[name] = raw_value

    normalized.setdefault("format", list(_PDF_CONFIG_ARG_SPECS["format"]["default"]))
    normalized.setdefault("image_output", _PDF_CONFIG_ARG_SPECS["image_output"]["default"])

    argv: list[str] = []
    for name in sorted(normalized):
        spec = _PDF_CONFIG_ARG_SPECS[name]
        coerced = _coerce_pdf_config_arg_value(name, normalized[name], spec)
        if coerced == "":
            continue
        argv.append(spec["flag"])
        if coerced is not None:
            argv.append(coerced)
    return tuple(argv)


def normalize_opendataloader_pdf_args_config(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("opendataloader_pdf_args must be a JSON object")

    normalized: dict[str, Any] = {}
    for raw_name, raw_value in value.items():
        name = _normalize_arg_name(str(raw_name))
        spec = _PDF_CONFIG_ARG_SPECS.get(name)
        if spec is None:
            allowed = ", ".join(sorted(_PDF_CONFIG_ARG_SPECS))
            raise ValueError(
                f"Unsupported opendataloader_pdf_args key '{raw_name}'. "
                f"Allowed keys: {allowed}"
            )
        coerced = _coerce_pdf_config_arg_value(name, raw_value, spec)
        if coerced == "":
            normalized[name] = "false" if spec["type"] == "flag" else raw_value
        elif coerced is None:
            normalized[name] = "true"
        else:
            normalized[name] = coerced

    normalized.setdefault("format", ",".join(_PDF_CONFIG_ARG_SPECS["format"]["default"]))
    normalized.setdefault("image_output", _PDF_CONFIG_ARG_SPECS["image_output"]["default"])
    return normalized


def _whisperx_args_config(config: dict[str, Any]) -> Any:
    env_value = os.getenv(WHISPERX_ARGS_ENV)
    if env_value:
        try:
            return json.loads(env_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{WHISPERX_ARGS_ENV} must be valid JSON") from exc
    return config.get("whisperx_args")


def _opendataloader_pdf_args_config(config: dict[str, Any]) -> Any:
    env_value = os.getenv(OPENDATALOADER_PDF_ARGS_ENV)
    if env_value:
        try:
            return json.loads(env_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{OPENDATALOADER_PDF_ARGS_ENV} must be valid JSON") from exc
    return config.get("opendataloader_pdf_args")


def _resolve_config_path() -> Path | None:
    configured = os.getenv("WHISPERX_CONFIG_FILE")
    if configured == "":
        return None
    return (
        Path(configured).expanduser().resolve()
        if configured
        else DEFAULT_CONFIG_JSON_PATH
    )


def load_backend_config() -> dict[str, Any]:
    """Load backend/config.json.

    Set WHISPERX_CONFIG_FILE to an alternate JSON path. Set it to an empty
    string to disable config-file loading. Environment variables still override
    values loaded from JSON.
    """

    path = _resolve_config_path()
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"backend config JSON is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"backend config JSON must be an object: {path}")
    return data


def write_backend_config_update(updates: dict[str, Any]) -> None:
    """Merge editable backend settings into backend/config.json atomically."""

    path = _resolve_config_path()
    if path is None:
        raise ValueError("backend config JSON loading is disabled")

    config = load_backend_config()
    for key, value in updates.items():
        config[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fileobj:
            json.dump(config, fileobj, ensure_ascii=False, indent=2)
            fileobj.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _resolve_path(value: str, base_dir: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def get_settings() -> Settings:
    config_path = _resolve_config_path()
    config = load_backend_config()
    config_base = config_path.parent if config_path is not None else None

    env_data_root = os.getenv("WHISPERX_DATA_ROOT")
    config_data_root = _optional_str(config.get("data_root"))
    if env_data_root:
        data_root = _resolve_path(env_data_root)
    elif config_data_root:
        data_root = _resolve_path(config_data_root, config_base)
    else:
        data_root = _resolve_path("./data")

    env_model_dir = os.getenv("WHISPERX_MODEL_DIR")
    config_model_dir = _optional_str(config.get("whisperx_model_dir"))
    if env_model_dir:
        model_dir = str(_resolve_path(env_model_dir))
    elif config_model_dir:
        model_dir = str(_resolve_path(config_model_dir, config_base))
    else:
        model_dir = None

    model = (
        os.getenv("WHISPERX_MODEL")
        or _optional_str(config.get("whisperx_model"))
        or "small"
    ).strip()
    if not model:
        raise ValueError("WHISPERX_MODEL must not be empty")

    whisperx_backend = _normalize_whisperx_backend(
        os.getenv("WHISPERX_BACKEND")
        or _optional_str(config.get("whisperx_backend"))
        or "cli"
    )
    whisperx_openai_base_url = (
        os.getenv("WHISPERX_OPENAI_BASE_URL")
        or _optional_str(config.get("whisperx_openai_base_url"))
        or None
    )
    whisperx_openai_api_key = (
        os.getenv("WHISPERX_OPENAI_API_KEY")
        or _optional_str(config.get("whisperx_openai_api_key"))
        or None
    )
    whisperx_openai_timeout_seconds = _positive_float(
        os.getenv("WHISPERX_OPENAI_TIMEOUT_SECONDS")
        if os.getenv("WHISPERX_OPENAI_TIMEOUT_SECONDS") is not None
        else config.get("whisperx_openai_timeout_seconds"),
        "whisperx_openai_timeout_seconds",
        3600.0,
    )

    env_nltk_data = os.getenv("WHISPERX_NLTK_DATA_DIR") or os.getenv("NLTK_DATA")
    config_nltk_data = _optional_str(config.get("nltk_data_dir"))
    if env_nltk_data:
        nltk_data_dir = str(_resolve_path(env_nltk_data))
    elif config_nltk_data:
        nltk_data_dir = str(_resolve_path(config_nltk_data, config_base))
    elif model_dir:
        nltk_data_dir = str(Path(model_dir) / "nltk_data")
    else:
        nltk_data_dir = None

    env_cache_only = os.getenv("WHISPERX_MODEL_CACHE_ONLY")
    api_base_url = (
        os.getenv("MEDIA_TO_MD_API_BASE_URL")
        or _optional_str(config.get("api_base_url"))
        or None
    )
    admin_username = (
        os.getenv("WHISPERX_ADMIN_USERNAME")
        or _optional_str(config.get("admin_username"))
        or None
    )
    admin_password = (
        os.getenv("WHISPERX_ADMIN_PASSWORD")
        or _optional_str(config.get("admin_password"))
        or None
    )
    raw_whisperx_args = _whisperx_args_config(config)
    whisperx_args_config = (
        dict(raw_whisperx_args) if isinstance(raw_whisperx_args, dict) else {}
    )
    raw_pdf_args = _opendataloader_pdf_args_config(config)
    if raw_pdf_args is None:
        raw_pdf_args = {}
    opendataloader_pdf_args_config = normalize_opendataloader_pdf_args_config(raw_pdf_args)

    return Settings(
        data_root=data_root,
        whisperx_model=model,
        whisperx_model_dir=model_dir,
        whisperx_backend=whisperx_backend,
        whisperx_openai_base_url=whisperx_openai_base_url,
        whisperx_openai_api_key=whisperx_openai_api_key,
        whisperx_openai_timeout_seconds=whisperx_openai_timeout_seconds,
        api_base_url=api_base_url,
        model_cache_only=_bool_config(
            env_cache_only, _bool_config(config.get("model_cache_only"), False)
        ),
        nltk_data_dir=nltk_data_dir,
        whisperx_args=normalize_whisperx_args(raw_whisperx_args),
        whisperx_args_config=whisperx_args_config,
        opendataloader_pdf_args=normalize_opendataloader_pdf_args(raw_pdf_args),
        opendataloader_pdf_args_config=opendataloader_pdf_args_config,
        admin_username=admin_username,
        admin_password=admin_password,
    )
