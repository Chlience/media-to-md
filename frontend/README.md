# Media-to-MD 前端

前端是 React + TypeScript + Vite 单页应用，提供普通转换工作台和管理员页面。

## 路由

- `/#/`：普通工作台，上传音视频或 PDF，查看当前任务状态并下载 artifacts ZIP。
- `/#/admin`：管理员页面，登录后维护后端运行配置、查看任务列表/详情/事件/日志并删除任务。

## 启动

```bash
cd frontend
npm install
MEDIA_TO_MD_API_BASE_URL=http://localhost:8000/api npm run dev
```

构建：

```bash
npm run build
```

测试：

```bash
npm run test
npm run typecheck
```

## API 地址

前端启动/构建时读取 `MEDIA_TO_MD_API_BASE_URL`。未设置时默认使用：

```text
http://localhost:8000/api
```

前端文件选择会先按 `MEDIA_TO_MD_MAX_UPLOAD_MB` 拒绝超限文件；未设置时默认 `512` MB。

注意：

- 修改环境变量后需要重启 Vite dev server；生产包需要重新 `npm run build`。
- 如果写 `.env` 文件，应放在 `frontend/.env`，或在启动命令前显式导出变量。
- 管理页只读展示当前启动配置；浏览器本地不再保存或覆盖 API 地址。

## 页面行为

普通工作台：

- 只暴露必要参数：音视频语言、PDF Markdown 清洗力度。
- 上传后轮询任务状态。
- 不展示运行日志或文档正文预览。
- 任务成功后提供 artifacts ZIP 下载。

管理页：

- 登录弹窗保护管理能力。
- 支持按任务类型和状态筛选，分页展示。
- 详情中展示 metadata、artifacts、事件时间线和可滚动运行日志。
- 运行配置只展示保留的 WhisperX / OpenDataLoader PDF 常用参数。

## 代码结构

```text
src/api/              后端 API client
src/components/       通用 UI 组件
src/pages/            WorkbenchPage 与 AdminPage
src/services/         session、下载辅助
src/types/            API 类型与解析器
src/styles/           页面样式
```
