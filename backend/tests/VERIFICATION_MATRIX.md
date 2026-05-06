# 验证矩阵

本文件记录发布前应覆盖的核心质量门禁，便于维护测试与需求的对应关系。

| 需求 | 覆盖 |
| --- | --- |
| 上传、manifest、状态、结果、下载 | `test_api.py`, `test_api_security_contract.py`, `test_manifest_storage_contract.py` |
| WhisperX 直接 argv 与无 shell 调用 | `test_whisperx_runner.py`, `test_runner_command_contract.py` |
| PDF 直接 argv、Java/命令缺失可读错误 | `test_opendataloader_pdf_runner.py`, `test_opendataloader_pdf_runner_contract.py` |
| 后端配置 allowlist 与拒绝危险 PDF 参数 | `test_config.py`, `test_opendataloader_pdf_contract.py` |
| `markdown_clear` 与 `<origin>_clear.md` 后处理 | `test_opendataloader_pdf_postprocess.py`, `test_storage.py` |
| 管理员登录、账号、配置、任务列表、事件、日志、删除 | `test_api.py`, `test_opendataloader_pdf_contract.py` |
| 前端工作台和管理页静态行为 | `frontend/src/App.test.tsx` |

## 必跑命令

```bash
cd backend
uv run pytest
uv run --with ruff ruff check .
```

```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

真实 PDF 烟测需要本机存在 Java 和 `opendataloader-pdf`；真实音视频烟测需要本机存在 `whisperx` 和模型缓存或网络下载能力。
