from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.models import JobOptions, JobStatus
from app.storage import JobStorage
from app.whisperx_openai_runner import (
    JobStorageOpenAIWhisperXRunner,
    OpenAIWhisperXRunRequest,
    OpenAIWhisperXRunner,
    OpenAIWhisperXRunnerConfig,
    build_openai_form_fields,
    build_openai_transcriptions_url,
)
from app.whisperx_runner import WhisperXOptions


class OpenAIWhisperXRunnerTests(unittest.TestCase):
    def test_builds_endpoint_from_base_url_variants(self):
        self.assertEqual(
            build_openai_transcriptions_url("http://localhost:9000"),
            "http://localhost:9000/v1/audio/transcriptions",
        )
        self.assertEqual(
            build_openai_transcriptions_url("http://localhost:9000/v1"),
            "http://localhost:9000/v1/audio/transcriptions",
        )
        self.assertEqual(
            build_openai_transcriptions_url(
                "http://localhost:9000/v1/audio/transcriptions"
            ),
            "http://localhost:9000/v1/audio/transcriptions",
        )

    def test_builds_openai_fields_from_job_options_and_config(self):
        fields = build_openai_form_fields(
            WhisperXOptions(
                model="large-v2",
                language="zh",
                diarize=True,
                min_speakers=1,
                max_speakers=2,
            ),
            OpenAIWhisperXRunnerConfig(
                base_url="http://localhost:9000/v1",
                default_model="large-v2",
                config_fields={
                    "batch_size": 4,
                    "chunk_size": 30,
                    "device": "cuda",
                    "speaker_embeddings": True,
                },
            ),
        )

        self.assertIn(("model", "large-v2"), fields)
        self.assertIn(("language", "zh"), fields)
        self.assertIn(("response_format", "verbose_json"), fields)
        self.assertIn(("timestamp_granularities[]", "segment"), fields)
        self.assertIn(("diarize", "true"), fields)
        self.assertIn(("min_speakers", "1"), fields)
        self.assertIn(("max_speakers", "2"), fields)
        self.assertIn(("batch_size", "4"), fields)
        self.assertIn(("chunk_size", "30"), fields)
        self.assertIn(("speaker_embeddings", "true"), fields)
        self.assertNotIn(("device", "cuda"), fields)

    def test_runner_posts_multipart_and_writes_artifacts(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                input_path = root / "audio.wav"
                input_path.write_bytes(b"fake audio")
                request = OpenAIWhisperXRunRequest(
                    input_path=input_path,
                    output_dir=root / "output",
                    log_path=root / "logs" / "job.log",
                    options=WhisperXOptions(
                        model="small", language="zh", diarize=True, min_speakers=1
                    ),
                )
                response_payload = {
                    "text": "你好 世界",
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 1.25,
                            "text": "你好 世界",
                            "speaker": "SPEAKER_00",
                        }
                    ],
                }
                captured = {}

                class FakeResponse:
                    status = 200

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return None

                    def read(self):
                        return json.dumps(response_payload).encode("utf-8")

                def fake_urlopen(http_request, timeout):
                    captured["url"] = http_request.full_url
                    captured["headers"] = dict(http_request.header_items())
                    captured["body"] = http_request.data
                    captured["timeout"] = timeout
                    return FakeResponse()

                with mock.patch(
                    "app.whisperx_openai_runner.urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):
                    result = await OpenAIWhisperXRunner(
                        OpenAIWhisperXRunnerConfig(
                            base_url="http://localhost:9000/v1",
                            api_key="secret",
                            config_fields={"batch_size": 4},
                            timeout_seconds=123,
                        )
                    ).run(request)

                self.assertEqual(
                    captured["url"],
                    "http://localhost:9000/v1/audio/transcriptions",
                )
                self.assertEqual(captured["timeout"], 123)
                self.assertEqual(
                    captured["headers"].get("Authorization"), "Bearer secret"
                )
                body = captured["body"].decode("utf-8", errors="replace")
                self.assertIn('name="model"', body)
                self.assertIn('name="language"', body)
                self.assertIn('name="diarize"', body)
                self.assertIn('name="batch_size"', body)
                self.assertIn('filename="audio.wav"', body)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(
                    (request.output_dir / "result.txt").read_text(encoding="utf-8"),
                    "你好 世界\n",
                )
                self.assertIn(
                    "SPEAKER_00",
                    (request.output_dir / "result.srt").read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "WEBVTT",
                    (request.output_dir / "result.vtt").read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    json.loads(
                        (request.output_dir / "result.json").read_text(encoding="utf-8")
                    ),
                    response_payload,
                )

        asyncio.run(exercise())


class JobStorageOpenAIWhisperXRunnerTests(unittest.TestCase):
    def test_start_job_updates_manifest_logs_and_artifacts(self):
        async def exercise():
            class FakeRunner(JobStorageOpenAIWhisperXRunner):
                async def run(self, request, on_log=None):
                    request.output_dir.mkdir(parents=True, exist_ok=True)
                    (request.output_dir / "result.txt").write_text(
                        "ok", encoding="utf-8"
                    )
                    (request.output_dir / "result.srt").write_text(
                        "srt", encoding="utf-8"
                    )
                    (request.output_dir / "result.vtt").write_text(
                        "vtt", encoding="utf-8"
                    )
                    (request.output_dir / "result.json").write_text(
                        "{}", encoding="utf-8"
                    )
                    if on_log is not None:
                        await on_log("fake openai ok")
                    return None

            with tempfile.TemporaryDirectory() as tmp:
                storage = JobStorage(Path(tmp))
                manifest = storage.create_job(
                    io.BytesIO(b"fake audio"),
                    "input.wav",
                    JobOptions(output_formats=["txt", "json"]),
                )

                runner = FakeRunner(
                    storage,
                    OpenAIWhisperXRunnerConfig(base_url="http://localhost:9000/v1"),
                )
                await runner.start_job(manifest.job_id)

                updated = storage.read_manifest(manifest.job_id)
                self.assertEqual(updated.status, JobStatus.succeeded)
                self.assertEqual(
                    {artifact.format for artifact in updated.artifacts}, {"txt", "json"}
                )
                self.assertTrue(
                    any(
                        event.message == "fake openai ok"
                        for event in storage.read_events(manifest.job_id)
                    )
                )

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
