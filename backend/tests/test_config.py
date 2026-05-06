from __future__ import annotations

import pytest

from app.config import (
    get_settings,
    load_backend_config,
    normalize_opendataloader_pdf_args,
    normalize_whisperx_args,
)


def test_config_defaults_direct_cli_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", "")
    monkeypatch.setenv("WHISPERX_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("WHISPERX_MODEL", raising=False)
    monkeypatch.setenv("WHISPERX_MODEL_DIR", "/models")
    monkeypatch.delenv("WHISPERX_NLTK_DATA_DIR", raising=False)
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.delenv("WHISPERX_ARGS_JSON", raising=False)
    monkeypatch.delenv("MEDIA_TO_MD_API_BASE_URL", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_PASSWORD", raising=False)

    settings = get_settings()

    assert settings.whisperx_model == "small"
    assert settings.whisperx_model_dir == "/models"
    assert settings.nltk_data_dir == "/models/nltk_data"
    assert settings.whisperx_args == ()
    assert settings.api_base_url is None
    assert settings.opendataloader_pdf_args == (
        "--format",
        "markdown,text",
        "--image-output",
        "off",
    )
    assert settings.admin_username is None
    assert settings.admin_password is None


def test_backend_config_json_is_loaded_and_env_can_override(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "data_root": "configured-data",
  "whisperx_model": "/models-from-json/faster-whisper-large-v2",
  "api_base_url": "http://localhost:8000/api",
  "whisperx_model_dir": "/models-from-json",
  "nltk_data_dir": "configured-nltk",
  "model_cache_only": true,
	  "whisperx_args": {
	    "batch_size": 16,
	    "compute_type": "float16"
	  },
	  "opendataloader_pdf_args": {
	    "format": ["markdown", "text"],
	    "threads": 2,
	    "table_method": "cluster",
	    "image_output": "off"
	  },
	  "admin_username": "admin-json",
  "admin_password": "secret-json"
}
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("WHISPERX_DATA_ROOT", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL_DIR", raising=False)
    monkeypatch.delenv("WHISPERX_NLTK_DATA_DIR", raising=False)
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.delenv("WHISPERX_MODEL_CACHE_ONLY", raising=False)
    monkeypatch.delenv("WHISPERX_ARGS_JSON", raising=False)
    monkeypatch.delenv("MEDIA_TO_MD_API_BASE_URL", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("WHISPERX_ADMIN_PASSWORD", raising=False)

    settings = get_settings()

    assert settings.data_root == (tmp_path / "configured-data").resolve()
    assert settings.whisperx_model == "/models-from-json/faster-whisper-large-v2"
    assert settings.whisperx_model_dir == "/models-from-json"
    assert settings.api_base_url == "http://localhost:8000/api"
    assert settings.nltk_data_dir == str((tmp_path / "configured-nltk").resolve())
    assert settings.model_cache_only is True
    assert settings.whisperx_args == (
        "--batch_size",
        "16",
        "--compute_type",
        "float16",
    )
    assert settings.whisperx_args_config == {
        "batch_size": 16,
        "compute_type": "float16",
    }
    assert settings.opendataloader_pdf_args == (
        "--format",
        "markdown,text",
        "--image-output",
        "off",
        "--table-method",
        "cluster",
        "--threads",
        "2",
    )
    assert settings.opendataloader_pdf_args_config == {
        "format": "markdown,text",
        "threads": "2",
        "table_method": "cluster",
        "image_output": "off",
    }
    assert settings.admin_username == "admin-json"
    assert settings.admin_password == "secret-json"

    monkeypatch.setenv("WHISPERX_MODEL", "/models-from-env/faster-whisper-large-v2")
    monkeypatch.setenv("WHISPERX_MODEL_DIR", "/models-from-env")
    monkeypatch.setenv("WHISPERX_NLTK_DATA_DIR", "/nltk-from-env")
    monkeypatch.setenv("WHISPERX_MODEL_CACHE_ONLY", "false")
    monkeypatch.setenv("MEDIA_TO_MD_API_BASE_URL", "http://127.0.0.1:9000/api")
    monkeypatch.setenv(
        "WHISPERX_ARGS_JSON", '{"batch_size": 4, "compute_type": "float16"}'
    )
    monkeypatch.setenv(
        "OPENDATALOADER_PDF_ARGS_JSON",
        '{"format": "md,txt", "pages": "1-2", "image_output": "off"}',
    )
    monkeypatch.setenv("WHISPERX_ADMIN_USERNAME", "admin-env")
    monkeypatch.setenv("WHISPERX_ADMIN_PASSWORD", "secret-env")
    overridden = get_settings()
    assert overridden.whisperx_model == "/models-from-env/faster-whisper-large-v2"
    assert overridden.whisperx_model_dir == "/models-from-env"
    assert overridden.api_base_url == "http://127.0.0.1:9000/api"
    assert overridden.nltk_data_dir == "/nltk-from-env"
    assert overridden.model_cache_only is False
    assert overridden.whisperx_args == (
        "--batch_size",
        "4",
        "--compute_type",
        "float16",
    )
    assert overridden.whisperx_args_config == {
        "batch_size": 4,
        "compute_type": "float16",
    }
    assert overridden.opendataloader_pdf_args == (
        "--format",
        "md,txt",
        "--image-output",
        "off",
        "--pages",
        "1-2",
    )
    assert overridden.opendataloader_pdf_args_config == {
        "format": "md,txt",
        "pages": "1-2",
        "image_output": "off",
    }
    assert overridden.admin_username == "admin-env"
    assert overridden.admin_password == "secret-env"


def test_config_json_can_be_disabled(monkeypatch):
    monkeypatch.setenv("WHISPERX_CONFIG_FILE", "")

    assert load_backend_config() == {}


def test_whisperx_args_are_allowlisted_and_normalized():
    assert normalize_whisperx_args(
        {
            "--batch_size": "12",
            "compute_type": "int8",
            "device": "cuda",
            "chunk_size": 30,
        }
    ) == (
        "--batch_size",
        "12",
        "--compute_type",
        "int8",
        "--device",
        "cuda",
        "--chunk_size",
        "30",
    )

    with pytest.raises(ValueError, match="Unsupported whisperx_args key"):
        normalize_whisperx_args({"output_dir": "/tmp/unsafe"})
    with pytest.raises(ValueError, match="batch_size"):
        normalize_whisperx_args({"batch_size": 0})


def test_opendataloader_pdf_args_are_safe_allowlisted_and_normalized():
    assert normalize_opendataloader_pdf_args(
        {
            "format": [
                "json",
                "text",
                "html",
                "pdf",
                "markdown",
                "markdown-with-html",
                "markdown-with-images",
                "tagged-pdf",
            ],
            "pages": "1-3,5",
            "table_method": "cluster",
            "reading_order": "xycut",
            "image_output": "external",
            "image_format": "jpeg",
            "threads": 2,
            "hybrid": "docling-fast",
            "hybrid_mode": "full",
            "hybrid_timeout": 30000,
        }
    ) == (
        "--format",
        "json,text,html,pdf,markdown,markdown-with-html,markdown-with-images,tagged-pdf",
        "--hybrid",
        "docling-fast",
        "--hybrid-mode",
        "full",
        "--hybrid-timeout",
        "30000",
        "--image-format",
        "jpeg",
        "--image-output",
        "external",
        "--pages",
        "1-3,5",
        "--reading-order",
        "xycut",
        "--table-method",
        "cluster",
        "--threads",
        "2",
    )

    with pytest.raises(ValueError, match="Unsupported opendataloader_pdf_args key"):
        normalize_opendataloader_pdf_args({"ocr": True})
    with pytest.raises(ValueError, match="image_output"):
        normalize_opendataloader_pdf_args({"image_output": "sidecar"})
    for removed_key in ("content_safety_off", "output_dir", "to_stdout", "image_dir", "hybrid_url"):
        with pytest.raises(ValueError, match="Unsupported opendataloader_pdf_args key"):
            normalize_opendataloader_pdf_args({removed_key: "value"})
