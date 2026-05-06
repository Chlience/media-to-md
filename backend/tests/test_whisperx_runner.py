import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.whisperx_runner import (
    REQUIRED_OUTPUT_FORMATS,
    WhisperXErrorKind,
    WhisperXOptions,
    WhisperXRunRequest,
    WhisperXRunner,
    JobStorageWhisperXRunner,
    WhisperXRunnerConfig,
    WhisperXRunnerError,
    build_runner_env,
    build_whisperx_argv,
    map_whisperx_error,
    options_from_job_options,
    validate_options,
)


class WhisperXCommandBuilderTests(unittest.TestCase):
    def test_builds_direct_argv_list_with_model_dir_cache_and_diarization(self):
        config = WhisperXRunnerConfig(
            model_dir=Path("/models"), config_args=("--batch_size", "16")
        )
        options = WhisperXOptions(
            model="large-v3", language="en", diarize=True, model_cache_only=True
        )

        argv = build_whisperx_argv(Path("/in/audio.wav"), Path("/out"), options, config)

        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:2], ["whisperx", "/in/audio.wav"])
        self.assertNotIn("--from", argv)
        self.assertIn("/in/audio.wav", argv)
        self.assertIn("--model", argv)
        self.assertIn("large-v3", argv)
        self.assertIn("--language", argv)
        self.assertIn("en", argv)
        self.assertIn("--diarize", argv)
        self.assertIn("--model_dir", argv)
        self.assertIn("/models", argv)
        cache_only_index = argv.index("--model_cache_only")
        self.assertEqual(
            argv[cache_only_index : cache_only_index + 2],
            ["--model_cache_only", "True"],
        )
        self.assertIn("--output_format", argv)
        self.assertIn("all", argv)
        batch_index = argv.index("--batch_size")
        self.assertEqual(argv[batch_index : batch_index + 2], ["--batch_size", "16"])
        self.assertNotIn("shell=True", " ".join(argv))

    def test_auto_language_is_omitted(self):
        argv = build_whisperx_argv(
            Path("audio.wav"),
            Path("out"),
            WhisperXOptions(model="small", language="auto"),
            WhisperXRunnerConfig(model_dir=None),
        )
        self.assertNotIn("--language", argv)

    def test_invalid_model_language_format_and_extra_args_are_rejected(self):
        with self.assertRaisesRegex(WhisperXRunnerError, "Unsupported WhisperX model"):
            validate_options(WhisperXOptions(model="$(rm -rf /)"))
        with self.assertRaisesRegex(WhisperXRunnerError, "Unsupported WhisperX model"):
            validate_options(WhisperXOptions(model="/unconfigured/local/model"))
        with self.assertRaisesRegex(
            WhisperXRunnerError, "Unsupported WhisperX language"
        ):
            validate_options(WhisperXOptions(language="en;rm"))
        with self.assertRaisesRegex(WhisperXRunnerError, "Raw extra"):
            validate_options(WhisperXOptions(extra_args=("--danger",)))

    def test_configured_local_model_path_is_allowed(self):
        local_model = "/home/chlience/model/faster-whisper-large-v2"
        config = WhisperXRunnerConfig(
            model_dir=Path("/models"), default_model=local_model
        )

        argv = build_whisperx_argv(
            Path("/in/audio.wav"),
            Path("/out"),
            WhisperXOptions(model=local_model, model_cache_only=True),
            config,
        )

        model_index = argv.index("--model")
        self.assertEqual(argv[model_index : model_index + 2], ["--model", local_model])

    def test_required_output_formats_are_locked_to_manifest_allowlist(self):
        self.assertEqual(REQUIRED_OUTPUT_FORMATS, ("txt", "srt", "vtt", "json"))
        with self.assertRaisesRegex(WhisperXRunnerError, "Unsupported output format"):
            validate_options(WhisperXOptions(output_formats=("txt", "log")))

    def test_env_includes_whisperx_model_dir(self):
        env = build_runner_env(
            WhisperXRunnerConfig(model_dir=Path("/cache/models"), env={"X": "Y"})
        )
        self.assertEqual(env["WHISPERX_MODEL_DIR"], "/cache/models")
        self.assertEqual(env["NLTK_DATA"], "/cache/models/nltk_data")
        self.assertEqual(env["X"], "Y")

    def test_env_preserves_explicit_nltk_data(self):
        env = build_runner_env(
            WhisperXRunnerConfig(
                model_dir=Path("/cache/models"), env={"NLTK_DATA": "/custom/nltk"}
            )
        )
        self.assertEqual(env["NLTK_DATA"], "/custom/nltk")


