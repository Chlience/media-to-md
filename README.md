<h1 align="center">Media-to-MD</h1>

<p align="center">
  <strong>A self-hosted audio, video, and PDF to Markdown workspace.</strong>
</p>

<p align="center">
  <a href="./README_zh.md">中文</a> · <a href="#deployment-guide">Deployment Guide</a> · <a href="#configuration">Configuration</a> · <a href="#verification">Verification</a> · <a href="#documentation">Documentation</a>
</p>

<p align="center">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi" />
  <img alt="React" src="https://img.shields.io/badge/React-frontend-61DAFB?logo=react" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-typed-blue?logo=typescript" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-build-646CFF?logo=vite" />
  <img alt="Vitest" src="https://img.shields.io/badge/Vitest-tested-6E9F18?logo=vitest" />
  <img alt="Storage" src="https://img.shields.io/badge/storage-local%20filesystem-orange" />
</p>

---

## What is Media-to-MD?

Media-to-MD is a self-hosted workspace for converting audio, video, and PDF files into Markdown-oriented artifacts such as Markdown, TXT, SRT, VTT, and JSON.

It is designed for a personal workstation or an internal server. Public SaaS hosting, multi-tenant isolation, GPU scheduling, HTTPS certificates, and Docker orchestration are intentionally left to the deployment environment.

## Features

- Audio/video transcription through either a local `whisperx` CLI or an OpenAI-compatible WhisperX HTTP service, producing SRT plus TXT derived from the returned SRT.
- WhisperX OpenAI mode supports admin-side `/models` discovery and runtime stage display when the remote service advertises the progress sidecar.
- PDF parsing through a local `opendataloader-pdf` CLI, including raw Markdown/TXT and cleaned `*_clear.md` output.
- Optional LLM polishing can be enabled separately for WhisperX transcripts and OpenDataLoader PDF outputs.
- Web workbench for drag-and-drop uploads, task polling, status display, and `artifacts.zip` downloads.
- Admin page for single-admin login, task list, details, events, logs, deletion, and backend runtime configuration.
- Local filesystem storage for uploads, outputs, logs, events, and manifests.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI, uv, pytest |
| Frontend | React, TypeScript, Vite, Vitest |
| Media runner | Local `whisperx` CLI or OpenAI-compatible WhisperX HTTP service |
| PDF runner | Local `opendataloader-pdf` CLI |
| Storage | Local filesystem job directory |

## Deployment Guide

### 1. Install system dependencies

Ubuntu / Debian example:

```bash
sudo apt update
sudo apt install -y ffmpeg openjdk-17-jre
```

WhisperX normally needs `ffmpeg` for media processing. PDF parsing requires Java 11+.

### 2. Choose the media transcription backend

#### Option A: local WhisperX CLI

Use this when Media-to-MD should run WhisperX directly on the backend machine:

```bash
uv tool install --python 3.12 whisperx
uv tool install --python 3.12 opendataloader-pdf
uv tool update-shell
```

If you need OpenDataLoader PDF Hybrid/OCR support:

```bash
uv tool install --python 3.12 "opendataloader-pdf[hybrid]"
opendataloader-pdf-hybrid --port 5002
```

Verify that the backend process can find the commands:

```bash
whisperx --help
opendataloader-pdf --help
java -version
ffmpeg -version
```

#### Option B: OpenAI-compatible WhisperX service

Use this when GPU work, model loading, or WhisperX execution should live in a separate process or internal server.

For local deployment, you can use:

<https://github.com/Chlience/whisperx-openai-server>

After starting that service, point `whisperx_openai_base_url` to its `/v1` endpoint:

```json
{
  "whisperx_backend": "openai",
  "whisperx_openai_base_url": "http://localhost:9000/v1",
  "whisperx_openai_api_key": null,
  "whisperx_openai_model": "large-v2"
}
```

Use a model id returned by the remote `/v1/models` endpoint. The admin page can request `OpenAI Base URL + /models`, show the returned ids in a selector, and write the selected id back to `whisperx_openai_model`.

In OpenAI mode, Media-to-MD sends synchronous `/v1/audio/transcriptions` multipart requests with `response_format=srt` and diarization enabled, then derives `result.txt` from `result.srt` by removing SRT sequence and timestamp lines. Before that remote request it can transcode the accepted upload to a temporary 16 kHz mono MP3 payload (`whisperx_openai_transcode_to_mp3`, enabled by default; bitrate controlled by `whisperx_openai_mp3_bitrate`, default `64k`) to reduce the second-hop upload size and avoid remote 413 errors. It forwards only request-level options that belong in the remote multipart request: `batch_size`, `chunk_size`, `no_align`, `min_speakers`, `max_speakers`, and `speaker_embeddings`.

