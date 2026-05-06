"""Shared helpers for WhisperX Web backend contract tests.

These tests are intentionally contract-oriented because implementation lanes may
land backend modules in parallel. They skip when the target module is not present
in this worker's isolated worktree, and become active automatically once the
backend scaffold exists.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import pytest


BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


CONTRACT_SKIP = (
    "backend implementation module is not present in this worker worktree yet"
)


def import_or_skip(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_root = exc.name == module_name or module_name.startswith(f"{exc.name}.")
        if missing_root:
            pytest.skip(f"{CONTRACT_SKIP}: {module_name}", allow_module_level=False)
        raise


def get_attr_or_skip(module: Any, *names: str) -> Any:
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    pytest.skip(f"{module.__name__} lacks expected helper(s): {', '.join(names)}")


@pytest.fixture()
def configured_env(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    data_root = tmp_path / "data"
    model_root = tmp_path / "models"
    data_root.mkdir()
    model_root.mkdir()
    monkeypatch.setenv("WHISPERX_DATA_ROOT", str(data_root))
    monkeypatch.delenv("WHISPERX_MODEL", raising=False)
    monkeypatch.setenv("WHISPERX_MODEL_DIR", str(model_root))
    monkeypatch.delenv("WHISPERX_NLTK_DATA_DIR", raising=False)
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.setenv("WHISPERX_FAKE_RUNNER", "1")
    return data_root


def call_first(candidates: list[Callable[[], Any]]) -> Any:
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return candidate()
        except TypeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise AssertionError("no candidates provided")