class WhisperXErrorMappingTests(unittest.TestCase):
    def test_model_cache_errors_are_readable(self):
        error = map_whisperx_error("model_cache_only requested but model not found", 2)
        self.assertEqual(error.kind, WhisperXErrorKind.MODEL_CACHE)
        self.assertIn("WHISPERX_MODEL_DIR", error.message)

    def test_diarization_errors_are_readable(self):
        error = map_whisperx_error(
            "pyannote diarization requires hf_token and terms", 3
        )
        self.assertEqual(error.kind, WhisperXErrorKind.DIARIZATION)
        self.assertIn("Hugging Face", error.message)

    def test_generic_process_error_is_readable(self):
        error = map_whisperx_error("unexpected crash", 9)
        self.assertEqual(error.kind, WhisperXErrorKind.PROCESS)
        self.assertIn("exit code 9", error.message)


class WhisperXRunnerTests(unittest.TestCase):
    def test_runner_uses_create_subprocess_exec_without_shell(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request = WhisperXRunRequest(
                    input_path=root / "audio.wav",
                    output_dir=root / "out",
                    log_path=root / "logs" / "job.log",
                    options=WhisperXOptions(),
                )
                request.input_path.write_text("fake", encoding="utf-8")

                stdout = mock.MagicMock()
                stdout.__aiter__.return_value = [b"ok\n"]
                process = mock.MagicMock()
                process.stdout = stdout
                process.wait = mock.AsyncMock(return_value=0)

                with mock.patch(
                    "app.whisperx_runner.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=process),
                ) as create_proc:
                    result = await WhisperXRunner(
                        WhisperXRunnerConfig(model_dir=root / "models")
                    ).run(request)

                _, kwargs = create_proc.call_args
                self.assertNotIn("shell", kwargs)
                self.assertEqual(result.returncode, 0)
                self.assertIn(
                    "$ whisperx",
                    request.log_path.read_text(encoding="utf-8"),
                )

        asyncio.run(exercise())

    def test_runner_maps_failed_process_output(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                request = WhisperXRunRequest(
                    input_path=root / "audio.wav",
                    output_dir=root / "out",
                    log_path=root / "logs" / "job.log",
                    options=WhisperXOptions(diarize=True),
                )
                request.input_path.write_text("fake", encoding="utf-8")

                stdout = mock.MagicMock()
                stdout.__aiter__.return_value = [b"pyannote hf_token missing\n"]
                process = mock.MagicMock()
                process.stdout = stdout
                process.wait = mock.AsyncMock(return_value=7)

                with mock.patch(
                    "app.whisperx_runner.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=process),
                ):
                    with self.assertRaises(WhisperXRunnerError) as ctx:
                        await WhisperXRunner(WhisperXRunnerConfig(model_dir=None)).run(
                            request
                        )

                self.assertEqual(ctx.exception.kind, WhisperXErrorKind.DIARIZATION)
                self.assertEqual(ctx.exception.returncode, 7)

        asyncio.run(exercise())


class JobStorageWhisperXRunnerTests(unittest.TestCase):
    def test_start_job_updates_manifest_logs_and_artifacts(self):
        async def exercise():
            from app.models import JobOptions, JobStatus
            from app.storage import JobStorage

            class FakeRunner(JobStorageWhisperXRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    for fmt in ("txt", "srt", "vtt", "json"):
                        (request.output_dir / f"result.{fmt}").write_text(
                            fmt, encoding="utf-8"
                        )
                    request.log_path.write_text("fake whisperx ok\n", encoding="utf-8")
                    return None

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"fake audio"),
                    "input.wav",
                    JobOptions(
                        model="small",
                        language="auto",
                        diarize=False,
                        model_cache_only=True,
                    ),
                )

                runner = FakeRunner(
                    storage, WhisperXRunnerConfig(model_dir=Path(tmp) / "models")
                )
                await runner.start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertEqual(
                    {artifact.format for artifact in updated.artifacts},
                    {"txt", "srt", "vtt"},
                )
                self.assertTrue(
                    all(
                        artifact.path.startswith("output/")
                        for artifact in updated.artifacts
                    )
                )
                self.assertEqual(updated.log_path, "logs/job.log")

        asyncio.run(exercise())

    def test_json_artifact_is_generated_but_hidden_when_not_requested(self):
        async def exercise():
            from app.models import JobOptions, JobStatus
            from app.storage import JobStorage

            class FakeRunner(JobStorageWhisperXRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    for fmt in ("txt", "json"):
                        (request.output_dir / f"result.{fmt}").write_text(
                            fmt, encoding="utf-8"
                        )
                    request.log_path.write_text("fake whisperx ok\n", encoding="utf-8")
                    return None

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"fake audio"),
                    "input.wav",
                    JobOptions(output_formats=["txt"]),
                )

                runner = FakeRunner(storage, WhisperXRunnerConfig(model_dir=None))
                await runner.start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertEqual(
                    {artifact.format for artifact in updated.artifacts}, {"txt"}
                )
                self.assertTrue(
                    (
                        storage.job_dir(manifest.job_id) / "output" / "result.json"
                    ).is_file()
                )

        asyncio.run(exercise())

    def test_json_artifact_is_public_when_requested(self):
        async def exercise():
            from app.models import JobOptions
            from app.storage import JobStorage

            class FakeRunner(JobStorageWhisperXRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    for fmt in ("txt", "json"):
                        (request.output_dir / f"result.{fmt}").write_text(
                            fmt, encoding="utf-8"
                        )
                    request.log_path.write_text("fake whisperx ok\n", encoding="utf-8")
                    return None

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"fake audio"),
                    "input.wav",
                    JobOptions(output_formats=["txt", "json"]),
                )

                runner = FakeRunner(storage, WhisperXRunnerConfig(model_dir=None))
                await runner.start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(
                    {artifact.format for artifact in updated.artifacts},
                    {"txt", "json"},
                )

        asyncio.run(exercise())

    def test_start_job_persists_runner_errors_without_raising(self):
        async def exercise():
            from app.models import JobOptions, JobStatus
            from app.storage import JobStorage

            class FailingRunner(JobStorageWhisperXRunner):
                async def run(self, request, on_log=None):
                    raise WhisperXRunnerError(
                        WhisperXErrorKind.MODEL_CACHE, "cache missing"
                    )

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"fake audio"), "input.wav", JobOptions()
                )

                await FailingRunner(
                    storage, WhisperXRunnerConfig(model_dir=None)
                ).start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.failed)
                self.assertEqual(updated.error, "cache missing")
                self.assertIn("cache missing", storage.read_log(manifest.job_id))

        asyncio.run(exercise())

    def test_job_options_conversion_preserves_backend_options(self):
        from app.models import JobOptions

        options = options_from_job_options(
            JobOptions(
                model="medium",
                language="en",
                diarize=True,
                model_cache_only=True,
                output_formats=["txt", "json"],
            )
        )

        self.assertEqual(options.model, "medium")
        self.assertEqual(options.language, "en")
        self.assertTrue(options.diarize)
        self.assertTrue(options.model_cache_only)
        self.assertEqual(options.output_formats, ("txt", "json"))

    def test_from_settings_carries_backend_config_args(self):
        from app.config import Settings
        from app.storage import JobStorage

        with tempfile.TemporaryDirectory() as tmp:
            runner = JobStorageWhisperXRunner.from_settings(
                JobStorage(Path(tmp)),
                Settings(
                    data_root=Path(tmp),
                    whisperx_model_dir=None,
                    whisperx_args=("--batch_size", "16"),
                ),
            )

        self.assertEqual(runner.config.config_args, ("--batch_size", "16"))


if __name__ == "__main__":
    unittest.main()
