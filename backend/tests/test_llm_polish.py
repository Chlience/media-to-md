from __future__ import annotations

from io import BytesIO

from app.llm_polish import (
    LlmPolishConfig,
    check_llm_connection,
    fetch_llm_models,
    polish_job_outputs,
    resolve_llm_base_url,
)
from app.models import JobOptions
from app.storage import JobStorage
from app.srt_text import write_plain_text_from_srt


def test_llm_provider_defaults_resolve_to_openai_compatible_v1():
    assert resolve_llm_base_url("deepseek", None) == "https://api.deepseek.com/v1"
    assert resolve_llm_base_url("custom", "http://localhost:11434") == "http://localhost:11434/v1"
    assert (
        resolve_llm_base_url("custom", "http://localhost:11434/v1/chat/completions")
        == "http://localhost:11434/v1"
    )


def test_fetch_models_parse_openai_compatible_payload(monkeypatch):
    def fake_request_json(method, url, payload, config):
        assert method == "GET"
        assert url == "http://llm.local/v1/models"
        assert payload is None
        assert config.api_key == "secret"
        return {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    monkeypatch.setattr("app.llm_polish._request_json", fake_request_json)
    config = LlmPolishConfig(
        enabled=True,
        provider="custom",
        base_url="http://llm.local/v1",
        api_key="secret",
        model="model-a",
    )

    assert fetch_llm_models(config) == ["model-a", "model-b"]


def test_connection_check_uses_short_chat_completion_request(monkeypatch):
    seen_payloads = []

    def fake_request_json(method, url, payload, config):
        assert method == "POST"
        assert url == "http://llm.local/v1/chat/completions"
        assert config.api_key == "secret"
        assert config.timeout_seconds == 10.0
        assert payload["model"] == "model-a"
        assert payload["max_tokens"] == 4
        seen_payloads.append(payload)
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr("app.llm_polish._request_json", fake_request_json)
    config = LlmPolishConfig(
        enabled=True,
        provider="custom",
        base_url="http://llm.local/v1",
        api_key="secret",
        model="model-a",
        timeout_seconds=120,
    )

    ok, message, models = check_llm_connection(config)
    assert ok is True
    assert "chat/completions 测试" in message
    assert "10s 超时" in message
    assert models == []
    assert seen_payloads[0]["messages"][1]["content"] == "ping"


def test_connection_check_accepts_empty_chat_completion_content(monkeypatch):
    def fake_request_json(method, url, payload, config):
        assert method == "POST"
        assert url == "http://llm.local/v1/chat/completions"
        assert config.timeout_seconds == 10.0
        return {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}

    monkeypatch.setattr("app.llm_polish._request_json", fake_request_json)
    ok, message, models = check_llm_connection(
        LlmPolishConfig(
            enabled=True,
            provider="custom",
            base_url="http://llm.local/v1",
            api_key="secret",
            model="model-a",
        )
    )

    assert ok is True
    assert "chat/completions 测试" in message
    assert models == []


def test_polish_job_outputs_creates_markdown_llm_artifact(monkeypatch, tmp_path):
    seen_payloads = []

    def fake_request_json(method, url, payload, config):
        assert method == "POST"
        assert url == "http://llm.local/v1/chat/completions"
        assert payload["model"] == "local-model"
        seen_payloads.append(payload)
        return {"choices": [{"message": {"content": "纠错后的正文。"}}]}

    monkeypatch.setattr("app.llm_polish._request_json", fake_request_json)
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(
        BytesIO(b"audio"),
        "sample.wav",
        JobOptions(task_type="whisperx", model="small", llm_polish=True),
    )
    output = storage.job_dir(manifest.job_id) / "output"
    srt_path = output / "result.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nraw transcript\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nASR mistak\n",
        encoding="utf-8",
    )
    write_plain_text_from_srt(srt_path, output / "result.txt")

    result = polish_job_outputs(
        storage,
        manifest.job_id,
        task_type="whisperx",
        config=LlmPolishConfig(
            enabled=True,
            provider="custom",
            base_url="http://llm.local/v1",
            model="local-model",
        ),
    )

    assert result.skipped_reason is None
    assert [path.name for path in result.created_paths] == ["llm_polished.md"]
    artifacts = storage.discover_output_artifacts(manifest.job_id)
    by_name = {artifact.name: artifact for artifact in artifacts}
    assert by_name["llm_polished.md"].format == "markdown_llm"
    assert (output / "llm_polished.md").read_text(encoding="utf-8") == "纠错后的正文。\n"
    prompt = seen_payloads[0]["messages"][1]["content"]
    assert "raw transcript" in prompt
    assert "ASR mistak" in prompt
    assert "00:00:00,000" not in prompt
    assert "\n1\n" not in f"\n{prompt}\n"
    assert "不要总结" in prompt


def test_pdf_polish_prompt_does_not_use_srt_language(monkeypatch, tmp_path):
    seen_payloads = []

    def fake_request_json(method, url, payload, config):
        seen_payloads.append(payload)
        return {"choices": [{"message": {"content": "校对后的文档。"}}]}

    monkeypatch.setattr("app.llm_polish._request_json", fake_request_json)
    storage = JobStorage(tmp_path)
    manifest = storage.create_job(
        BytesIO(b"%PDF"),
        "sample.pdf",
        JobOptions(task_type="pdf", llm_polish=True),
    )
    output = storage.job_dir(manifest.job_id) / "output"
    (output / "result.md").write_text("# Title\n\nPDF text", encoding="utf-8")

    result = polish_job_outputs(
        storage,
        manifest.job_id,
        task_type="pdf",
        config=LlmPolishConfig(
            enabled=True,
            provider="custom",
            base_url="http://llm.local/v1",
            model="local-model",
        ),
    )

    assert [path.name for path in result.created_paths] == ["result_llm.md"]
    prompt = seen_payloads[0]["messages"][1]["content"]
    assert "原始文档提取文本" in prompt
    assert "SRT" not in prompt
    assert "不要总结" in prompt
