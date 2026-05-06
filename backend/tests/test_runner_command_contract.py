from __future__ import annotations

import inspect
import pathlib
import subprocess

import pytest

from conftest import get_attr_or_skip, import_or_skip


def _build_command(runner, tmp_path: pathlib.Path):
    input_file = tmp_path / "input.wav"
    output_dir = tmp_path / "output"
    model_dir = tmp_path / "models"
    input_file.write_bytes(b"fake audio")
    output_dir.mkdir()
    model_dir.mkdir(exist_ok=True)

    if hasattr(runner, "build_whisperx_argv"):
        return runner.build_whisperx_argv(
            input_file,
            output_dir,
            runner.WhisperXOptions(
                model="small",
                language="en",
                diarize=True,
                model_cache_only=True,
                output_formats=("txt", "srt", "vtt", "json"),
            ),
            runner.WhisperXRunnerConfig(model_dir=model_dir),
        )

    build_command = get_attr_or_skip(
        runner,
        "build_whisperx_command",
        "build_command",
        "create_whisperx_command",
    )

    attempts = [
        lambda: build_command(
            input_path=input_file,
            output_dir=output_dir,
            model="small",
            language="en",
            diarize=True,
            model_dir=model_dir,
            model_cache_only=True,
            output_formats=["txt", "srt", "vtt", "json"],
        ),
        lambda: build_command(
            str(input_file),
            str(output_dir),
            model="small",
            language="en",
            diarize=True,
            model_dir=str(model_dir),
            model_cache_only=True,
        ),
        lambda: build_command(
            input_file,
            output_dir,
            {
                "model": "small",
                "language": "en",
                "diarize": True,
                "model_dir": str(model_dir),
                "model_cache_only": True,
                "output_formats": ["txt", "srt", "vtt", "json"],
            },
        ),
    ]
    last_error: TypeError | None = None
    for attempt in attempts:
        try:
            command = attempt()
            break
        except TypeError as exc:
            last_error = exc
    else:
        raise last_error or AssertionError("command builder could not be called")

    if hasattr(command, "argv"):
        command = command.argv
    return command


def test_command_builder_uses_direct_whisperx_argv_and_model_flags(
    tmp_path, configured_env
):
    runner = import_or_skip("app.whisperx_runner")
    argv = _build_command(runner, tmp_path)

    assert isinstance(argv, list), (
        "WhisperX command must be an argv list, not a shell string"
    )
    assert argv[:2] == ["whisperx", str(tmp_path / "input.wav")]
    assert "--from" not in argv
    assert "--model" in argv and "small" in argv
    assert "--language" in argv and "en" in argv
    assert "--diarize" in argv
    assert "--model_dir" in argv and str(tmp_path / "models") in argv
    cache_only_index = argv.index("--model_cache_only")
    assert argv[cache_only_index : cache_only_index + 2] == [
        "--model_cache_only",
        "True",
    ]
    assert "--output_format" in argv or "--output_format" in " ".join(argv)


def test_runner_source_does_not_use_shell_true():
    runner = import_or_skip("app.whisperx_runner")
    source = inspect.getsource(runner)
    assert "shell=True" not in source


def test_subprocess_invocation_receives_sequence_not_shell_string(
    monkeypatch, tmp_path, configured_env
):
    runner = import_or_skip("app.whisperx_runner")
    run_callable = get_attr_or_skip(
        runner, "run_whisperx", "run_command", "execute_whisperx"
    )
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, *args, **kwargs):
        calls.append((argv, kwargs))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    command = _build_command(runner, tmp_path)

    try:
        result = run_callable(command, log_path=tmp_path / "job.log")
        if inspect.isawaitable(result):
            pytest.skip(
                "async runner invocation is covered by fake-flow integration tests"
            )
    except TypeError:
        pytest.skip(
            "runner execution signature is implementation-specific; static no-shell check still applies"
        )

    assert calls, (
        "runner should invoke subprocess.run or expose an async implementation covered elsewhere"
    )
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert kwargs.get("shell") is not True
