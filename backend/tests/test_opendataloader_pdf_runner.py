from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.models import JobOptions, JobStatus
from app.opendataloader_pdf_runner import (
    OpenDataLoaderPdfErrorKind,
    OpenDataLoaderPdfRunRequest,
    OpenDataLoaderPdfRunner,
    OpenDataLoaderPdfRunnerConfig,
    OpenDataLoaderPdfRunnerError,
    build_opendataloader_pdf_argv,
    map_opendataloader_pdf_error,
)
from app.storage import JobStorage


class OpenDataLoaderPdfCommandBuilderTests(unittest.TestCase):
    def test_builds_direct_argv_with_markdown_text_and_output_dir(self):
        argv = build_opendataloader_pdf_argv(
            Path("/in/file.pdf"),
            Path("/jobs/job-1/output"),
            OpenDataLoaderPdfRunnerConfig(),
        )

        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:2], ["opendataloader-pdf", "/in/file.pdf"])
        self.assertNotIn("--from", argv)
        self.assertIn("-f", argv)
        self.assertEqual(argv[argv.index("-f") + 1], "json,markdown,text")
        self.assertIn("-o", argv)
        self.assertEqual(argv[argv.index("-o") + 1], "/jobs/job-1/output")

    def test_builds_argv_with_configured_hybrid_args(self):
        argv = build_opendataloader_pdf_argv(
            Path("/in/file.pdf"),
            Path("/jobs/job-1/output"),
            OpenDataLoaderPdfRunnerConfig(
                extra_args=(
                    "--format",
                    "markdown,text",
                    "--hybrid",
                    "docling-fast",
                    "--hybrid-mode",
                    "full",
                )
            ),
        )

        self.assertIn("--hybrid", argv)
        self.assertEqual(argv[argv.index("--format") + 1], "json,markdown,text")
        self.assertEqual(argv[argv.index("--hybrid") + 1], "docling-fast")
        self.assertIn("--hybrid-mode", argv)

    def test_rejects_output_destination_overrides(self):
        with self.assertRaisesRegex(ValueError, "output-dir"):
            build_opendataloader_pdf_argv(
                Path("/in/file.pdf"),
                Path("/jobs/job-1/output"),
                OpenDataLoaderPdfRunnerConfig(
                    extra_args=(
                        "--format",
                        "markdown",
                        "--output-dir",
                        "/tmp/custom-output",
                    )
                ),
            )

    def test_runner_uses_create_subprocess_exec_without_shell(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request = OpenDataLoaderPdfRunRequest(
                    input_path=root / "input.pdf",
                    output_dir=root / "output",
                    log_path=root / "logs" / "job.log",
                )
                request.input_path.write_bytes(b"%PDF")
                stdout = mock.MagicMock()
                stdout.__aiter__.return_value = [b"ok\n"]
                process = mock.MagicMock()
                process.stdout = stdout
                process.wait = mock.AsyncMock(return_value=0)

                with mock.patch(
                    "app.opendataloader_pdf_runner.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=process),
                ) as create_proc:
                    result = await OpenDataLoaderPdfRunner().run(request)

                _, kwargs = create_proc.call_args
                self.assertNotIn("shell", kwargs)
                self.assertEqual(result.returncode, 0)
                self.assertIn(
                    "$ opendataloader-pdf",
                    request.log_path.read_text(encoding="utf-8"),
                )

        asyncio.run(exercise())


class OpenDataLoaderPdfErrorMappingTests(unittest.TestCase):
    def test_java_errors_are_readable(self):
        error = map_opendataloader_pdf_error("java: command not found", 127)
        self.assertEqual(error.kind, OpenDataLoaderPdfErrorKind.JAVA)
        self.assertIn("Install a JRE/JDK", error.message)

    def test_opendataloader_errors_are_readable(self):
        error = map_opendataloader_pdf_error("opendataloader-pdf: command not found", 127)
        self.assertEqual(error.kind, OpenDataLoaderPdfErrorKind.OPENDATALOADER)
        self.assertIn("opendataloader-pdf executable", error.message)

    def test_java_stack_traces_are_not_reported_as_missing_java(self):
        error = map_opendataloader_pdf_error(
            "java.io.IOException: can not locate xref table", 1
        )

        self.assertEqual(error.kind, OpenDataLoaderPdfErrorKind.PROCESS)
        self.assertIn("can not locate xref table", error.message)
        self.assertNotIn("requires Java", error.message)

    def test_failed_process_output_is_mapped(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request = OpenDataLoaderPdfRunRequest(
                    input_path=root / "input.pdf",
                    output_dir=root / "output",
                    log_path=root / "logs" / "job.log",
                )
                request.input_path.write_bytes(b"%PDF")
                stdout = mock.MagicMock()
                stdout.__aiter__.return_value = [b"java executable missing\n"]
                process = mock.MagicMock()
                process.stdout = stdout
                process.wait = mock.AsyncMock(return_value=127)

                with mock.patch(
                    "app.opendataloader_pdf_runner.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=process),
                ):
                    with self.assertRaises(OpenDataLoaderPdfRunnerError) as ctx:
                        await OpenDataLoaderPdfRunner().run(request)

                self.assertEqual(ctx.exception.kind, OpenDataLoaderPdfErrorKind.JAVA)

        asyncio.run(exercise())


class JobStorageOpenDataLoaderPdfRunnerTests(unittest.TestCase):
    def test_start_job_updates_manifest_and_discovers_pdf_artifacts(self):
        from app.opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner

        async def exercise():
            class FakeRunner(JobStorageOpenDataLoaderPdfRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    (request.output_dir / "result.json").write_text(
                        '{"kids":[]}', encoding="utf-8"
                    )
                    (request.output_dir / "result.md").write_text("# ok", encoding="utf-8")
                    (request.output_dir / "result.txt").write_text("ok", encoding="utf-8")
                    (request.output_dir / "ignored.html").write_text("no", encoding="utf-8")

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"%PDF"),
                    "paper.pdf",
                    JobOptions(task_type="pdf"),
                )

                await FakeRunner(storage).start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertEqual(
                    {artifact.format for artifact in updated.artifacts},
                    {"html", "json", "markdown_clear", "md", "txt"},
                )

        asyncio.run(exercise())

    def test_start_job_filters_image_text_from_markdown_artifact(self):
        from app.opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner

        async def exercise():
            class FakeRunner(JobStorageOpenDataLoaderPdfRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    (request.output_dir / "paper.md").write_text(
                        "Body text.\n\n![image](images/figure.png)\n\nFIGURE TEXT\n",
                        encoding="utf-8",
                    )
                    (request.output_dir / "paper.json").write_text(
                        """
{
  "kids": [
    {
      "type": "image",
      "page number": 1,
      "bounding box": [100, 100, 300, 300],
      "source": "images/figure.png"
    },
    {
      "type": "paragraph",
      "page number": 1,
      "bounding box": [120, 140, 220, 160],
      "content": "FIGURE TEXT"
    }
  ]
}
""",
                        encoding="utf-8",
                    )

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"%PDF"),
                    "paper.pdf",
                    JobOptions(task_type="pdf"),
                )

                await FakeRunner(storage).start_job(manifest.job_id)

                original = storage.job_dir(manifest.job_id) / "output" / "paper.md"
                clean = (
                    storage.job_dir(manifest.job_id)
                    / "output"
                    / "paper_clear.md"
                )
                updated = storage.read_manifest(manifest.job_id)
                events = storage.read_events(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertIn("FIGURE TEXT", original.read_text(encoding="utf-8"))
                self.assertIn("Body text.", clean.read_text(encoding="utf-8"))
                self.assertIn(
                    "![image](images/figure.png)",
                    clean.read_text(encoding="utf-8"),
                )
                self.assertNotIn("FIGURE TEXT", clean.read_text(encoding="utf-8"))
                self.assertIn(
                    "markdown_clear", {artifact.format for artifact in updated.artifacts}
                )
                self.assertTrue(
                    any("生成 markdown_clear 清洗版" in event.message for event in events)
                )

        asyncio.run(exercise())

    def test_start_job_skips_postprocess_when_strength_off(self):
        from app.opendataloader_pdf_runner import JobStorageOpenDataLoaderPdfRunner

        async def exercise():
            class FakeRunner(JobStorageOpenDataLoaderPdfRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    (request.output_dir / "paper.md").write_text(
                        "Body text.\n\n![image](images/figure.png)\n\nFIGURE TEXT\n",
                        encoding="utf-8",
                    )
                    (request.output_dir / "paper.json").write_text(
                        "{}",
                        encoding="utf-8",
                    )

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"%PDF"),
                    "paper.pdf",
                    JobOptions(
                        task_type="pdf",
                        markdown_cleanup_strength="off",
                    ),
                )

                with mock.patch(
                    "app.opendataloader_pdf_runner.postprocess_opendataloader_markdown_outputs"
                ) as postprocess:
                    await FakeRunner(storage).start_job(manifest.job_id)
                    self.assertFalse(postprocess.called)

                updated = storage.read_manifest(manifest.job_id)
                clean = storage.job_dir(manifest.job_id) / "output" / "paper_clear.md"
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertFalse(clean.exists())
                self.assertNotIn(
                    "markdown_clear",
                    {artifact.format for artifact in updated.artifacts},
                )

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