Runtime and model-loading details stay on the WhisperX service: device, compute type, cache paths, diarization model, and align model are not forwarded by Media-to-MD. The align model is selected by WhisperX from the detected language unless the remote service itself is configured otherwise.

If the remote service is `whisperx-openai-server` and `/health` advertises runtime progress, Media-to-MD attaches the configured request-id header and polls the sidecar progress endpoint to show the current stage and current-stage progress. Other OpenAI-compatible transcription services remain usable without that sidecar.

### 3. Configure the backend

```bash
cp backend/config.example.json backend/config.json
```

At minimum, change the admin password:

```json
{
  "admin_username": "admin",
  "admin_password": "change-me-before-use"
}
```

## Configuration

Common backend config keys:

| Key | Purpose |
| --- | --- |
| `data_root` | Job data directory |
| `whisperx_backend` | `cli` or `openai` |
| `whisperx_cli_model` | Default model for local CLI mode |
| `whisperx_openai_model` | Default model for OpenAI-compatible mode |
| `whisperx_model_dir` | Local model cache directory |
| `model_cache_only` | Whether to use local model cache only |
| `whisperx_cli_args` | Local CLI mode arguments |
| `whisperx_openai_args` | OpenAI multipart overrides: `batch_size`, `chunk_size`, `no_align`, `min_speakers`, `max_speakers`, `speaker_embeddings` |
| `whisperx_openai_transcode_to_mp3` / `whisperx_openai_mp3_bitrate` | Whether OpenAI-compatible mode should transcode the accepted upload to a temporary MP3 before posting to the remote service, and the target bitrate such as `64k` |
| `opendataloader_pdf_args` | PDF runner arguments |
| `whisperx_llm_polish_enabled` / `pdf_llm_polish_enabled` | Separate backend-controlled LLM polishing switches for WhisperX and PDF tasks |
| `llm_polish_*` | Shared LLM polishing provider, base URL, API key, model, and timeout |
| `max_whisperx_upload_mb` / `max_pdf_upload_mb` | Separate upload-size limits for audio/video transcription and PDF parsing; exposed via `/api/health` and editable from the admin page |
| `admin_username` / `admin_password` | Admin page credentials |

The complete reference is `backend/config.example.json`. Saving settings from the admin page writes back to `backend/config.json`.

### 4. Start the backend

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Default API URL:

```text
http://localhost:8000/api
```

Swagger / OpenAPI:

```text
http://localhost:8000/docs
```

### 5. Start the frontend

```bash
cd frontend
npm install
MEDIA_TO_MD_API_BASE_URL=http://localhost:8000/api npm run dev
```

Open the Vite URL in your browser:

- Workbench: `/#/`
- Admin page: `/#/admin`

`MEDIA_TO_MD_API_BASE_URL` is a frontend startup/build-time variable. Restart the Vite dev server after changing it; production bundles must be rebuilt. The admin page displays the current API URL as read-only and does not write browser-local overrides.

### 6. Build for production

Run the backend under your preferred process manager or reverse proxy. Build the frontend like this:

```bash
cd frontend
MEDIA_TO_MD_API_BASE_URL=https://your-domain.example/api npm run build
```

Static assets are written to:

```text
frontend/dist/
```

For public access, put HTTPS, domain routing, access control, and upload-size limits in front of the app.

## Job Data

Each job is stored under:

```text
<data_root>/jobs/<job_id>/
  input/               Uploaded file
  output/              Conversion artifacts
  logs/job.log         Runtime log
  logs/events.jsonl    Job events
  manifest.json        Job metadata and artifact manifest
```

The frontend downloads results as `artifacts.zip` by default.

## Verification

Backend:

```bash
cd backend
uv run pytest
uv run --with ruff ruff check .
```

Frontend:

```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

## Documentation

- [Local setup and smoke test](docs/local-setup.md)
- [Architecture](docs/architecture.md)
- [Direct CLI runner contract](docs/direct-cli-runners.md)
- [WhisperX model cache and diarization](docs/whisperx-cache-and-diarization.md)
- [WhisperX OpenAI-compatible backend](docs/whisperx-openai-backend.md)
