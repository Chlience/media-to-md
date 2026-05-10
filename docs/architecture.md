# 架构说明

Media-to-MD 采用本地单机架构：浏览器前端调用 FastAPI 后端，后端在本机文件系统中管理任务；PDF 直接调用本机 CLI，音视频可直接调用本机 WhisperX CLI，也可调用 OpenAI 兼容 WhisperX HTTP 服务。

## 组件

```text
Browser
  │
  ├─ React/Vite 前端
  │   ├─ 普通工作台：上传、状态、下载
  │   └─ 管理页：登录、配置、任务、日志
  │
  └─ FastAPI 后端
      ├─ API routes
      ├─ JobStorage：manifest / artifacts / events / logs
      ├─ WhisperX CLI runner：whisperx argv
      ├─ WhisperX OpenAI runner：/v1/audio/transcriptions HTTP multipart
      └─ PDF runner：opendataloader-pdf argv + markdown_clear 后处理
```

## 任务生命周期

1. 前端上传文件和少量公开参数。
2. 后端创建 `<data_root>/jobs/<job_id>/`。
3. 后端写入 manifest、事件和空日志文件。
4. runner 按任务类型和配置执行：CLI runner 以 argv 列表启动外部命令；OpenAI runner 发起 HTTP multipart 请求。
5. 后端将运行日志或 HTTP 调用摘要追加到 `logs/job.log` 并生成事件。
6. 任务结束后发现 `output/` 下允许的 artifact，写回 manifest。
7. 前端通过状态/结果接口展示任务并下载 ZIP。

## 存储边界

任务目录结构：

```text
jobs/<job_id>/
  input/<upload>
  output/<artifacts>
  logs/job.log
  logs/events.jsonl
  manifest.json
```

下载接口只允许访问 manifest 中登记的 artifacts。日志不作为普通 artifact 暴露，只能通过管理员日志接口查看或下载。

## 配置边界

后端配置文件是 `backend/config.json`。管理页保存配置时会写回该文件。为了保持任务输出可收集，PDF 配置不开放自定义输出目录、标准输出重定向、图片目录或远程 Hybrid URL。

## 安全假设

当前版本假设服务运行在可信本地或内网环境中：

- 单管理员账号保护管理页。
- 公开页面可提交任务和下载公开 artifacts。
- 不提供公网级身份、配额、租户隔离或审计能力。
- 外部 CLI、OpenAI 兼容 WhisperX 服务和模型文件由部署者自行安装、配置和信任。
