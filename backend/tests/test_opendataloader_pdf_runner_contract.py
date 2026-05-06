from __future__ import annotations

import importlib
import inspect
from pathlib import Path


def _build_pdf_argv(runner_module, tmp_path: Path) -> list[str]:
    input_path = tmp_path / "input.pdf"
    output_dir = tmp_path / "output"
    input_path.write_bytes(b"%PDF-1.7\n")
    output_dir.mkdir()

    argv = runner_module.build_opendataloader_pdf_argv(
        input_path,
        output_dir,
        runner_module.OpenDataLoaderPdfRunnerConfig(),
    )
    return list(argv)


def test_opendataloader_pdf_runner_builds_argv_list_without_shell(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    argv = _build_pdf_argv(runner, tmp_path)

    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert "shell=True" not in inspect.getsource(runner)


def test_opendataloader_pdf_runner_uses_direct_opendataloader_pdf_command(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    argv = _build_pdf_argv(runner, tmp_path)

    assert argv[:2] == ["opendataloader-pdf", str(tmp_path / "input.pdf")]
    assert "--from" not in argv


def test_opendataloader_pdf_runner_passes_backend_owned_output_dir(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    argv = _build_pdf_argv(runner, tmp_path)

    assert "-o" in argv
    output_dir = Path(argv[argv.index("-o") + 1]).resolve()
    assert output_dir == (tmp_path / "output").resolve()
    assert "--output-dir" not in argv
    assert "--output_dir" not in argv


def test_opendataloader_pdf_runner_defaults_markdown_text(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    argv = _build_pdf_argv(runner, tmp_path)

    assert "-f" in argv
    assert argv[argv.index("-f") + 1] in {"json,markdown,text", "json,md,txt"}


def test_hybrid_options_are_not_passed_to_runner_by_default(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    argv = _build_pdf_argv(runner, tmp_path)
    option_tokens: list[str] = []
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if index == 1:  # positional input path can contain arbitrary tmpdir text
            continue
        if token == "-o":
            skip_next = True
            continue
        option_tokens.append(token)
    joined = " ".join(option_tokens).lower()

    assert "hybrid" not in joined
    assert "ocr" not in joined
    assert "content-safety-off" not in joined
    assert "password" not in joined


def test_configured_hybrid_options_are_passed_to_runner(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")
    config_cls = getattr(runner, "OpenDataLoaderPdfRunnerConfig")

    argv = runner.build_opendataloader_pdf_argv(
        tmp_path / "input.pdf",
        tmp_path / "output",
        config_cls(extra_args=("--format", "markdown,text", "--hybrid", "hancom-ai")),
    )

    assert "--hybrid" in argv
    assert argv[argv.index("--hybrid") + 1] == "hancom-ai"


def test_configured_retained_options_are_passed_to_runner(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")
    config_cls = getattr(runner, "OpenDataLoaderPdfRunnerConfig")

    argv = runner.build_opendataloader_pdf_argv(
        tmp_path / "input.pdf",
        tmp_path / "output",
        config_cls(
            extra_args=(
                "--format",
                "markdown-with-images",
                "--image-output",
                "external",
                "--image-format",
                "jpeg",
                "--table-method",
                "cluster",
            )
        ),
    )

    assert "--image-output" in argv
    assert argv[argv.index("--image-output") + 1] == "external"
    assert "--image-format" in argv
    assert argv[argv.index("--image-format") + 1] == "jpeg"
    assert "--table-method" in argv
    assert argv[argv.index("--table-method") + 1] == "cluster"


def test_removed_pdf_options_are_rejected_by_managed_runner(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")
    config_cls = getattr(runner, "OpenDataLoaderPdfRunnerConfig")

    for removed_flag in (
        "--output-dir",
        "--to-stdout",
        "--content-safety-off",
        "--password",
        "--image-dir",
        "--hybrid-url",
    ):
        try:
            runner.build_opendataloader_pdf_argv(
                tmp_path / "input.pdf",
                tmp_path / "output",
                config_cls(extra_args=("--format", "json", removed_flag, "value")),
            )
        except ValueError as exc:
            assert removed_flag in str(exc)
        else:  # pragma: no cover - assertion message is clearer
            raise AssertionError(f"{removed_flag} should be rejected")


def test_markdown_output_auto_requests_json_for_postprocess(tmp_path: Path):
    runner = importlib.import_module("app.opendataloader_pdf_runner")
    config_cls = getattr(runner, "OpenDataLoaderPdfRunnerConfig")

    argv = runner.build_opendataloader_pdf_argv(
        tmp_path / "input.pdf",
        tmp_path / "output",
        config_cls(extra_args=("--format", "markdown,pdf,tagged-pdf")),
    )

    assert argv[argv.index("--format") + 1] == "json,markdown,pdf,tagged-pdf"


def test_missing_java_or_opendataloader_failure_is_readable():
    runner = importlib.import_module("app.opendataloader_pdf_runner")

    error_mapper = getattr(runner, "readable_pdf_runtime_error", None) or getattr(
        runner, "format_pdf_runtime_error", None
    )
    assert error_mapper is not None, "PDF runner must map runtime failures to readable errors"

    message = error_mapper(FileNotFoundError("java"))
    assert "Java" in message or "OpenDataLoader" in message
    assert "install" in message.lower() or "PATH" in message
